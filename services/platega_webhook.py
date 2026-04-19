"""
Обработчик webhook'ов Platega для автоматической выдачи подписок.
Поддержка типов: subscription, traffic, gift.
"""

import json
from aiogram import Bot
from loguru import logger
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from decimal import Decimal

from config import settings
from database.models import User, PaymentInvoice, Transaction, GiftCode
from services.marzban_api import marzban_service
from sqlalchemy import select
from database.engine import get_session_factory


async def handle_platega_webhook_update(data: Dict[str, Any], bot: Bot) -> Dict[str, str]:
    logger.info("=" * 50)
    logger.info("💰 PLATEGA WEBHOOK получен")
    logger.info("=" * 50)
    logger.info(f"Данные: {data}")

    try:
        status = str(data.get("status") or data.get("Status") or data.get("STATUS", "")).upper()
        if status not in ("CONFIRMED", "SUCCESS", "PAID", "COMPLETED"):
            return {"status": "ok", "message": "Статус не требует обработки"}

        order_id = data.get("payload") or data.get("order_id") or data.get("orderId")
        amount = Decimal(str(data.get("amount") or data.get("Amount") or data.get("total") or 0))
        currency = data.get("currency") or data.get("Currency") or "RUB"

        if not order_id:
            return {"status": "error", "message": "Отсутствует order_id"}

        result = await process_platega_payment(order_id, amount, currency, bot)
        return {"status": "ok", "message": "Обработано"}

    except Exception as e:
        logger.error(f"❌ Ошибка обработки webhook: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {"status": "error", "message": str(e)}


async def process_platega_payment(order_id: str, amount: Decimal, currency: str, bot: Bot) -> bool:
    parts = str(order_id).split("_")
    if len(parts) < 3:
        logger.error(f"Invalid order_id format: {order_id}")
        return False

    if parts[0] == "platega":
        try:
            user_telegram_id = int(parts[1])
        except ValueError:
            logger.error(f"Cannot parse user_id: {order_id}")
            return False
    else:
        logger.error(f"Cannot parse order_id: {order_id}")
        return False

    async with get_session_factory()() as session:
        result = await session.execute(select(User).where(User.user_id == user_telegram_id))
        user = result.scalar_one_or_none()
        if not user:
            logger.error(f"User not found: {user_telegram_id}")
            return False

        existing = await session.execute(select(PaymentInvoice).where(PaymentInvoice.invoice_id == str(order_id)))
        invoice = existing.scalar_one_or_none()

        payment_type = "subscription"
        days = 30
        tier = "standard"
        device_count = 1
        gb_limit = 0
        traffic_gb = 0

        if invoice and invoice.payload:
            try:
                payload_data = json.loads(invoice.payload)
                payment_type = payload_data.get("type", "subscription")
                days = payload_data.get("days", 30)
                tier = payload_data.get("tier", "standard")
                device_count = payload_data.get("device_count", 1)
                gb_limit = payload_data.get("gb_limit", 0)
                traffic_gb = payload_data.get("gb", 0)
            except Exception as e:
                logger.warning(f"Failed to parse payload: {e}")

        if invoice and invoice.status == "paid":
            return True

        if invoice:
            invoice.status = "paid"
        else:
            invoice = PaymentInvoice(
                user_id=user_telegram_id, invoice_id=str(order_id),
                amount=float(amount), currency="RUB", payment_method="platega",
                status="paid", payload=json.dumps({"days": days, "tier": tier, "device_count": device_count}),
                created_at=datetime.utcnow()
            )
            session.add(invoice)

        # ==========================================
        # ТИП: ДОКУПКА ТРАФИКА
        # ==========================================
        if payment_type == "traffic":
            return await _process_traffic_payment(session, bot, user, invoice, amount, traffic_gb)

        # ==========================================
        # ТИП: ПОДАРОК
        # ==========================================
        if payment_type == "gift":
            return await _process_gift_payment(session, bot, user, invoice, amount, tier, days, gb_limit)

        # ==========================================
        # ТИП: ПОДПИСКА
        # ==========================================
        return await _process_subscription_payment(session, bot, user, invoice, amount, days, tier, device_count, gb_limit)


async def _process_traffic_payment(session, bot, user, invoice, amount, traffic_gb) -> bool:
    user_id = user.user_id
    tx = Transaction(
        user_id=user_id, amount=float(amount), currency="RUB",
        payment_method="platega_traffic", status="paid",
        payment_id=invoice.invoice_id,
        description=f"Докупка +{traffic_gb} ГБ трафика (Platega)"
    )
    session.add(tx)

    current_gb = user.gb_limit or 0
    user.gb_limit = current_gb + traffic_gb

    if user.marzban_username:
        try:
            new_limit_bytes = int(user.gb_limit * 1024**3)
            await marzban_service.update_user_data_limit(user.marzban_username, new_limit_bytes)
        except Exception as e:
            logger.error(f"Ошибка обновления лимита Marzban: {e}")

    await session.commit()

    await bot.send_message(user_id,
        f"✅ <b>Трафик докуплен!</b>\n\n"
        f"📶 Добавлено: <b>+{traffic_gb} ГБ</b>\n"
        f"📊 Новый лимит: <b>{user.gb_limit} ГБ</b>\n"
        f"💰 Сумма: <b>{amount:.2f} RUB</b>",
        parse_mode="HTML"
    )
    return True


async def _process_gift_payment(session, bot, user, invoice, amount, tier, days, gb) -> bool:
    import uuid
    user_id = user.user_id
    tx = Transaction(
        user_id=user_id, amount=float(amount), currency="RUB",
        payment_method="platega_gift", status="paid",
        payment_id=invoice.invoice_id,
        description=f"Подарочная подписка {days} дней ({tier}) (Platega)"
    )
    session.add(tx)

    code = str(uuid.uuid4())
    gift = GiftCode(
        code=code, creator_id=user_id, tier=tier, days=days, gb_limit=gb,
        expires_at=datetime.utcnow() + timedelta(days=30)
    )
    session.add(gift)
    await session.commit()

    bot_info = await bot.get_me()
    gift_link = f"https://t.me/{bot_info.username}?start=gift_{code}"

    await bot.send_message(user_id,
        f"🎁 <b>Подарочная подписка оплачена!</b>\n\n"
        f"Отправьте эту ссылку другу:\n\n"
        f"<code>{gift_link}</code>\n\n"
        f"⏳ Код действителен <b>30 дней</b>.",
        parse_mode="HTML"
    )
    return True


async def _process_subscription_payment(session, bot, user, invoice, amount, days, tier, device_count, gb_limit) -> bool:
    user_telegram_id = user.user_id

    prev_paid_tx = await session.execute(
        select(Transaction).where(Transaction.user_id == user_telegram_id)
        .where(Transaction.status == "paid").limit(1)
    )
    is_first_payment = prev_paid_tx.scalar_one_or_none() is None

    transaction = Transaction(
        user_id=user_telegram_id, amount=float(amount), currency="RUB",
        payment_method="platega", status="paid", payment_id=invoice.invoice_id,
        description=f"Оплата подписки на {days} дней ({'VIP' if tier == 'premium' else 'Обычный'}) | Устройств: {device_count}"
    )
    session.add(transaction)

    now = datetime.utcnow()
    is_extension = bool(user.expire_date and user.expire_date > now)
    if is_extension:
        user.expire_date = user.expire_date + timedelta(days=days)
    else:
        user.expire_date = now + timedelta(days=days)

    user.tier = tier
    if device_count > 0:
        user.device_count = device_count
    if gb_limit > 0:
        current_gb = user.gb_limit or 0
        user.gb_limit = current_gb + gb_limit

    try:
        if user.marzban_username:
            mz_user = await marzban_service.get_user(user.marzban_username)
            if mz_user:
                await marzban_service.update_user_full(user.marzban_username, extra_days=days, tier=tier, device_count=device_count, data_limit_gb=gb_limit)
            else:
                new_user = await marzban_service.create_user(user_telegram_id, user.username, days, data_limit_gb=gb_limit, tier=tier, device_count=device_count)
                user.marzban_username = new_user.get("username")
        else:
            new_user = await marzban_service.create_user(user_telegram_id, user.username, days, data_limit_gb=gb_limit, tier=tier, device_count=device_count)
            user.marzban_username = new_user.get("username")
    except Exception as e:
        logger.error(f"❌ Marzban error: {e}")

    referrers_bonuses = []
    try:
        percentages = settings.referral_percentages_list
        current_referrer_id = user.referrer_id
        for level, pct in enumerate(percentages, 1):
            if not current_referrer_id: break
            ref_result = await session.execute(select(User).where(User.user_id == current_referrer_id))
            referrer = ref_result.scalar_one_or_none()
            if not referrer: break
            bonus = float(amount) * (pct / 100.0)
            referrer.referral_balance += bonus

            bonus_days_msg = ""
            if level == 1 and is_first_payment:
                referrer.refs_paid_count += 1
                bonus_days = 0
                if referrer.refs_paid_count == 1: bonus_days = 5
                elif referrer.refs_paid_count == 5: bonus_days = 14
                elif referrer.refs_paid_count == 10: bonus_days = 30
                if bonus_days > 0:
                    ref_now = datetime.utcnow()
                    if referrer.expire_date and referrer.expire_date > ref_now:
                        referrer.expire_date += timedelta(days=bonus_days)
                    else:
                        referrer.expire_date = ref_now + timedelta(days=bonus_days)
                    if referrer.marzban_username:
                        try:
                            await marzban_service.update_user_expiry(referrer.marzban_username, bonus_days, tier=referrer.tier)
                        except Exception:
                            pass
                    bonus_days_msg = f"\n🎁 <b>Бонус за {referrer.refs_paid_count}-го друга:</b> +{bonus_days} дней VPN!"

            referrers_bonuses.append({'level': level, 'id': referrer.user_id, 'username': referrer.username, 'bonus': bonus})
            try:
                await bot.send_message(referrer.user_id,
                    f"💸 <b>Реферальное начисление!</b>\n\n"
                    f"Ваш реферал (ID: {user_telegram_id}) пополнил баланс.\n"
                    f"Вам начислено: <b>+{bonus:.2f}₽</b> ({level} уровень, {pct}%){bonus_days_msg}\n\n"
                    f"Реферальный баланс: {referrer.referral_balance:.2f}₽",
                    parse_mode="HTML"
                )
            except Exception:
                pass
            current_referrer_id = referrer.referrer_id
    except Exception as e:
        logger.error(f"Ошибка реферальных: {e}")

    await session.commit()

    try:
        tier_name = "🚀 Обход белых списков (VIP)" if tier == "premium" else "🛡 Обычный VPN"
        sub_url = ""
        vless_link = ""
        if user.marzban_username:
            sub_url = await marzban_service.get_user_subscription(user.marzban_username)
            vless_link = await marzban_service.get_user_vless_link(user.marzban_username)

        msg = (
            f"✅ <b>Оплата прошла успешно!</b>\n\n"
            f"💎 Тариф: <b>{tier_name}</b>\n"
            f"⏳ Подписка: <b>{days} дней</b>\n"
            f"📱 Доступно устройств: <b>{user.device_count}</b>\n"
            f"💰 Сумма: <b>{amount:.2f} {currency}</b>\n\n"
        )
        if sub_url:
            msg += (
                f"🔑 <b>Ключ подписки:</b>\n<code>{sub_url}</code>\n\n"
                f"🔗 <b>VLESS ключ:</b>\n<code>{vless_link}</code>\n\n"
                f"Приятного пользования! 🎉"
            )
        else:
            msg += "🔗 Подписка активирована!"
        await bot.send_message(user_telegram_id, msg, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Failed to notify user: {e}")

    try:
        user_display = f" @{user.username}" if user.username else f"ID: {user_telegram_id}"
        referrer_line = "\n👥 Рефовод: Нет"
        if referrers_bonuses:
            ref_info = referrers_bonuses[0]
            ref_link = f" @{ref_info['username']}" if ref_info['username'] else f"ID: {ref_info['id']}"
            referrer_line = f"\n👥 Рефовод: {ref_link} (+{ref_info['bonus']:.2f}₽)"
        admin_msg = (
            f"💰 <b>Новое пополнение! (Platega)</b>\n\n"
            f"🆔 ID: <code>{user_telegram_id}</code>\n"
            f"👤 Профиль: {user_display}\n"
            f"💵 Сумма: <b>{amount:.2f}₽</b>\n"
            f"📦 Тариф: <b>{'VIP' if tier == 'premium' else 'Обычный'} ({days} дней)</b>\n"
            f"📱 Устройств: <b>{user.device_count}</b>{referrer_line}"
        )
        for admin_id in settings.admin_ids_list:
            try:
                await bot.send_message(admin_id, admin_msg, parse_mode="HTML")
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Ошибка уведомления админа: {e}")

    return True

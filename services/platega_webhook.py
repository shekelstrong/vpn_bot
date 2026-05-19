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
from services.xui_api import xui_service as marzban_service
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from database.engine import get_session_factory
from services.crypto_webhook import _process_referrer_bonuses


async def _ensure_user_for_webhook(session, tg_id: int) -> User:
    """Создать юзера в БД если его нет. Для webhook-обработчиков.
    Синхронизирует данные из Marzban если найдёт сиротский аккаунт."""
    result = await session.execute(select(User).where(User.user_id == tg_id))
    user = result.scalar_one_or_none()
    if user:
        return user

    import uuid as _uuid
    marzban_username = f"tg_{tg_id}_{_uuid.uuid4().hex[:6]}"

    # Попробовать найти сиротский 3x-ui аккаунт
    _found_orphan = False
    try:
        await marzban_service._ensure_login()
        for _inbound_id in (1, 2):
            inbound_data = await marzban_service._get_inbound(_inbound_id)
            for client in inbound_data.get("settings", {}).get("clients", []):
                email = client.get("email", "")
                if email.startswith(f"user_{tg_id}_") or email.startswith(f"tg_{tg_id}_"):
                    marzban_username = email
                    _found_orphan = True
                    break
            if _found_orphan:
                break
    except Exception as e:
        logger.warning(f"3x-ui lookup для сироты {tg_id}: {e}")

    user = User(user_id=tg_id, marzban_username=marzban_username)

    # Синхронизируем данные из 3x-ui если нашли сироту
    if marzban_username.startswith(f"user_{tg_id}_") or marzban_username.startswith(f"tg_{tg_id}_"):
        try:
            mz = await marzban_service.get_user(marzban_username)
            if mz:
                now = datetime.utcnow()
                expire_ts = mz.get("expire") or 0
                data_limit = mz.get("data_limit") or 0
                inbounds = mz.get("inbounds", {}).get("vless", [])

                if "vless-reality-whitelist" in inbounds:
                    user.tier = "premium"
                    if expire_ts > int(now.timestamp()):
                        user.expire_premium = datetime.utcfromtimestamp(expire_ts)
                else:
                    user.tier = "standard"
                    if expire_ts > int(now.timestamp()):
                        user.expire_standard = datetime.utcfromtimestamp(expire_ts)

                if expire_ts > 0:
                    user.expire_date = datetime.utcfromtimestamp(expire_ts) if expire_ts > int(now.timestamp()) else None

                if data_limit > 0:
                    user.gb_limit = round(data_limit / (1024**3), 2)

                user.device_count = mz.get("limitIp") or mz.get("ip_limit") or 1
                user.recalculate_expire_date()
                logger.info(f"🔧 [Platega] Синхронизированы данные 3x-ui для {tg_id}: tier={user.tier}")
        except Exception as e:
            logger.error(f"Ошибка синхронизации Marzban для {tg_id}: {e}")

    session.add(user)
    try:
        await session.commit()
        logger.info(f"🔧 [Platega] Авто-создан пользователь {tg_id} (marzban: {marzban_username})")
    except IntegrityError:
        await session.rollback()
        result = await session.execute(select(User).where(User.user_id == tg_id))
        user = result.scalar_one_or_none()
    return user


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

    # === Определяем платформу и парсим order_id ===
    is_vk_gift = order_id.startswith("vkgift_")
    is_vk = order_id.startswith("vk_") and not is_vk_gift

    if parts[0] == "platega":
        # TG заказ: platega_USERID_...
        try:
            user_telegram_id = int(parts[1])
        except ValueError:
            logger.error(f"Cannot parse user_id: {order_id}")
            return False
    elif is_vk or is_vk_gift:
        # VK заказ — создаём инвойс в БД, VK-бот polling всё обработает
        # (подписка, Marzban, уведомление в VK)
        prefix = "vkgift_" if is_vk_gift else "vk_"
        rest = order_id[len(prefix):]
        vk_parts = rest.split("_")
        if len(vk_parts) < 3:
            logger.error(f"Cannot parse VK order_id: {order_id}")
            return False
        try:
            vk_tier = vk_parts[0]
            vk_user_id = int(vk_parts[1])
            vk_days = int(vk_parts[2])
        except (ValueError, IndexError):
            logger.error(f"Cannot parse VK order_id fields: {order_id}")
            return False

        logger.info(f"VK Platega: VK order tier={vk_tier} vk_user_id={vk_user_id} days={vk_days} amount={amount}")

        try:
            async with get_session_factory()() as session:
                # Находим юзера по vk_id
                result = await session.execute(select(User).where(User.vk_id == vk_user_id))
                vk_user = result.scalar_one_or_none()
                if not vk_user:
                    logger.error(f"VK Platega: User vk_id={vk_user_id} not found")
                    return False

                # Проверяем что инвойс не создан ранее
                existing = await session.execute(select(PaymentInvoice).where(PaymentInvoice.invoice_id == str(order_id)))
                if existing.scalar_one_or_none():
                    logger.info(f"VK Platega: Invoice {order_id} already exists")
                    return True

                # Создаём инвойс со status=paid — VK-бот polling обработает активацию
                # Если у VK-юзера есть marzban_username, сохраняем его как marzban_username_vk
                vk_marzban = vk_user.marzban_username
                if vk_marzban and not vk_user.marzban_username_vk:
                    vk_user.marzban_username_vk = vk_marzban
                
                invoice = PaymentInvoice(
                    user_id=vk_user.user_id,
                    invoice_id=str(order_id),
                    amount=float(amount),
                    currency="RUB",
                    payment_method="platega",
                    status="paid",
                    payload=json.dumps({
                        "days": vk_days,
                        "tier": vk_tier,
                        "type": "gift" if is_vk_gift else "subscription",
                        "vk_user_id": vk_user_id,
                        "marzban_username_vk": vk_marzban or "",
                    }),
                    created_at=datetime.utcnow(),
                )
                session.add(invoice)
                await session.commit()
                logger.info(f"VK Platega: Invoice created for vk_id={vk_user_id}, VK polling will activate")
        except Exception as e:
            logger.error(f"VK Platega: Error creating invoice: {e}")
            return False

        return True
    else:
        logger.error(f"Cannot parse order_id: {order_id}")
        return False

    async with get_session_factory()() as session:
        result = await session.execute(select(User).where(User.user_id == user_telegram_id))
        user = result.scalar_one_or_none()
        if not user:
            logger.warning(f"⚠️ User {user_telegram_id} не найден в БД, авто-создание...")
            try:
                user = await _ensure_user_for_webhook(session, user_telegram_id)
            except Exception as e:
                logger.error(f"Не удалось создать юзера {user_telegram_id}: {e}")
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

    # Защита: не устанавливать лимит трафика для стандартного тарифа
    if user.tier != "premium":
        logger.warning(f"Попытка докупки трафика для стандартного тарифа: {user_id}. Пропускаем установку лимита.")
        await session.commit()
        await bot.send_message(user_id,
            "ℹ️ <b>У вас обычный VPN с безлимитным трафиком.</b>\n\n"
            "Докупка гигабайтов вам не нужна — трафик не ограничен!",
            parse_mode="HTML"
        )
        return True

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
            # Кумулятивно: берём used_traffic из Marzban и прибавляем новые ГБ
            mz_user = await marzban_service.get_user(user.marzban_username)
            if mz_user:
                used_bytes = mz_user.get("used_traffic") or 0
                new_limit_gb = used_bytes / (1024**3) + traffic_gb
                await marzban_service.update_user_data_limit(user.marzban_username, new_limit_gb)
            else:
                await marzban_service.update_user_data_limit(user.marzban_username, user.gb_limit)
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
    try:
        for admin_id in settings.admin_ids_list:
            await bot.send_message(admin_id,
                f"📦 <b>Докупка трафика (Platega)</b>\n"
                f"ID: <code>{user_id}</code>\n"
                f"+{traffic_gb} ГБ за {amount:.0f}₽",
                parse_mode="HTML")
    except: pass
    await _process_referrer_bonuses(session, bot, user, amount, "докупил трафик")
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
        f"{gift_link}\n\n"
        f"⏳ Код действителен <b>30 дней</b>.",
        parse_mode="HTML"
    )
    try:
        for admin_id in settings.admin_ids_list:
            await bot.send_message(admin_id,
                f"🎁 <b>Подарок оплачен (Platega)</b>\n"
                f"ID: <code>{user_id}</code>\n"
                f"Тариф: {'VIP' if tier == 'premium' else 'Стандарт'}, {days} дней\n"
                f"Сумма: {amount:.0f}₽",
                parse_mode="HTML")
    except: pass
    await _process_referrer_bonuses(session, bot, user, amount, "купил VPN в подарок")
    return True


async def _process_subscription_payment(session, bot, user, invoice, amount, days, tier, device_count, gb_limit, currency="RUB") -> bool:
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

    # Раздельные сроки по тарифам
    if tier == "premium":
        if user.expire_premium and user.expire_premium > now:
            user.expire_premium = user.expire_premium + timedelta(days=days)
        else:
            user.expire_premium = now + timedelta(days=days)
    else:
        if user.expire_standard and user.expire_standard > now:
            user.expire_standard = user.expire_standard + timedelta(days=days)
        else:
            user.expire_standard = now + timedelta(days=days)

    user.recalculate_expire_date()
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
                # Собираем активные inbound-ы
                active_inbounds = []
                if user.expire_standard and user.expire_standard > now:
                    active_inbounds.append("vless-reality-standard")
                if user.expire_premium and user.expire_premium > now:
                    active_inbounds.append("vless-reality-whitelist")
                await marzban_service.update_user_full(user.marzban_username, extra_days=days, tier=tier, device_count=device_count, data_limit_gb=gb_limit, inbounds=active_inbounds if active_inbounds else None)
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
                            await marzban_service.extend_user_expiry_light(referrer.marzban_username, bonus_days)
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
            f"💰 Сумма: <b>{amount:.2f} ₽</b>\n\n"
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

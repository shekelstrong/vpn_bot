"""
Обработчик webhook'ов CryptoPay для автоматической выдачи подписок.
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
from sqlalchemy.exc import IntegrityError
from database.engine import get_session_factory


async def _ensure_user_crypto(session, tg_id: int) -> User:
    """Создать юзера в БД если его нет. Для Crypto webhook.
    Синхронизирует данные из Marzban если найдёт сиротский аккаунт."""
    result = await session.execute(select(User).where(User.user_id == tg_id))
    user = result.scalar_one_or_none()
    if user:
        return user

    import uuid as _uuid
    marzban_username = f"tg_{tg_id}_{_uuid.uuid4().hex[:6]}"

    # Попробовать найти сиротский Marzban-аккаунт
    try:
        import httpx
        token = await marzban_service.get_token()
        headers = {"Authorization": f"Bearer {token}"}
        base = marzban_service.base_url
        async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
            resp = await client.get(f"{base}/users", headers=headers, params={"username": f"user_{tg_id}_"})
            if resp.status_code == 200:
                data = resp.json()
                for u in data.get("users", []):
                    uname = u.get("username", "")
                    if uname.startswith(f"user_{tg_id}_") or uname.startswith(f"tg_{tg_id}_"):
                        marzban_username = uname
                        break
    except Exception as e:
        logger.warning(f"Marzban lookup для сироты {tg_id}: {e}")

    user = User(user_id=tg_id, marzban_username=marzban_username)

    # Синхронизируем данные из Marzban если нашли сироту
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

                user.device_count = mz.get("ip_limit") or 1
                user.recalculate_expire_date()
                logger.info(f"🔧 [Crypto] Синхронизированы данные Marzban для {tg_id}: tier={user.tier}")
        except Exception as e:
            logger.error(f"Ошибка синхронизации Marzban для {tg_id}: {e}")

    session.add(user)
    try:
        await session.commit()
        logger.info(f"🔧 [Crypto] Авто-создан пользователь {tg_id} (marzban: {marzban_username})")
    except IntegrityError:
        await session.rollback()
        result = await session.execute(select(User).where(User.user_id == tg_id))
        user = result.scalar_one_or_none()
    return user


async def _process_referrer_bonuses(session, bot, user, amount, action_type="пополнил баланс"):
    """Начисление реферальных бонусов по 3 уровням (15/10/5%).
    Уведомляет рефоводов без указания кто именно."""
    try:
        percentages = settings.referral_percentages_list  # [15, 10, 5]
        current_referrer_id = user.referrer_id
        
        for level, pct in enumerate(percentages, 1):
            if not current_referrer_id: break
            ref_result = await session.execute(select(User).where(User.user_id == current_referrer_id))
            referrer = ref_result.scalar_one_or_none()
            if not referrer: break
            
            bonus = float(amount) * (pct / 100.0)
            referrer.referral_balance += bonus
            
            try:
                await bot.send_message(referrer.user_id,
                    f"💸 <b>Реферальное начисление!</b>\n\n"
                    f"Ваш реферал {action_type}.\n"
                    f"Вам начислено: <b>+{bonus:.2f}₽</b> ({level} уровень, {pct}%)\n\n"
                    f"Реферальный баланс: {referrer.referral_balance:.2f}₽",
                    parse_mode="HTML"
                )
            except: pass
            
            current_referrer_id = referrer.referrer_id
    except Exception as e:
        logger.error(f"Ошибка реферальных бонусов: {e}")


async def handle_crypto_webhook_update(data: Dict[str, Any], bot: Bot) -> Dict[str, str]:
    logger.info("=" * 50)
    logger.info("🪙 CRYPTO WEBHOOK получен")
    logger.info(f"📦 RAW DATA: {json.dumps(data, default=str, ensure_ascii=False)}")
    logger.info("=" * 50)
    
    try:
        update_type = data.get("update_type")
        if update_type != "invoice_paid":
            return {"status": "ok", "message": "Тип обновления не требует обработки"}

        payload = data.get("payload", {})
        status = payload.get("status")
        if status != "paid":
            return {"status": "ok", "message": "Статус не требует обработки"}

        invoice_id = str(payload.get("invoice_id"))
        amount = Decimal(str(payload.get("amount", 0)))
        asset = payload.get("asset", "USDT")
        fiat_amount = Decimal(str(payload.get("fiat_amount", 0)))
        fiat_currency = payload.get("fiat_currency", "RUB")
        
        raw_payload = payload.get("payload")
        logger.info(f"  raw_payload: {raw_payload!r}")

        order_id = None
        if raw_payload:
            try:
                parsed = json.loads(str(raw_payload))
                if isinstance(parsed, dict) and "user_id" in parsed:
                    order_id = invoice_id
                else:
                    order_id = str(raw_payload)
            except (json.JSONDecodeError, TypeError):
                order_id = str(raw_payload)

        if not order_id:
            order_id = invoice_id

        if fiat_amount > 0:
            process_amount = fiat_amount
        else:
            rate = getattr(settings, 'USDT_TO_RUB_RATE', 95.0)
            process_amount = amount * Decimal(str(rate))

        result = await process_crypto_payment(order_id, invoice_id, process_amount, bot)
        return {"status": "ok", "message": "Обработано"}

    except Exception as e:
        logger.error(f"❌ Ошибка обработки crypto webhook: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {"status": "error", "message": str(e)}


async def _find_invoice(session, order_id: str, cryptobot_invoice_id: str) -> Optional[PaymentInvoice]:
    result = await session.execute(select(PaymentInvoice).where(PaymentInvoice.invoice_id == str(order_id)))
    invoice = result.scalar_one_or_none()
    if invoice:
        return invoice

    if cryptobot_invoice_id and cryptobot_invoice_id != order_id:
        result = await session.execute(select(PaymentInvoice).where(PaymentInvoice.invoice_id == str(cryptobot_invoice_id)))
        invoice = result.scalar_one_or_none()
        if invoice:
            return invoice

    result = await session.execute(
        select(PaymentInvoice).where(PaymentInvoice.status == "pending")
        .where(PaymentInvoice.payment_method == "cryptopay")
        .order_by(PaymentInvoice.created_at.desc()).limit(10)
    )
    for inv in result.scalars().all():
        if inv.payload and str(order_id) in str(inv.payload):
            return inv

    try:
        numeric_id = int(order_id)
        result = await session.execute(select(PaymentInvoice).where(PaymentInvoice.id == numeric_id))
        invoice = result.scalar_one_or_none()
        if invoice:
            return invoice
    except (ValueError, TypeError):
        pass

    return None


async def process_crypto_payment(order_id: str, cryptobot_invoice_id: str, amount: Decimal, bot: Bot) -> bool:
    async with get_session_factory()() as session:
        invoice = await _find_invoice(session, order_id, cryptobot_invoice_id)
        if not invoice:
            logger.error(f"Invoice not found: order_id={order_id}")
            return False

        user_telegram_id = invoice.user_id
        result = await session.execute(select(User).where(User.user_id == user_telegram_id))
        user = result.scalar_one_or_none()
        if not user:
            logger.warning(f"⚠️ [Crypto] User {user_telegram_id} не найден в БД, авто-создание...")
            try:
                user = await _ensure_user_crypto(session, user_telegram_id)
            except Exception as e:
                logger.error(f"Не удалось создать юзера {user_telegram_id}: {e}")
                return False

        # Определяем тип платежа из payload
        payment_type = "subscription"
        days = 30
        tier = "standard"
        device_count = 1
        gb_limit = 0
        traffic_gb = 0
        gift_tier = "standard"
        gift_days = 30
        gift_gb = 0

        if invoice.payload:
            try:
                payload_data = json.loads(invoice.payload)
                payment_type = payload_data.get("type", "subscription")
                days = payload_data.get("days", 30)
                tier = payload_data.get("tier", "standard")
                device_count = payload_data.get("device_count", 1)
                gb_limit = payload_data.get("gb_limit", 0)
                traffic_gb = payload_data.get("gb", 0)
                gift_tier = payload_data.get("tier", "standard")
                gift_days = payload_data.get("days", 30)
                gift_gb = payload_data.get("gb", 0)
            except Exception as e:
                logger.warning(f"Failed to parse payload: {e}")

        if invoice.status == "paid":
            return True

        invoice.status = "paid"

        # ==========================================
        # ТИП: ДОКУПКА ТРАФИКА
        # ==========================================
        if payment_type == "traffic":
            return await _process_traffic_payment(session, bot, user, invoice, amount, traffic_gb)

        # ==========================================
        # ТИП: ПОДАРОК
        # ==========================================
        if payment_type == "gift":
            return await _process_gift_payment(session, bot, user, invoice, amount, gift_tier, gift_days, gift_gb)

        # ==========================================
        # ТИП: ПОДПИСКА (стандартная логика)
        # ==========================================
        return await _process_subscription_payment(session, bot, user, invoice, amount, days, tier, device_count, gb_limit)


async def _process_traffic_payment(session, bot, user, invoice, amount, traffic_gb) -> bool:
    """Обработка докупки трафика."""
    from database.models import Transaction
    
    user_id = user.user_id

    # Защита: не устанавливать лимит трафика для стандартного тарифа
    if user.tier != "premium":
        logger.warning(f"Попытка докупки трафика для стандартного тарифа: {user_id}. Пропускаем установку лимита.")
        await bot.send_message(user_id,
            "ℹ️ <b>У вас обычный VPN с безлимитным трафиком.</b>\n\n"
            "Докупка гигабайтов вам не нужна — трафик не ограничен!",
            parse_mode="HTML"
        )
        return True

    tx = Transaction(
        user_id=user_id, amount=float(amount), currency="RUB",
        payment_method="cryptopay_traffic", status="paid",
        payment_id=invoice.invoice_id,
        description=f"Докупка +{traffic_gb} ГБ трафика (Crypto)"
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
    
    # Notify admins
    try:
        for admin_id in settings.admin_ids_list:
            await bot.send_message(admin_id,
                f"📦 <b>Докупка трафика</b>\n"
                f"ID: <code>{user_id}</code>\n"
                f"+{traffic_gb} ГБ за {amount:.0f}₽\n"
                f"Новый лимит: {user.gb_limit} ГБ",
                parse_mode="HTML")
    except: pass
    
    logger.info(f"Трафик +{traffic_gb}ГБ для {user_id}")
    
    # Реферальные бонусы
    await _process_referrer_bonuses(session, bot, user, amount, "докупил трафик")
    return True


async def _process_gift_payment(session, bot, user, invoice, amount, tier, days, gb) -> bool:
    """Обработка оплаты подарочной подписки."""
    import uuid
    from database.models import Transaction, GiftCode

    user_id = user.user_id
    tx = Transaction(
        user_id=user_id, amount=float(amount), currency="RUB",
        payment_method="cryptopay_gift", status="paid",
        payment_id=invoice.invoice_id,
        description=f"Подарочная подписка {days} дней ({tier}) (Crypto)"
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
                f"🎁 <b>Подарок оплачен (Crypto)</b>\n"
                f"ID: <code>{user_id}</code>\n"
                f"Тариф: {'VIP' if tier == 'premium' else 'Стандарт'}, {days} дней\n"
                f"Сумма: {amount:.0f}₽",
                parse_mode="HTML")
    except: pass
    logger.info(f"Подарок {code} создан для {user_id}")
    
    # Реферальные бонусы
    await _process_referrer_bonuses(session, bot, user, amount, "купил VPN в подарок")
    return True


async def _process_subscription_payment(session, bot, user, invoice, amount, days, tier, device_count, gb_limit) -> bool:
    """Стандартная обработка подписки (из оригинального файла)."""
    from database.models import Transaction

    user_telegram_id = user.user_id

    prev_paid_tx = await session.execute(
        select(Transaction).where(Transaction.user_id == user_telegram_id)
        .where(Transaction.status == "paid").limit(1)
    )
    is_first_payment = prev_paid_tx.scalar_one_or_none() is None

    transaction = Transaction(
        user_id=user_telegram_id, amount=float(amount), currency="RUB",
        payment_method="cryptopay", status="paid", payment_id=invoice.invoice_id,
        description=f"Оплата подписки на {days} дней (Crypto) | Устройств: {device_count}"
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

    # Реферальные бонусы
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
                        except Exception as e:
                            logger.error(f"Ошибка бонусных дней: {e}")
                    bonus_days_msg = f"\n🎁 <b>Бонус за {referrer.refs_paid_count}-го друга:</b> +{bonus_days} дней VPN!"

            referrers_bonuses.append({'level': level, 'id': referrer.user_id, 'username': referrer.username, 'bonus': bonus})
            try:
                await bot.send_message(referrer.user_id,
                    f"💸 <b>Реферальное начисление!</b>\n\n"
                    f"Ваш реферал (ID: {user_telegram_id}) пополнил баланс криптовалютой.\n"
                    f"Вам начислено: <b>+{bonus:.2f}₽</b> ({level} уровень, {pct}%){bonus_days_msg}\n\n"
                    f"Реферальный баланс: {referrer.referral_balance:.2f}₽",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.warning(f"Failed to notify referrer: {e}")
            current_referrer_id = referrer.referrer_id
    except Exception as e:
        logger.error(f"Ошибка реферальных: {e}")

    await session.commit()

    # Уведомление пользователя
    try:
        tier_name = "🚀 Обход белых списков (VIP)" if tier == "premium" else "🛡 Обычный VPN"
        sub_url = ""
        vless_link = ""
        if user.marzban_username:
            sub_url = await marzban_service.get_user_subscription(user.marzban_username)
            vless_link = await marzban_service.get_user_vless_link(user.marzban_username)

        msg = (
            f"✅ <b>Оплата криптовалютой прошла успешно!</b>\n\n"
            f"💎 Тариф: <b>{tier_name}</b>\n"
            f"⏳ Подписка: <b>{days} дней</b>\n"
            f"📱 Доступно устройств: <b>{user.device_count}</b>\n"
            f"💰 Сумма: <b>{amount:.2f} RUB</b>\n\n"
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

    # Уведомление админов
    try:
        user_display = f" @{user.username}" if user.username else f"ID: {user_telegram_id}"
        referrer_line = "\n👥 Рефовод: Нет"
        if referrers_bonuses:
            ref_info = referrers_bonuses[0]
            ref_link = f" @{ref_info['username']}" if ref_info['username'] else f"ID: {ref_info['id']}"
            referrer_line = f"\n👥 Рефовод: {ref_link} (+{ref_info['bonus']:.2f}₽)"
        admin_msg = (
            f"🪙 <b>Новое пополнение! (CryptoPay)</b>\n\n"
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

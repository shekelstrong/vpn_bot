"""
Обработчик webhook'ов CryptoPay для автоматической выдачи подписок.
"""

import json
from aiogram import Bot
from loguru import logger
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from decimal import Decimal

from config import settings
from database.models import User, PaymentInvoice, Transaction
from services.marzban_api import marzban_service
from sqlalchemy import select, or_
from database.engine import get_session_factory


async def handle_crypto_webhook_update(data: Dict[str, Any], bot: Bot) -> Dict[str, str]:
    """Обработать обновление от CryptoPay webhook."""
    logger.info("=" * 50)
    logger.info("🪙 CRYPTO WEBHOOK получен")
    logger.info(f"📦 RAW DATA: {json.dumps(data, default=str, ensure_ascii=False)}")
    logger.info("=" * 50)
    
    try:
        update_type = data.get("update_type")
        if update_type != "invoice_paid":
            logger.info(f"Ignoring update_type: {update_type}")
            return {"status": "ok", "message": "Тип обновления не требует обработки"}

        payload = data.get("payload", {})
        status = payload.get("status")

        if status != "paid":
            logger.info(f"Ignoring crypto payment status: {status}")
            return {"status": "ok", "message": "Статус не требует обработки"}

        # Извлекаем данные инвойса
        invoice_id = str(payload.get("invoice_id"))
        amount = Decimal(str(payload.get("amount", 0)))
        asset = payload.get("asset", "USDT")
        fiat_amount = Decimal(str(payload.get("fiat_amount", 0)))
        fiat_currency = payload.get("fiat_currency", "RUB")
        
        # payload.payload — это то, что мы передали при создании инвойса.
        # В старом API (payment_crypto.py) это числовой ID инвойса из нашей БД.
        # В v2 API (crypto_bot_v2.py) это JSON-строка с user_id и days.
        raw_payload = payload.get("payload")
        logger.info(f"  raw_payload из CryptoBot: {raw_payload!r} (type: {type(raw_payload).__name__})")

        # Определяем order_id для поиска в БД
        order_id = None
        if raw_payload:
            # Пробуем распарсить как JSON (от v2 API)
            try:
                parsed = json.loads(str(raw_payload))
                if isinstance(parsed, dict) and "user_id" in parsed:
                    # Это от v2 API — ищем по user_id
                    logger.info(f"  Определён формат v2 API: user_id={parsed['user_id']}")
                    # Для v2 ищем инвойс по CryptoBot invoice_id
                    order_id = invoice_id
                else:
                    order_id = str(raw_payload)
            except (json.JSONDecodeError, TypeError):
                order_id = str(raw_payload)

        if not order_id:
            order_id = invoice_id

        logger.info(f"Платеж CryptoPay:")
        logger.info(f"  CryptoBot Invoice ID: {invoice_id}")
        logger.info(f"  Order ID (для поиска в БД): {order_id}")
        logger.info(f"  Amount: {amount} {asset} (~{fiat_amount} {fiat_currency})")
        logger.info(f"  Status: {status}")

        if not order_id:
            logger.error("No payload/order_id in webhook data")
            return {"status": "error", "message": "Отсутствует order_id"}

        # В качестве суммы зачисления используем фиатный эквивалент (в рублях)
        # Если fiat_amount = 0, пересчитываем по курсу из настроек
        if fiat_amount > 0:
            process_amount = fiat_amount
        else:
            rate = getattr(settings, 'USDT_TO_RUB_RATE', 95.0)
            process_amount = amount * Decimal(str(rate))
            logger.info(f"  fiat_amount=0, пересчёт: {amount} USDT × {rate} = {process_amount} RUB")

        result = await process_crypto_payment(order_id, invoice_id, process_amount, bot)

        return {"status": "ok", "message": "Подписка выдана"}

    except Exception as e:
        logger.error(f"❌ Ошибка обработки crypto webhook: {e}")
        import traceback
        logger.error(f"Traceback:\n{traceback.format_exc()}")
        return {"status": "error", "message": str(e)}


async def _find_invoice(session, order_id: str, cryptobot_invoice_id: str) -> Optional[PaymentInvoice]:
    """
    Надёжный поиск инвойса в БД с несколькими fallback-стратегиями.
    """
    # Стратегия 1: точное совпадение по invoice_id (наш внутренний ID)
    result = await session.execute(
        select(PaymentInvoice).where(PaymentInvoice.invoice_id == str(order_id))
    )
    invoice = result.scalar_one_or_none()
    if invoice:
        logger.info(f"  Инвойс найден по invoice_id={order_id}")
        return invoice

    # Стратегия 2: поиск по CryptoBot invoice_id (если payment_crypto перезаписал ID)
    if cryptobot_invoice_id and cryptobot_invoice_id != order_id:
        result = await session.execute(
            select(PaymentInvoice).where(PaymentInvoice.invoice_id == str(cryptobot_invoice_id))
        )
        invoice = result.scalar_one_or_none()
        if invoice:
            logger.info(f"  Инвойс найден по CryptoBot invoice_id={cryptobot_invoice_id}")
            return invoice

    # Стратегия 3: поиск последнего pending-инвойса по payload, содержащему order_id
    result = await session.execute(
        select(PaymentInvoice)
        .where(PaymentInvoice.status == "pending")
        .where(PaymentInvoice.payment_method == "cryptopay")
        .order_by(PaymentInvoice.created_at.desc())
        .limit(10)
    )
    pending_invoices = result.scalars().all()
    for inv in pending_invoices:
        # Проверяем, что payload содержит наш order_id
        if inv.payload and str(order_id) in str(inv.payload):
            logger.info(f"  Инвойс найден по payload-поиску: id={inv.id}, invoice_id={inv.invoice_id}")
            return inv

    # Стратегия 4: поиск по ID как числу (если order_id — числовой)
    try:
        numeric_id = int(order_id)
        result = await session.execute(
            select(PaymentInvoice).where(PaymentInvoice.id == numeric_id)
        )
        invoice = result.scalar_one_or_none()
        if invoice:
            logger.info(f"  Инвойс найден по числовому ID={numeric_id}")
            return invoice
    except (ValueError, TypeError):
        pass

    logger.error(f"  Инвойс НЕ НАЙДЕН: order_id={order_id}, cryptobot_id={cryptobot_invoice_id}")
    return None


async def process_crypto_payment(order_id: str, cryptobot_invoice_id: str, amount: Decimal, bot: Bot) -> bool:
    """
    Единая функция обработки криптовалютного платежа.
    """
    logger.info(f"🔄 Обработка крипто-платежа order_id={order_id}, cryptobot_id={cryptobot_invoice_id}, amount={amount} RUB")

    async with get_session_factory()() as session:
        # Ищем инвойс в нашей БД (надёжный поиск с fallback'ами)
        invoice = await _find_invoice(session, order_id, cryptobot_invoice_id)

        if not invoice:
            logger.error(f"Invoice not found in DB: order_id={order_id}, cryptobot_id={cryptobot_invoice_id}")
            return False

        user_telegram_id = invoice.user_id

        # Находим пользователя
        result = await session.execute(select(User).where(User.user_id == user_telegram_id))
        user = result.scalar_one_or_none()

        if not user:
            logger.error(f"User not found: {user_telegram_id}")
            return False

        # Получаем days, tier, device_count и gb_limit из payload инвойса
        days = 30
        tier = "standard"
        device_count = 1
        gb_limit = 0

        if invoice.payload:
            try:
                payload_data = json.loads(invoice.payload)
                days = payload_data.get("days", 30)
                tier = payload_data.get("tier", "standard")
                device_count = payload_data.get("device_count", 1)
                gb_limit = payload_data.get("gb_limit", 0)
            except Exception as e:
                logger.warning(f"Failed to parse invoice payload: {e}")

        logger.info(f"Crypto Payment: user={user_telegram_id}, days={days}, tier={tier}, devices={device_count}, gb_limit={gb_limit} GB, amount={amount}")

        # Проверяем, есть ли уже оплаченный инвойс
        if invoice.status == "paid":
            logger.info(f"Payment already processed: {invoice.invoice_id}")
            return True

        # Обновляем инвойс
        invoice.status = "paid"
        invoice.device_count = device_count

        # === Проверяем, первая ли это оплата (до добавления транзакции) ===
        prev_paid_tx = await session.execute(
            select(Transaction)
            .where(Transaction.user_id == user_telegram_id)
            .where(Transaction.status == "paid")
            .limit(1)
        )
        is_first_payment = prev_paid_tx.scalar_one_or_none() is None

        # Создаем транзакцию
        transaction = Transaction(
            user_id=user_telegram_id,
            amount=float(amount),
            currency="RUB",
            payment_method="cryptopay",
            status="paid",
            payment_id=str(order_id),
            description=f"Оплата подписки на {days} дней (Crypto) | Устройств: {device_count}"
        )
        session.add(transaction)

        # === ВЫДАЧА ПОДПИСКИ ===
        now = datetime.utcnow()
        is_extension = bool(user.expire_date and user.expire_date > now)

        if is_extension:
            user.expire_date = user.expire_date + timedelta(days=days)
            logger.info(f"Продление подписки с {user.expire_date - timedelta(days=days)} до {user.expire_date}")
        else:
            user.expire_date = now + timedelta(days=days)
            logger.info(f"Новая подписка до {user.expire_date}")

        # Обновляем тариф, количество устройств и лимит трафика
        user.tier = tier
        if device_count > 0:
            user.device_count = device_count
        if gb_limit > 0:
            # Накопительный лимит: прибавляем к текущему
            current_gb = user.gb_limit or 0
            user.gb_limit = current_gb + gb_limit
            logger.info(f"GB лимит: {current_gb} + {gb_limit} = {user.gb_limit} ГБ")

        # === MARZBAN ===
        try:
            if user.marzban_username:
                marzban_user = await marzban_service.get_user(user.marzban_username)
                if marzban_user:
                    # Один запрос — обновляем всё разом (срок + тариф + устройства + трафик)
                    await marzban_service.update_user_full(
                        marzban_username=user.marzban_username,
                        extra_days=days,
                        tier=tier,
                        device_count=device_count,
                        data_limit_gb=gb_limit
                    )
                    logger.info(f"✅ Marzban: {user.marzban_username} обновлён (+{days}д, {tier}, {device_count} устр., {gb_limit} ГБ)")
                else:
                    new_user = await marzban_service.create_user(
                        tg_id=user_telegram_id,
                        username=user.username,
                        expire_days=days,
                        data_limit_gb=gb_limit,
                        tier=tier,
                        device_count=device_count
                    )
                    user.marzban_username = new_user.get("username")
                    logger.info(f"✅ Marzban: создан {user.marzban_username} (Тариф: {tier})")
            else:
                new_user = await marzban_service.create_user(
                    tg_id=user_telegram_id,
                    username=user.username,
                    expire_days=days,
                    data_limit_gb=gb_limit,
                    tier=tier,
                    device_count=device_count
                )
                user.marzban_username = new_user.get("username")
                logger.info(f"✅ Marzban: создан {user.marzban_username} (Тариф: {tier})")
            
        except Exception as e:
            logger.error(f"❌ Marzban error: {e}")

        # === РЕФЕРАЛЬНЫЕ БОНУСЫ (3 уровня) ===
        referrers_bonuses = []
        try:
            percentages = settings.referral_percentages_list
            current_referrer_id = user.referrer_id

            for level, pct in enumerate(percentages, 1):
                if not current_referrer_id:
                    break

                ref_result = await session.execute(
                    select(User).where(User.user_id == current_referrer_id)
                )
                referrer = ref_result.scalar_one_or_none()

                if not referrer:
                    break

                bonus = float(amount) * (pct / 100.0)
                referrer.referral_balance += bonus
                
                # Логика для заданий (только для 1 уровня)
                bonus_days_msg = ""
                if level == 1 and is_first_payment:
                    referrer.refs_paid_count += 1
                    bonus_days = 0
                    
                    if referrer.refs_paid_count == 1:
                        bonus_days = 5
                    elif referrer.refs_paid_count == 5:
                        bonus_days = 14
                    elif referrer.refs_paid_count == 10:
                        bonus_days = 30
                        
                    if bonus_days > 0:
                        ref_now = datetime.utcnow()
                        if referrer.expire_date and referrer.expire_date > ref_now:
                            referrer.expire_date += timedelta(days=bonus_days)
                        else:
                            referrer.expire_date = ref_now + timedelta(days=bonus_days)
                            
                        if referrer.marzban_username:
                            try:
                                await marzban_service.update_user_expiry(
                                    marzban_username=referrer.marzban_username,
                                    extra_days=bonus_days,
                                    tier=referrer.tier
                                )
                            except Exception as e:
                                logger.error(f"Ошибка начисления бонусных дней в Marzban для {referrer.user_id}: {e}")
                                
                        bonus_days_msg = f"\n🎁 <b>Бонус за {referrer.refs_paid_count}-го друга:</b> +{bonus_days} дней VPN!"

                referrers_bonuses.append({
                    'level': level,
                    'id': referrer.user_id,
                    'username': referrer.username,
                    'bonus': bonus
                })

                # Уведомляем рефовода
                try:
                    await bot.send_message(
                        referrer.user_id,
                        f"💸 <b>Реферальное начисление!</b>\n\n"
                        f"Ваш реферал (ID: {user_telegram_id}) пополнил баланс криптовалютой.\n"
                        f"Вам начислено: <b>+{bonus:.2f}₽</b> ({level} уровень, {pct}%){bonus_days_msg}\n\n"
                        f"Реферальный баланс: {referrer.referral_balance:.2f}₽",
                        parse_mode="HTML"
                    )
                except Exception as e:
                    logger.warning(f"Failed to notify referrer {referrer.user_id}: {e}")

                current_referrer_id = referrer.referrer_id
        except Exception as e:
            logger.error(f"Ошибка при начислении реферальных: {e}")

        # Фиксируем изменения
        await session.commit()

        # === УВЕДОМЛЕНИЕ ПОЛЬЗОВАТЕЛЯ (ПРЯМАЯ ВЫДАЧА КЛЮЧЕЙ) ===
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
                f"💰 Сумма: <b>{amount:.2f} RUB</b> (в эквиваленте)\n\n"
            )

            if sub_url:
                msg += (
                    f"🔑 <b>Ваш ключ доступа (Subscription URL):</b>\n"
                    f"<code>{sub_url}</code>\n\n"
                    f"🔗 <b>Прямой VLESS ключ:</b>\n"
                    f"<code>{vless_link}</code>\n\n"
                    f"📖 <b>Инструкция по подключению:</b>\n"
                    f"1. Нажмите на ключ доступа выше, чтобы скопировать его.\n"
                    f"2. Откройте приложение V2Box (iOS), v2rayNG (Android) или Hiddify (ПК).\n"
                    f"3. Добавьте подписку из буфера обмена (через плюсик ➕) и обновите её.\n"
                    f"4. Выберите нужный сервер и нажмите старт!\n\n"
                    f"Приятного пользования! 🎉"
                )
            else:
                msg += "🔗 Ваша подписка активирована!\nПроверьте профиль для подключения."

            await bot.send_message(
                user_telegram_id,
                msg,
                parse_mode="HTML"
            )
            logger.info(f"✅ Пользователь {user_telegram_id} уведомлен об успехе крипто-платежа и получил ключи")
        except Exception as e:
            logger.error(f"Failed to notify user {user_telegram_id}: {e}")

        # === УВЕДОМЛЕНИЕ АДМИНОВ ===
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
                f"📱 Устройств: <b>{user.device_count}"
                f"</b>{referrer_line}"
            )

            for admin_id in settings.admin_ids_list:
                try:
                    await bot.send_message(admin_id, admin_msg, parse_mode="HTML")
                except Exception as e:
                    logger.warning(f"Failed to notify admin {admin_id}: {e}")
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления админу: {e}")

        return True

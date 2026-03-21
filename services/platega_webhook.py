"""
Обработчик webhook'ов Platega для автоматической выдачи подписок.
Работает по аналогии с успешными проектами.
"""
from aiogram import Bot
from loguru import logger
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from decimal import Decimal

from config import settings
from database.models import User, PaymentInvoice, Transaction
from services.marzban_api import marzban_service
from sqlalchemy import select
from database.engine import get_session_factory


async def handle_platega_webhook_update(data: Dict[str, Any], bot: Bot) -> Dict[str, str]:
    """
    Обработать обновление от Platega webhook.
    """
    logger.info("=" * 50)
    logger.info("💰 PLATEGA WEBHOOK получен")
    logger.info("=" * 50)
    logger.info(f"Данные: {data}")

    try:
        # Получаем статус платежа
        status = str(data.get("status") or data.get("Status") or data.get("STATUS", "")).upper()

        # Обрабатываем только успешные платежи
        if status not in ("CONFIRMED", "SUCCESS", "PAID", "COMPLETED"):
            logger.info(f"Ignoring payment status: {status}")
            return {"status": "ok", "message": "Статус не требует обработки"}

        # Получаем данные платежа
        order_id = data.get("payload") or data.get("order_id") or data.get("orderId")
        amount = Decimal(str(data.get("amount") or data.get("Amount") or data.get("total") or 0))
        currency = data.get("currency") or data.get("Currency") or "RUB"

        logger.info(f"Платеж Platega:")
        logger.info(f"  Order ID: {order_id}")
        logger.info(f"  Amount: {amount} {currency}")
        logger.info(f"  Status: {status}")

        if not order_id:
            logger.error("No payload/order_id in webhook data")
            return {"status": "error", "message": "Отсутствует order_id"}

        # Обрабатываем платеж
        result = await process_platega_payment(order_id, amount, currency, bot)

        return {"status": "ok", "message": "Подписка выдана"}

    except Exception as e:
        logger.error(f"❌ Ошибка обработки webhook: {e}")
        import traceback
        logger.error(f"Traceback:\n{traceback.format_exc()}")
        return {"status": "error", "message": str(e)}


async def process_platega_payment(order_id: str, amount: Decimal, currency: str, bot: Bot) -> bool:
    """
    Единая функция обработки платежа Platega.
    По аналогии с успешными проектами.
    """
    logger.info(f"🔄 Обработка платежа order_id={order_id}, amount={amount} {currency}")

    # Парсим order_id: формат "platega_{user_id}_{uuid}"
    # Days берем из payload инвойса в БД
    parts = str(order_id).split("_")
    
    if len(parts) < 3:
        logger.error(f"Invalid order_id format: {order_id}")
        return False

    # Формат: platega_{user_id}_{uuid}
    if parts[0] == "platega":
        user_telegram_id = int(parts[1])
    else:
        logger.error(f"Cannot parse order_id: {order_id}")
        return False

    async with get_session_factory()() as session:
        # Находим пользователя
        result = await session.execute(select(User).where(User.user_id == user_telegram_id))
        user = result.scalar_one_or_none()

        if not user:
            logger.error(f"User not found: {user_telegram_id}")
            return False

        # Находим инвойс для получения days
        existing = await session.execute(
            select(PaymentInvoice).where(PaymentInvoice.invoice_id == str(order_id))
        )
        invoice = existing.scalar_one_or_none()

        # Получаем days из payload инвойса
        days = 30  # По умолчанию
        if invoice and invoice.payload:
            try:
                import json
                payload_data = json.loads(invoice.payload)
                days = payload_data.get("days", 30)
            except:
                pass
        else:
            # Если инвойса нет, пробуем найти по user_id последний pending
            recent = await session.execute(
                select(PaymentInvoice)
                .where(PaymentInvoice.user_id == user_telegram_id)
                .where(PaymentInvoice.status == "pending")
                .order_by(PaymentInvoice.created_at.desc())
                .limit(1)
            )
            recent_invoice = recent.scalar_one_or_none()
            if recent_invoice and recent_invoice.payload:
                try:
                    import json
                    payload_data = json.loads(recent_invoice.payload)
                    days = payload_data.get("days", 30)
                except:
                    pass

        logger.info(f"Payment: user={user_telegram_id}, days={days}, amount={amount}")

        # Проверяем, есть ли уже оплаченный инвойс
        if invoice and invoice.status == "paid":
            logger.info(f"Payment already processed: {order_id}")
            return True

        # Обновляем или создаем инвойс
        if invoice:
            invoice.status = "paid"
        else:
            invoice = PaymentInvoice(
                user_id=user_telegram_id,
                invoice_id=str(order_id),
                amount=float(amount),
                currency="RUB",
                payment_method="platega",
                status="paid",
                payload=f'{{"days": {days}}}',
                created_at=datetime.utcnow()
            )
            session.add(invoice)

        # Создаем транзакцию
        transaction = Transaction(
            user_id=user_telegram_id,
            amount=float(amount),
            currency="RUB",
            payment_method="platega",
            status="paid",
            payment_id=str(order_id),
            description=f"Оплата подписки на {days} дней"
        )
        session.add(transaction)

        # === ВЫДАЧА ПОДПИСКИ ===
        now = datetime.utcnow()
        is_extension = bool(user.expire_date and user.expire_date > now)

        if is_extension:
            user.expire_date = user.expire_date + timedelta(days=days)
            logger.info(f"Продление подписки с {user.expire_date} до {user.expire_date}")
        else:
            user.expire_date = now + timedelta(days=days)
            logger.info(f"Новая подписка до {user.expire_date}")

        # === MARZBAN ===
        try:
            if user.marzban_username:
                # Проверяем существование в Marzban
                marzban_user = await marzban_service.get_user(user.marzban_username)
                if marzban_user:
                    await marzban_service.update_user_expiry(
                        marzban_username=user.marzban_username,
                        extra_days=days
                    )
                    logger.info(f"✅ Marzban: подписка {user.marzban_username} продлена на {days} дней")
                else:
                    # Создаем нового
                    new_user = await marzban_service.create_user(
                        tg_id=user_telegram_id,
                        username=user.username,
                        expire_days=days,
                        data_limit_gb=0.0
                    )
                    user.marzban_username = new_user.get("username")
                    logger.info(f"✅ Marzban: создан пользователь {user.marzban_username}")
            else:
                # Создаем нового
                new_user = await marzban_service.create_user(
                    tg_id=user_telegram_id,
                    username=user.username,
                    expire_days=days,
                    data_limit_gb=0.0
                )
                user.marzban_username = new_user.get("username")
                logger.info(f"✅ Marzban: создан пользователь {user.marzban_username}")
        except Exception as e:
            logger.error(f"❌ Marzban error: {e}")
            # Не прерываем обработку, продолжаем с уведомлениями

        # === РЕФЕРАЛЬНЫЕ БОНУСЫ (3 уровня: 15%, 10%, 5%) ===
        referrers_bonuses = []
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
                    f"Ваш реферал (ID: {user_telegram_id}) пополнил баланс.\n"
                    f"Вам начислено: <b>+{bonus:.2f}₽</b> ({level} уровень, {pct}%)\n\n"
                    f"Реферальный баланс: {referrer.referral_balance}₽",
                    parse_mode="HTML"
                )
                logger.info(f"✅ Рефовод {referrer.user_id} уведомлен (уровень {level}, +{bonus:.2f}₽)")
            except Exception as e:
                logger.warning(f"Failed to notify referrer {referrer.user_id}: {e}")

            current_referrer_id = referrer.referrer_id

        await session.commit()

        # === УВЕДОМЛЕНИЕ ПОЛЬЗОВАТЕЛЯ ===
        try:
            subscription_info = ""
            if user.marzban_username:
                subscription_info = f"\n\n🔗 Ваша подписка активирована!\nПроверьте профиль для подключения."

            await bot.send_message(
                user_telegram_id,
                f"✅ <b>Оплата прошла успешно!</b>\n\n"
                f"💎 Подписка: <b>{days} дней</b>\n"
                f"💰 Сумма: <b>{amount:.2f} {currency}</b> (Platega)\n"
                f"{subscription_info}\n"
                f"Спасибо за покупку! 🎉",
                parse_mode="HTML"
            )
            logger.info(f"✅ Пользователь {user_telegram_id} уведомлен об успехе")
        except Exception as e:
            logger.error(f"Failed to notify user {user_telegram_id}: {e}")

        # === УВЕДОМЛЕНИЕ АДМИНОВ ===
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
            f"📦 Подписка: <b>{days} дней</b>"
            f"{referrer_line}"
        )

        for admin_id in settings.admin_ids_list:
            try:
                await bot.send_message(admin_id, admin_msg, parse_mode="HTML")
            except Exception as e:
                logger.warning(f"Failed to notify admin {admin_id}: {e}")

        logger.info(
            f"✅ Platega payment: User {user_telegram_id} +{days} days | "
            f"Amount: {amount} RUB | "
            f"Ref bonuses: {len(referrers_bonuses)} referrers"
        )

        return True

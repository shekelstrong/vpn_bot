"""
Обработчик webhook'ов Platega для автоматической выдачи подписок.
"""
from aiogram import Bot
from loguru import logger
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from config import settings
from database.models import User, PaymentInvoice, Transaction
from services.marzban_api import marzban_service
from sqlalchemy import select
from database.engine import get_session_factory

async def handle_platega_webhook_update(data: Dict[str, Any], bot: Bot) -> Dict[str, str]:
    """
    Обработать обновление от Platega webhook.
    
    Args:
        data: Данные вебхука от Platega
        bot: Экземпляр Telegram бота
        
    Returns:
        Dict: {"status": "ok"} или {"error": "сообщение"}
    """
    logger.info("=" * 50)
    logger.info("Platega webhook получен")
    logger.info("=" * 50)
    
    try:
        # Получаем статус платежа (улучшенный парсинг, устойчивый к разным регистрам ключей Platega)
        status = str(data.get("status") or data.get("Status") or data.get("STATUS", "")).upper()
        
        # Обрабатываем только успешные платежи
        if status not in ("CONFIRMED", "SUCCESS", "PAID", "COMPLETED"):
            logger.info(f"Ignoring payment status: {status}")
            return {"status": "ok", "message": "Статус не требует обработки"}

        # Получаем ID заказа (улучшенный парсинг ключей)
        order_id = data.get("payload") or data.get("order_id") or data.get("orderId") or data.get("merchant_order_id")
        
        if not order_id:
            logger.error("No payload/order_id in webhook data")
            return {"status": "error", "message": "Отсутствует order_id"}

        # Получаем сумму
        amount = float(str(data.get("amount") or data.get("Amount") or data.get("total") or 0))
        currency = data.get("currency") or data.get("Currency") or "RUB"
        
        logger.info(f"Платеж Platega:")
        logger.info(f"  Order ID: {order_id}")
        logger.info(f"  Amount: {amount} {currency}")
        logger.info(f"  Status: {status}")

        # Парсим order_id: формат "platega_{user_id}_{uuid}"
        parts = str(order_id).split("_")
        if len(parts) < 3:
            logger.error(f"Invalid order_id format: {order_id}")
            return {"status": "error", "message": "Неверный формат order_id"}
            
        user_id = int(parts[1])

        # Получаем пользователя из базы данных
        async with get_session_factory()() as session:
            result = await session.execute(select(User).where(User.user_id == user_id))
            user = result.scalar_one_or_none()
            
            if not user:
                logger.error(f"Пользователь {user_id} не найден в базе данных")
                return {"status": "error", "message": "Пользователь не найден"}

            # Проверяем, оплачен ли этот счет (защита от дублей)
            existing_invoice = await session.execute(
                select(PaymentInvoice).where(PaymentInvoice.invoice_id == str(order_id))
            )
            existing = existing_invoice.scalar_one_or_none()
            
            if existing and existing.status == "paid":
                logger.info(f"Счет {order_id} уже был обработан")
                return {"status": "ok", "message": "Уже обработан"}

            # Получаем данные о платеже из payload инвойса
            days = 30
            if existing:
                try:
                    import json
                    if existing.payload:
                        payload_data = json.loads(existing.payload)
                        days = payload_data.get("days", 30)
                except:
                    pass
            else:
                days = 30

            # Обновляем статус счета на "paid"
            if existing:
                existing.status = "paid"
            else:
                new_invoice = PaymentInvoice(
                    user_id=user_id,
                    invoice_id=str(order_id),
                    amount=amount,
                    currency="RUB",
                    payment_method="platega",
                    status="paid",
                    payload=f'{{"days": {days}}}',
                    created_at=datetime.utcnow()
                )
                session.add(new_invoice)
                
            logger.info(f"Счет {order_id} обновлен на статус 'paid'")

            # ВЫДАЧА ПОДПИСКИ И НАЧИСЛЕНИЕ БОНУСОВ
            await issue_subscription(
                bot=bot,
                user=user,
                days=days,
                session=session,
                payment_id=str(order_id),
                amount_rub=amount
            )

            logger.info("=" * 50)
            logger.info(f"✅ Подписка выдана пользователю {user_id} на {days} дней")
            logger.info("=" * 50)
            
            await session.commit()
            return {"status": "ok", "message": "Подписка выдана"}
            
    except Exception as e:
        logger.error(f"❌ Ошибка обработки webhook: {e}")
        import traceback
        logger.error(f"Traceback:\n{traceback.format_exc()}")
        return {"status": "error", "message": str(e)}


async def issue_subscription(
    bot: Bot,
    user: User,
    days: int,
    session,
    payment_id: str,
    amount_rub: float
):
    """
    Выдать подписку пользователю, начислить бонусы и уведомить всех.
    """
    logger.info(f"Выдача подписки пользователю {user.user_id} на {days} дней")
    
    # Рассчитываем новую дату окончания
    now = datetime.utcnow()
    is_extension = bool(user.expire_date and user.expire_date > now)
    
    if is_extension:
        # Если подписка уже активна - продлеваем
        new_expire_date = user.expire_date + timedelta(days=days)
        logger.info(f"Продление подписки с {user.expire_date} до {new_expire_date}")
    else:
        # Если подписка не активна или истекла - задаем новую
        new_expire_date = now + timedelta(days=days)
        logger.info(f"Новая подписка с {now} до {new_expire_date}")
        
    user.expire_date = new_expire_date

    # Распределяем реферальные бонусы по уровням
    referrers_bonuses = []
    percentages = settings.referral_percentages_list
    current_referrer_id = user.referrer_id
    
    for level, pct in enumerate(percentages, 1):
        if not current_referrer_id:
            break
            
        ref_res = await session.execute(select(User).where(User.user_id == current_referrer_id))
        referrer = ref_res.scalar_one_or_none()
        
        if not referrer:
            break
            
        bonus = float(amount_rub) * (pct / 100.0)
        referrer.referral_balance += bonus
        
        referrers_bonuses.append({
            'level': level,
            'id': referrer.user_id,
            'username': referrer.username,
            'bonus': bonus
        })
        
        from handlers.admin.notifications import notify_referrer_payment
        await notify_referrer_payment(bot, referrer.user_id, user.user_id, bonus, level, user.username)
        
        current_referrer_id = referrer.referrer_id

    # Создаем запись о транзакции
    transaction = Transaction(
        user_id=user.user_id,
        amount=amount_rub,
        currency="RUB",
        payment_method="platega",
        status="paid",
        payment_id=payment_id,
        description=f"Оплата подписки на {days} дней",
    )
    session.add(transaction)

    # Обновляем или создаем пользователя в Marzban
    try:
        if user.marzban_username:
            try:
                marzban_user = await marzban_service.get_user(user.marzban_username)
                if marzban_user:
                    await marzban_service.update_user_expiry(
                        marzban_username=user.marzban_username,
                        extra_days=days
                    )
                    logger.info(f"Подписка пользователя {user.marzban_username} продлена на {days} дней")
                else:
                    logger.info(f"Пользователь {user.marzban_username} не найден в Marzban, создаем нового")
                    new_user = await marzban_service.create_user(
                        tg_id=user.user_id,
                        username=user.username,
                        expire_days=days,
                        data_limit_gb=0.0
                    )
                    user.marzban_username = new_user.get("username")
                    logger.info(f"Создан пользователь Marzban: {user.marzban_username}")
            except Exception as e:
                logger.error(f"Ошибка обновления Marzban: {e}")
                raise
        else:
            try:
                new_user = await marzban_service.create_user(
                    tg_id=user.user_id,
                    username=user.username,
                    expire_days=days,
                    data_limit_gb=0.0
                )
                user.marzban_username = new_user.get("username")
                logger.info(f"Создан новый пользователь Marzban: {user.marzban_username}")
            except Exception as e:
                logger.error(f"Ошибка создания пользователя в Marzban: {e}")
                raise

        # Отправляем уведомление пользователю
        from handlers.admin.notifications import notify_user_purchase
        await notify_user_purchase(
            bot=bot,
            user_id=user.user_id,
            amount_rub=amount_rub,
            duration_days=days,
            is_extension=is_extension,
            marzban_username=user.marzban_username
        )

        # Отправляем уведомление админам
        from handlers.admin.notifications import notify_admin_payment
        await notify_admin_payment(
            bot=bot, 
            user_id=user.user_id, 
            amount_rub=amount_rub, 
            username=user.username, 
            method="Platega", 
            referrers_bonuses=referrers_bonuses
        )

    except Exception as e:
        logger.error(f"Ошибка выдачи подписки/уведомлений: {e}")
        import traceback
        logger.error(f"Traceback:\n{traceback.format_exc()}")
        raise
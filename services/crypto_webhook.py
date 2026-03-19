"""
Обработчик webhook'ов CryptoBot для автоматической выдачи подписок.
"""

from aiogram import Bot
from aiocryptopay import AioCryptoPay
from loguru import logger
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from config import settings
from database.models import User, PaymentInvoice
from services.marzban_api import marzban_service
from services.crypto_bot_v2 import crypto_bot_v2_service
import json


async def handle_crypto_webhook_update(update: Dict[str, Any], bot: Bot) -> Dict[str, str]:
    """
    Обработать обновление от CryptoBot webhook.
    
    Args:
        update: Обновление от CryptoBot
        bot: Экземпляр Telegram бота
        
    Returns:
        Dict: {"status": "ok"} или {"error": "сообщение"}
    """
    logger.info(f"=" * 50)
    logger.info(f"CryptoBot webhook получен")
    logger.info(f"=" * 50)
    
    try:
        # Проверяем тип обновления
        if update.get("update_type") != "invoice_paid":
            logger.info(f"Неподдерживаемый update_type: {update.get('update_type')}")
            return {"status": "ok", "message": "Неподдерживаемый тип"}
        
        # Проверяем подпись
        if not crypto_bot_v2_service.verify_webhook_update(update):
            logger.error("Неверная подпись webhook")
            return {"status": "error", "message": "Неверная подпись"}
        
        invoice = update.get("payload", {})
        
        if not invoice:
            logger.error("Webhook не содержит invoice")
            return {"status": "error", "message": "Invoice отсутствует"}
        
        invoice_id = str(invoice.get("invoice_id", ""))
        asset = invoice.get("asset", "")
        amount = float(invoice.get("amount", 0))
        
        logger.info(f"Информация о счете:")
        logger.info(f"  Invoice ID: {invoice_id}")
        logger.info(f"  Asset: {asset}")
        logger.info(f"  Amount: {amount}")
        logger.info(f"  Status: {invoice.get('status')}")
        
        # Парсим custom_payload
        custom_payload_str = invoice.get("payload", "")
        user_id = None
        days = 30
        
        if custom_payload_str:
            try:
                custom_payload = json.loads(custom_payload_str)
                user_id = custom_payload.get("user_id")
                days = custom_payload.get("days", 30)
                
                logger.info(f"Custom payload:")
                logger.info(f"  User ID: {user_id}")
                logger.info(f"  Days: {days}")
                
            except json.JSONDecodeError as e:
                logger.error(f"Ошибка парсинга custom_payload: {e}")
        
        if not user_id:
            logger.error("Не удалось получить user_id из custom_payload")
            return {"status": "error", "message": "User ID отсутствует"}
        
        # Проверяем, оплачен ли счет
        if invoice.get("status") != "paid":
            logger.info(f"Счет {invoice_id} не оплачен (статус: {invoice.get('status')})")
            return {"status": "ok", "message": "Счет не оплачен"}
        
        logger.info(f"=" * 50)
        logger.info(f"Обработка оплаты: {user_id}")
        logger.info(f"=" * 50)
        
        # Получаем пользователя из базы данных (нужно передать session)
        from database.engine import get_session_factory
        
        async with get_session_factory()() as session:
            from sqlalchemy import select
            
            result = await session.execute(
                select(User).where(User.user_id == user_id)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                logger.error(f"Пользователь {user_id} не найден в базе данных")
                return {"status": "error", "message": "Пользователь не найден"}
            
            # Проверяем, оплачен ли этот счет (защита от дублей)
            existing_invoice = await session.execute(
                select(PaymentInvoice).where(PaymentInvoice.invoice_id == invoice_id)
            )
            existing = existing_invoice.scalar_one_or_none()
            
            if existing and existing.status == "paid":
                logger.info(f"Счет {invoice_id} уже был обработан")
                return {"status": "ok", "message": "Уже обработан"}
            
            # Обновляем статус счета на "paid"
            if existing:
                existing.status = "paid"
            else:
                new_invoice = PaymentInvoice(
                    user_id=user_id,
                    invoice_id=invoice_id,
                    amount=amount,
                    currency="USDT",
                    payment_method="cryptobot",
                    status="paid",
                    payload=f'{{"days": {days}}}',
                    created_at=datetime.utcnow()
                )
                session.add(new_invoice)
            
            logger.info(f"Счет {invoice_id} обновлен на статус 'paid'")
            
            # ВЫДАЧА ПОДПИСКИ
            await issue_subscription(
                bot=bot,
                user=user,
                days=days,
                session=session,
                payment_id=invoice_id
            )
            
            logger.info(f"=" * 50)
            logger.info(f"✅ Подписка выдана пользователю {user_id} на {days} дней")
            logger.info(f"=" * 50)
            
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
    payment_id: str
):
    """
    Выдать подписку пользователю.
    
    Args:
        bot: Экземпляр Telegram бота
        user: Пользователь из базы данных
        days: Срок подписки в днях
        session: Сессия базы данных
        payment_id: ID платежа
    """
    logger.info(f"Выдача подписки пользователю {user.user_id} на {days} дней")
    
    # Рассчитываем новую дату окончания
    now = datetime.utcnow()
    
    if user.expire_date and user.expire_date > now:
        # Если подписка уже активна - продлеваем
        new_expire_date = user.expire_date + timedelta(days=days)
        logger.info(f"Продление подписки с {user.expire_date} до {new_expire_date}")
    else:
        # Если подписка не активна или истекла - задаем новую
        new_expire_date = now + timedelta(days=days)
        logger.info(f"Новая подписка с {now} до {new_expire_date}")
    
    user.expire_date = new_expire_date
    
    # Если триал использован - помечаем
    if user.is_trial_used and not (user.expire_date and user.expire_date > now):
        # Если пользователь продлевает триал до полной подписки
        pass
    
    try:
        if user.marzban_username:
            try:
                marzban_user = await marzban_service.get_user(user.marzban_username)
                
                if marzban_user:
                    await marzban_service.update_user_expiry(
                        username=user.marzban_username,
                        days=days
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
        
        try:
            await bot.send_message(
                user.user_id,
                f"✅ Подписка успешно продлена на {days} дней!"
            )
        except Exception as e:
            logger.warning(f"Не удалось отправить уведомление пользователю: {e}")
    
    except Exception as e:
        logger.error(f"Ошибка выдачи подписки: {e}")
        raise

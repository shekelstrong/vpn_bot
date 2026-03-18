#!/usr/bin/env python3
"""
Вебхук-сервер для обработки платежей от CryptoBot и Platega.
Запускается ОТДЕЛЬНО от основного бота на сервере.

Реализована логика:
1. Выдача подписки пользователю.
2. Распределение бонусов по 3 уровням рефералов (15%, 10%, 5%).
3. Уведомления пользователю, рефоводам и администраторам.
"""

import asyncio
from aiohttp import web
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from datetime import datetime, timedelta
from loguru import logger
import sys
from pathlib import Path
import json

from config import settings
from database.models import User, PaymentInvoice, Transaction
from services.marzban_api import marzban_service
from services.payment_platega import platega_service
from handlers.admin.notifications import (
    notify_admin_payment, 
    notify_referrer_payment, 
    notify_user_purchase
)

# Настройка логгирования
logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> - <level>{message}</level>",
    level="INFO",
)

log_path = Path("logs")
log_path.mkdir(exist_ok=True)

logger.add(
    log_path / "webhooks_{time:YYYY-MM-DD}.log",
    rotation="00:00",
    retention="7 days",
    level="DEBUG",
)

class WebhookHandler:
    """Обработчик вебхуков с логикой распределения прибыли."""

    def __init__(self):
        # Используем URL из конфига (PostgreSQL в докере или SQLite локально)
        self.engine = create_async_engine(settings.DATABASE_URL)
        self.session_factory = async_sessionmaker(
            bind=self.engine, 
            class_=AsyncSession, 
            expire_on_commit=False
        )

    async def handle_crypto_webhook(self, request: web.Request) -> web.Response:
        """Обработка вебхука от CryptoBot."""
        try:
            data = await request.json()
            logger.info(f"CryptoBot webhook: {data}")

            invoice_id = data.get('invoice_id')
            status = data.get('status')

            if not invoice_id or status != 'paid':
                return web.json_response({"status": "ok"})

            # Парсим custom_payload (формат: user_TG_ID_sub_DAYSd)
            custom_payload = data.get('custom_payload', '')
            tg_user_id = None
            days = 30

            if custom_payload:
                try:
                    parts = custom_payload.split('_')
                    if len(parts) >= 4:
                        tg_user_id = int(parts[1])
                        days = int(parts[3].replace('d', ''))
                except:
                    pass

            # Если в payload нет ID, ищем в базе счетов
            if tg_user_id is None:
                async with self.session_factory() as session:
                    result = await session.execute(
                        select(PaymentInvoice).where(PaymentInvoice.invoice_id == str(invoice_id))
                    )
                    invoice = result.scalar_one_or_none()
                    if invoice:
                        tg_user_id = invoice.user_id

            if not tg_user_id:
                return web.json_response({"error": "User not found"}, status=404)

            await self.process_payment(
                tg_user_id=tg_user_id,
                amount=float(data.get('amount', 0)),
                currency=data.get('currency', 'RUB'),
                payment_method='cryptobot',
                payment_id=str(invoice_id),
                days=days
            )

            return web.json_response({"status": "ok"})

        except Exception as e:
            logger.error(f"CryptoBot webhook error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def handle_platega_webhook(self, request: web.Request) -> web.Response:
        """Обработка вебхука от Platega."""
        try:
            data = await request.json()
            signature = request.headers.get('X-Platega-Signature', '')
            logger.info(f"Platega webhook: {data}")

            payment_data = platega_service.parse_webhook(data, signature)

            if not payment_data or payment_data.status != 'success':
                return web.json_response({"status": "ok"})

            tg_user_id = int(payment_data.custom_id) if payment_data.custom_id else None

            if not tg_user_id:
                return web.json_response({"error": "User not found"}, status=404)

            # Получаем количество дней из PaymentInvoice
            days = 30
            async with self.session_factory() as session:
                result = await session.execute(
                    select(PaymentInvoice).where(PaymentInvoice.invoice_id == payment_data.payment_id)
                )
                invoice = result.scalar_one_or_none()
                if invoice and invoice.payload:
                    try:
                        import json
                        payload = json.loads(invoice.payload)
                        days = payload.get("days", 30)
                    except:
                        pass

            await self.process_payment(
                tg_user_id=tg_user_id,
                amount=payment_data.amount,
                currency=payment_data.currency,
                payment_method='platega',
                payment_id=payment_data.payment_id,
                days=days
            )

            return web.json_response({"status": "ok"})

        except Exception as e:
            logger.error(f"Platega webhook error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def process_payment(
        self,
        tg_user_id: int,
        amount: float,
        currency: str,
        payment_method: str,
        payment_id: str,
        days: int = 30
    ):
        """Обработка успешного платежа и распределение реферальных бонусов."""
        from aiogram import Bot
        bot = Bot(token=settings.BOT_TOKEN)
        
        async with self.session_factory() as session:
            try:
                # 1. Получаем пользователя
                result = await session.execute(select(User).where(User.user_id == tg_user_id))
                user = result.scalar_one_or_none()

                if not user:
                    logger.error(f"User {tg_user_id} not found during payment process")
                    return

                # 2. Обновляем статус счета
                await session.execute(
                    update(PaymentInvoice)
                    .where(PaymentInvoice.invoice_id == payment_id)
                    .values(status="paid")
                )

                # 3. Создаем транзакцию
                transaction = Transaction(
                    user_id=tg_user_id,
                    amount=amount,
                    currency=currency,
                    payment_method=payment_method,
                    status="paid",
                    payment_id=payment_id,
                    description=f"Оплата подписки на {days} дней",
                )
                session.add(transaction)

                # 4. Продлеваем подписку в БД
                now = datetime.utcnow()
                if user.expire_date and user.expire_date > now:
                    user.expire_date = user.expire_date + timedelta(days=days)
                else:
                    user.expire_date = now + timedelta(days=days)

                # 5. РЕФЕРАЛЬНАЯ ЛОГИКА (3 уровня)
                referrers_bonuses = []
                percentages = settings.referral_percentages_list # [15, 10, 5]
                current_referrer_id = user.referrer_id
                
                for level, pct in enumerate(percentages, 1):
                    if not current_referrer_id:
                        break # Цепочка прервалась
                    
                    # Получаем рефовода уровня N
                    ref_res = await session.execute(select(User).where(User.user_id == current_referrer_id))
                    referrer = ref_res.scalar_one_or_none()
                    
                    if not referrer:
                        break
                    
                    # Начисляем бонус
                    bonus_amount = amount * (pct / 100)
                    referrer.referral_balance += bonus_amount
                    
                    # Сохраняем инфо для админского отчета
                    referrers_bonuses.append({
                        'level': level,
                        'id': referrer.user_id,
                        'username': referrer.username,
                        'bonus': bonus_amount
                    })
                    
                    # Уведомляем рефовода о бонусе
                    await notify_referrer_payment(
                        bot=bot,
                        referrer_id=referrer.user_id,
                        referral_id=tg_user_id,
                        bonus_amount=bonus_amount,
                        level=level,
                        referral_username=user.username
                    )
                    
                    # Переходим к следующему уровню (рефовод рефовода)
                    current_referrer_id = referrer.referrer_id

                # 6. Обновляем Marzban
                marzban_account_exists = False
                if user.marzban_username:
                    try:
                        marzban_data = await marzban_service.get_user(user.marzban_username)
                        if marzban_data:
                            marzban_account_exists = True
                    except: pass

                if marzban_account_exists:
                    await marzban_service.update_user_expiry(user.marzban_username, days)
                else:
                    # Создаем новый аккаунт если его нет (или был удален триал)
                    new_acc = await marzban_service.create_user(
                        tg_id=tg_user_id,
                        username=user.username,
                        expire_days=days,
                        data_limit_gb=0.0 # Безлимит для платных
                    )
                    user.marzban_username = new_acc.get('username')

                await session.commit()
                logger.info(f"Payment processed and bonuses distributed for user {tg_user_id}")

                # 7. Финальные уведомления (Юзеру и Админу)
                await notify_user_purchase(
                    bot=bot,
                    user_id=tg_user_id,
                    amount_rub=amount,
                    duration_days=days
                )

                await notify_admin_payment(
                    bot=bot,
                    user_id=tg_user_id,
                    amount_rub=amount,
                    username=user.username,
                    method=payment_method,
                    referrers_bonuses=referrers_bonuses if referrers_bonuses else None
                )

                # 8. Скрываем команду /trial у пользователя с активной подпиской
                from aiogram.types import BotCommand, BotCommandScopeChat
                base_commands = [
                    BotCommand(command="start", description="Главное меню"),
                    BotCommand(command="me", description="Мой профиль"),
                    BotCommand(command="buy", description="Купить подписку"),
                    BotCommand(command="sub", description="Подписка"),
                    BotCommand(command="referral", description="Реферальная программа"),
                    BotCommand(command="help", description="Помощь"),
                ]
                await bot.set_my_commands(
                    base_commands,
                    scope=BotCommandScopeChat(chat_id=tg_user_id)
                )
                logger.info(f"Команда /trial скрыта для пользователя {tg_user_id}")

            except Exception as e:
                logger.error(f"Error in process_payment: {e}")
                await session.rollback()
            finally:
                await bot.session.close()

    async def health_check(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

async def run_webhooks():
    handler = WebhookHandler()
    app = web.Application()
    app.router.add_post('/webhook/crypto', handler.handle_crypto_webhook)
    app.router.add_post('/webhook/platega', handler.handle_platega_webhook)
    app.router.add_get('/health', handler.health_check)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()

    logger.info("=" * 50)
    logger.info("Вебхук-сервер Nemo VPN запущен (Порт 8080)!")
    logger.info("=" * 50)

    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        await runner.cleanup()

if __name__ == '__main__':
    try:
        asyncio.run(run_webhooks())
    except KeyboardInterrupt:
        logger.info("Вебхук-сервер остановлен")
    except Exception as e:
        logger.critical(f"Critical error: {e}")
        raise
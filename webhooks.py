#!/usr/bin/env python3
"""
Вебхук-сервер для обработки платежей от CryptoBot и Platega.
Запускается ОТДЕЛЬНО от основного бота на сервере.

Запуск: python webhooks.py
"""

import asyncio
from aiohttp import web
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from datetime import datetime, timedelta
from loguru import logger
import sys
from pathlib import Path
import json

from config import settings
from database.models import User, PaymentInvoice, Transaction
from services.marzban_api import marzban_service
from services.payment_platega import platega_service

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
    """Обработчик вебхуков."""

    def __init__(self):
        self.engine = create_async_engine(settings.DATABASE_URL)

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

            if tg_user_id is None:
                async with self.engine.begin() as conn:
                    result = await conn.execute(
                        select(PaymentInvoice).where(PaymentInvoice.invoice_id == str(invoice_id))
                    )
                    invoice = result.scalar_one_or_none()
                    if invoice:
                        tg_user_id = invoice.user_id

            if not tg_user_id:
                return web.json_response({"error": "User not found"}, status=404)

            # Обрабатываем платеж
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

            # Проверяем подпись
            payment_data = platega_service.parse_webhook(data, signature)

            if not payment_data or payment_data.status != 'success':
                return web.json_response({"status": "ok"})

            tg_user_id = int(payment_data.custom_id) if payment_data.custom_id else None

            if not tg_user_id:
                return web.json_response({"error": "User not found"}, status=404)

            # Обрабатываем платеж
            await self.process_payment(
                tg_user_id=tg_user_id,
                amount=payment_data.amount,
                currency=payment_data.currency,
                payment_method='platega',
                payment_id=payment_data.payment_id,
                days=30  # По умолчанию
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
        """Обработка успешного платежа."""
        async with self.engine.begin() as conn:
            # Обновляем счет
            await conn.execute(
                update(PaymentInvoice)
                .where(PaymentInvoice.invoice_id == payment_id)
                .values(status="paid")
            )

            # Получаем пользователя
            result = await conn.execute(select(User).where(User.user_id == tg_user_id))
            user = result.scalar_one_or_none()

            if not user:
                logger.error(f"User {tg_user_id} not found")
                return

            # Создаем транзакцию
            transaction = Transaction(
                user_id=tg_user_id,
                amount=amount,
                currency=currency,
                payment_method=payment_method,
                status="paid",
                payment_id=payment_id,
                description=f"Оплата подписки на {days} дней",
            )
            conn.add(transaction)

            # Продлеваем подписку в БД
            now = datetime.utcnow()
            if user.expire_date and user.expire_date > now:
                user.expire_date = user.expire_date + timedelta(days=days)
            else:
                user.expire_date = now + timedelta(days=days)

            # ИСПРАВЛЕНИЕ: Обновляем в Marzban с учетом удаленных аккаунтов и новых пользователей
            marzban_account_exists = False
            
            if user.marzban_username:
                # Проверяем, существует ли аккаунт физически на сервере
                try:
                    marzban_data = await marzban_service.get_user(user.marzban_username)
                    if marzban_data:
                        marzban_account_exists = True
                except Exception as e:
                    logger.error(f"Ошибка проверки существования аккаунта: {e}")

            if marzban_account_exists:
                # Аккаунт есть, просто продлеваем
                try:
                    await marzban_service.update_user_expiry(user.marzban_username, days)
                except Exception as e:
                    logger.error(f"Marzban update error: {e}")
            else:
                # Аккаунта нет (или удален просроченный триал, или юзер купил сразу без триала)
                try:
                    # Создаем новый безлимитный (0.0 GB) аккаунт на купленное количество дней
                    new_marzban_data = await marzban_service.create_user(
                        tg_id=tg_user_id,
                        username=user.username,
                        expire_days=days,
                        data_limit_gb=0.0
                    )
                    # Сохраняем новый username в базу
                    user.marzban_username = new_marzban_data.get('username')
                    logger.info(f"Создан новый Marzban аккаунт {user.marzban_username} для пользователя {tg_user_id}")
                except Exception as e:
                    logger.error(f"Marzban create error for new payment: {e}")

            await conn.commit()
            logger.info(f"Payment processed for user {tg_user_id}")

            # Уведомляем пользователя
            try:
                from aiogram import Bot
                bot = Bot(token=settings.BOT_TOKEN)
                await bot.send_message(
                    chat_id=tg_user_id,
                    text=f"✅ <b>Оплата подтверждена!</b>\n\nПодписка продлена на {days} дней. Если у вас сменилась ссылка, вы можете найти новую в разделе «Мой профиль»."
                )
                await bot.session.close()
            except Exception as e:
                logger.error(f"Notification error: {e}")

    async def health_check(self, request: web.Request) -> web.Response:
        """Проверка работоспособности."""
        return web.json_response({"status": "ok"})

async def run_webhooks():
    """Запуск вебхук-сервера."""
    handler = WebhookHandler()

    app = web.Application()
    app.router.add_post('/webhook/crypto', handler.handle_crypto_webhook)
    app.router.add_post('/webhook/platega', handler.handle_platega_webhook)
    app.router.add_get('/health', handler.health_check)

    runner = web.AppRunner(app)
    await runner.setup()

    host = '0.0.0.0'
    port = 8080

    site = web.TCPSite(runner, host, port)
    await site.start()

    logger.info("=" * 50)
    logger.info("Вебхук-сервер запущен!")
    logger.info("=" * 50)
    logger.info(f"URL: http://{host}:{port}")
    logger.info(f"  - CryptoBot: /webhook/crypto")
    logger.info(f"  - Platega:   /webhook/platega")
    logger.info(f"  - Health:    /health")
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
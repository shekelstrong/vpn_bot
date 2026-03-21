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
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta
from loguru import logger
import sys
from pathlib import Path
import json
from typing import Optional

from config import settings
from database.models import User, PaymentInvoice, Transaction
from database.engine import get_session_factory, init_db
from services.marzban_api import marzban_service
from services.payment_platega import platega_service
from services.payment_crypto import check_webhook_signature
from handlers.admin.notifications import (
    notify_admin_payment,
    notify_referrer_payment
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

def validate_webhook_signature(body_text: str, signature: str, token: Optional[str] = None) -> bool:
    """Проверить HMAC-SHA256 подпись webhook CryptoBot."""
    if token is None:
        token = settings.CRYPTO_BOT_TOKEN

    if not token or not signature:
        logger.warning("Токен или подпись отсутствуют")
        return False

    try:
        import hmac
        import hashlib

        token_str = token if token is not None else ""
        secret = hashlib.sha256(token_str.encode()).digest()
        hmac_obj = hmac.new(secret, body_text.encode(), hashlib.sha256)
        calculated_signature = hmac_obj.hexdigest()

        is_valid = calculated_signature == signature

        if not is_valid:
            logger.warning("Неверная подпись webhook CryptoBot")

        return is_valid
    except Exception as e:
        logger.error(f"Ошибка проверки подписи: {e}")
        return False

class WebhookHandler:
    """Обработчик вебхуков с логикой распределения прибыли."""

    def __init__(self):
        self.session_factory = get_session_factory()

    async def handle_pay_success(self, request: web.Request) -> web.Response:
        """Обработчик возврата пользователя после успешной оплаты."""
        raise web.HTTPSeeOther("https://t.me/nemo_vpn_bot")

    async def handle_pay_failed(self, request: web.Request) -> web.Response:
        """Обработчик возврата пользователя после неудачной оплаты."""
        raise web.HTTPSeeOther("https://t.me/nemo_vpn_bot")

    async def handle_crypto_webhook(self, request: web.Request) -> web.Response:
        """Обработка вебхука от CryptoBot."""
        logger.info("=" * 50)
        logger.info("🪙 CryptoBot webhook получен!")
        logger.info(f"URL: {request.url}")
        logger.info(f"Method: {request.method}")
        
        try:
            body_bytes = await request.read()
            body_text = body_bytes.decode('utf-8')
            signature = request.headers.get('crypto-pay-api-signature')

            if settings.CRYPTO_BOT_TOKEN and signature:
                if not check_webhook_signature(body_text, signature, settings.CRYPTO_BOT_TOKEN):
                    logger.warning("Неверная подпись вебхука CryptoBot")
                    return web.json_response({"error": "Invalid signature"}, status=403)

            data = await request.json()
            
            if data.get("update_type") != "invoice_paid":
                return web.json_response({"status": "ok", "msg": "ignored type"})

            invoice = data.get("payload", {})
            order_id_str = invoice.get("payload")
            invoice_id = invoice.get("invoice_id")

            if not order_id_str:
                logger.error("Нет order_id в payload")
                return web.json_response({"status": "ok"})

            try:
                order_id = int(order_id_str)
            except ValueError:
                return web.json_response({"status": "ok"})

            async with self.session_factory() as session:
                result = await session.execute(
                    select(PaymentInvoice).where(PaymentInvoice.id == order_id)
                )
                payment_invoice = result.scalar_one_or_none()

                if not payment_invoice:
                    return web.json_response({"status": "ok"})

                if payment_invoice.status == "paid":
                    return web.json_response({"status": "ok"})

                payment_invoice.status = "paid"
                payment_invoice.invoice_id = str(invoice_id)
                await session.commit()
                await session.refresh(payment_invoice)

                tg_user_id = payment_invoice.user_id
                days = 30

                if payment_invoice.payload:
                    try:
                        payload = json.loads(payment_invoice.payload)
                        days = payload.get("days", 30)
                    except:
                        pass

                await self.process_payment(
                    tg_user_id=tg_user_id,
                    amount=payment_invoice.amount,
                    currency=payment_invoice.currency,
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
            try:
                data = await request.json()
            except json.JSONDecodeError:
                form_data = await request.post()
                data = dict(form_data)
                logger.info(f"💰 PLATEGA WEBHOOK (form-data): {data}")

            logger.info(f"💰 PLATEGA WEBHOOK: {data}")

            status = str(data.get("status") or data.get("Status") or data.get("STATUS", "")).upper()

            if status not in ("CONFIRMED", "SUCCESS", "PAID", "COMPLETED"):
                logger.info(f"Ignoring payment status: {status}")
                return web.json_response({"status": "ignored"})

            order_id = data.get("payload") or data.get("order_id") or data.get("orderId") or data.get("merchant_order_id")

            if not order_id:
                logger.error("No payload/order_id in webhook data")
                return web.json_response({"status": "error", "msg": "no payload"}, status=400)

            # Передаем обработку в правильный сервис, чтобы не дублировать код
            from services.platega_webhook import handle_platega_webhook_update
            from aiogram import Bot
            
            bot = Bot(token=settings.BOT_TOKEN)
            result = await handle_platega_webhook_update(data, bot)
            await bot.session.close()

            return web.json_response(result)

        except json.JSONDecodeError:
            logger.error("Invalid JSON in webhook")
            return web.json_response({"status": "error", "msg": "invalid json"}, status=400)
        except Exception as e:
            logger.exception(f"Webhook error: {e}")
            return web.json_response({"status": "error", "msg": str(e)}, status=500)

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
                        break

                    ref_res = await session.execute(select(User).where(User.user_id == current_referrer_id))
                    referrer = ref_res.scalar_one_or_none()

                    if not referrer:
                        break

                    bonus_amount = amount * (pct / 100)
                    referrer.referral_balance += bonus_amount
                    referrers_bonuses.append({
                        'level': level,
                        'id': referrer.user_id,
                        'username': referrer.username,
                        'bonus': bonus_amount
                    })

                    await notify_referrer_payment(
                        bot=bot,
                        referrer_id=referrer.user_id,
                        referral_id=tg_user_id,
                        bonus_amount=bonus_amount,
                        level=level,
                        referral_username=user.username
                    )

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
                    new_acc = await marzban_service.create_user(
                        tg_id=tg_user_id,
                        username=user.username,
                        expire_days=days,
                        data_limit_gb=0.0
                    )
                    user.marzban_username = new_acc.get('username')

                await session.commit()
                logger.info(f"Payment processed and bonuses distributed for user {tg_user_id}")

                # 7. Финальные уведомления (Юзеру и Админу)
                try:
                    subscription_info = ""
                    if user.marzban_username:
                        subscription_info = f"\n\n🔗 Ваша подписка активирована!\nПроверьте профиль для подключения."

                    await bot.send_message(
                        tg_user_id,
                        f"✅ <b>Оплата прошла успешно!</b>\n\n"
                        f"💎 Подписка: <b>{days} дней</b>\n"
                        f"💰 Сумма: <b>{amount:.2f} {currency}</b>\n"
                        f"{subscription_info}\n"
                        f"Спасибо за покупку! 🎉",
                        parse_mode="HTML"
                    )
                    logger.info(f"Уведомление об успешной покупке доставлено пользователю {tg_user_id}")
                except Exception as e:
                    logger.warning(f"Не удалось отправить сообщение об успехе пользователю {tg_user_id}: {e}")

                await notify_admin_payment(
                    bot=bot,
                    user_id=tg_user_id,
                    amount_rub=amount,
                    username=user.username,
                    method=payment_method,
                    referrers_bonuses=referrers_bonuses if referrers_bonuses else None
                )

            except Exception as e:
                logger.error(f"Error in process_payment: {e}")
                await session.rollback()
            finally:
                await bot.session.close()

    async def health_check(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

async def run_webhooks():
    await init_db()

    handler = WebhookHandler()
    app = web.Application()
    
    # Роуты вебхуков
    app.router.add_post('/cryptopay', handler.handle_crypto_webhook)
    app.router.add_post('/platega-webhook', handler.handle_platega_webhook)
    app.router.add_post('/webhook/platega', handler.handle_platega_webhook)
    
    # Роуты возврата пользователя (чтобы не было 521/404)
    app.router.add_get('/pay_success', handler.handle_pay_success)
    app.router.add_get('/pay_failed', handler.handle_pay_failed)
    
    app.router.add_get('/health', handler.health_check)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()

    logger.info("=" * 50)
    logger.info("Вебхук-сервер Nemo VPN запущен (Порт 8080) (SQLite/PG)!")
    logger.info("Webhooks:")
    logger.info("  - https://dealflow.bond/cryptopay (CryptoBot)")
    logger.info("  - https://dealflow.bond/webhook/platega (Platega)")
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
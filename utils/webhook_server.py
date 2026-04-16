"""
Сервер вебхуков для Nemo VPN.
Обрабатывает платежи Platega, CryptoPay и предоставляет REST API для Telegram Mini App.
"""

from aiohttp import web
import json
from loguru import logger
from datetime import datetime, timedelta
from typing import Callable, Awaitable

from sqlalchemy import select
from database.engine import get_session_factory, init_db
from database.models import User, PaymentInvoice
from config import settings

# Импорты сервисов
from services.crypto_webhook import handle_crypto_webhook_update
from services.platega_webhook import handle_platega_webhook_update
from services.marzban_api import marzban_service
from services.payment_crypto import crypto_bot_service


@web.middleware
async def cors_middleware(request: web.Request, handler: Callable[[web.Request], Awaitable[web.StreamResponse]]) -> web.StreamResponse:
    """
    Middleware для обработки CORS (Cross-Origin Resource Sharing).
    Необходимо, чтобы Mini App на Vercel мог делать запросы к нашему серверу.
    """
    is_options = request.method == 'OPTIONS'
    
    if is_options:
        response = web.Response()
    else:
        try:
            response = await handler(request)
        except web.HTTPException as ex:
            response = ex
        except Exception as e:
            logger.error(f"CORS Middleware Error: {e}")
            response = web.json_response({"error": "server_error"}, status=500)
            
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With'
    
    return response


class WebhookHandler:
    """Обработчик HTTP-запросов для вебхуков и API."""

    def __init__(self, bot):
        self.bot = bot

    # ==========================================
    # СТАРЫЕ РОУТЫ ВЕБХУКОВ (ЛОГИКА СОХРАНЕНА)
    # ==========================================
    
    async def handle_crypto_webhook(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            result = await handle_crypto_webhook_update(data, self.bot)
            return web.json_response(result)
        except Exception as e:
            logger.error(f"Crypto Webhook Error: {e}")
            return web.json_response({"status": "error"}, status=400)

    async def handle_platega_webhook(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            result = await handle_platega_webhook_update(data, self.bot)
            return web.json_response(result)
        except Exception as e:
            logger.error(f"Platega Webhook Error: {e}")
            return web.json_response({"status": "error"}, status=400)

    async def handle_pay_success(self, request: web.Request) -> web.Response:
        return web.Response(text="Оплата успешно завершена! Вы можете вернуться в бота.", content_type='text/html')

    async def handle_pay_failed(self, request: web.Request) -> web.Response:
        return web.Response(text="Произошла ошибка при оплате или вы отменили транзакцию.", content_type='text/html')

    async def health_check(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "message": "Nemo VPN Webhook & API Server is running."})

    # ==========================================
    # НОВЫЕ РОУТЫ ДЛЯ MINI APP (API)
    # ==========================================

    async def api_get_user(self, request: web.Request) -> web.Response:
        """Получить расширенные данные пользователя для отображения в профиле Mini App."""
        try:
            tg_id_str = request.query.get("tg_id")
            if not tg_id_str:
                return web.json_response({"error": "tg_id is required"}, status=400)
                
            tg_id = int(tg_id_str)
            
            async with get_session_factory()() as session:
                result = await session.execute(select(User).where(User.user_id == tg_id))
                user = result.scalar_one_or_none()
                
                if not user:
                    return web.json_response({"error": "user not found"}, status=404)
                
                # Данные о трафике из Marzban
                used_traffic_gb = 0.0
                if user.marzban_username:
                    try:
                        mz_data = await marzban_service.get_user(user.marzban_username)
                        if mz_data:
                            # Переводим байты в ГБ
                            used_traffic_gb = round(mz_data.get('used_traffic', 0) / (1024**3), 2)
                    except Exception as e:
                        logger.warning(f"Could not fetch traffic for {user.marzban_username}: {e}")

                # Считаем оставшиеся дни
                days_left = 0
                if user.expire_date and user.expire_date > datetime.utcnow():
                    delta = user.expire_date - datetime.utcnow()
                    days_left = delta.days

                # Формируем реферальную ссылку бота
                bot_info = await self.bot.get_me()
                ref_link = f"https://t.me/{bot_info.username}?start={user.user_id}"

                return web.json_response({
                    "status": "success",
                    "user": {
                        "user_id": user.user_id,
                        "username": user.username or "Пользователь",
                        "tier": user.tier,
                        "days_left": days_left,
                        "device_count": user.device_count,
                        "gb_limit": user.gb_limit or 0,
                        "used_traffic": used_traffic_gb,
                        "task_channel_sub": user.task_channel_sub,
                        "refs_paid_count": user.refs_paid_count,
                        "ref_link": ref_link,
                        "balance": user.balance,
                        "referral_balance": user.referral_balance
                    }
                })
        except Exception as e:
            logger.error(f"API Get User Error: {e}")
            return web.json_response({"error": "Internal server error"}, status=500)

    async def api_check_task(self, request: web.Request) -> web.Response:
        """Проверка подписки на ТГ-канал NEMO VPN для выдачи +3 дней."""
        try:
            data = await request.json()
            tg_id = int(data.get("tg_id"))
            channel_id = "@nemo_vpn_official" 
            
            async with get_session_factory()() as session:
                result = await session.execute(select(User).where(User.user_id == tg_id))
                user = result.scalar_one_or_none()
                
                if not user:
                    return web.json_response({"error": "user not found"}, status=404)
                    
                if user.task_channel_sub:
                    return web.json_response({"status": "already_done"})

                # Проверяем подписку через бота
                try:
                    chat_member = await self.bot.get_chat_member(chat_id=channel_id, user_id=tg_id)
                    is_member = chat_member.status in ["member", "administrator", "creator"]
                except Exception as e:
                    logger.error(f"Ошибка проверки подписки {tg_id} на {channel_id}: {e}")
                    is_member = False

                if is_member:
                    bonus_days = 3
                    now = datetime.utcnow()
                    if user.expire_date and user.expire_date > now:
                        user.expire_date += timedelta(days=bonus_days)
                    else:
                        user.expire_date = now + timedelta(days=bonus_days)
                        
                    user.task_channel_sub = True
                    
                    if user.marzban_username:
                        try:
                            await marzban_service.update_user_expiry(
                                marzban_username=user.marzban_username,
                                extra_days=bonus_days,
                                tier=user.tier
                            )
                        except: pass

                    await session.commit()
                    
                    try:
                        await self.bot.send_message(
                            tg_id,
                            "🎉 <b>Бонус начислен!</b>\n\nВы получили +3 дня за подписку на канал.",
                            parse_mode="HTML"
                        )
                    except: pass
                        
                    return web.json_response({"status": "success"})
                else:
                    return web.json_response({"status": "not_subscribed"})

        except Exception as e:
            logger.error(f"API Check Task Error: {e}")
            return web.json_response({"error": "Internal server error"}, status=500)

    async def api_create_invoice(self, request: web.Request) -> web.Response:
        """
        Создание реальной ссылки на оплату через CryptoBot или Platega.
        """
        try:
            data = await request.json()
            tg_id = int(data.get("tg_id"))
            days = int(data.get("days", 30))
            amount = float(data.get("amount", 300))
            payment_method = data.get("payment_method", "cryptopay")
            device_count = int(data.get("device_count", 1))
            
            import uuid
            order_id = f"app_{payment_method}_{uuid.uuid4().hex[:6]}"
            pay_url = None

            # Логика получения реальной ссылки от мерчанта
            if payment_method == "cryptopay":
                price_usdt = round(amount / settings.USDT_TO_RUB_RATE, 2)
                res = await crypto_bot_service.create_invoice(
                    amount_usdt=price_usdt,
                    order_id=order_id,
                    description=f"VIP VPN: {days} дн. ({device_count} устр.)"
                )
                if res: pay_url = res[0]
            
            elif payment_method == "platega":
                from services.payment_platega import create_invoice as create_sbp_link
                pay_url = await create_sbp_link(
                    amount_rub=int(amount),
                    order_id=order_id,
                    user_id=tg_id,
                    description=f"VIP VPN: {days} дн. ({device_count} устр.)"
                )

            if not pay_url:
                return web.json_response({"error": "Could not generate payment link"}, status=500)

            # Сохраняем инвойс в БД
            async with get_session_factory()() as session:
                invoice = PaymentInvoice(
                    user_id=tg_id,
                    invoice_id=order_id,
                    amount=amount,
                    currency="RUB",
                    payment_method=payment_method,
                    status="pending",
                    payload=json.dumps({
                        "days": days, 
                        "tier": "premium", 
                        "device_count": device_count
                    }),
                    created_at=datetime.utcnow()
                )
                session.add(invoice)
                await session.commit()

            return web.json_response({
                "status": "success", 
                "pay_url": pay_url
            })
            
        except Exception as e:
            logger.error(f"API Create Invoice Error: {e}")
            return web.json_response({"error": str(e)}, status=500)


async def run_webhooks(bot=None):
    """Функция запуска веб-сервера."""
    await init_db()
    handler = WebhookHandler(bot=bot)
    
    app = web.Application(middlewares=[cors_middleware])
    
    app.router.add_post('/cryptopay', handler.handle_crypto_webhook)
    app.router.add_post('/platega-webhook', handler.handle_platega_webhook)
    app.router.add_post('/webhook/platega', handler.handle_platega_webhook)
    
    app.router.add_get('/pay_success', handler.handle_pay_success)
    app.router.add_get('/pay_failed', handler.handle_pay_failed)
    
    app.router.add_get('/health', handler.health_check)

    app.router.add_get('/api/user', handler.api_get_user)
    app.router.add_post('/api/check_task', handler.api_check_task)
    app.router.add_post('/api/invoice', handler.api_create_invoice)

    runner = web.AppRunner(app)
    await runner.setup()
    
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    
    logger.info("🚀 Nemo VPN API & Webhooks started on port 8080")
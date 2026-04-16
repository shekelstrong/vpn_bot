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

# Импорты обработчиков (предполагается, что они используют функцию обновления)
from services.crypto_webhook import handle_crypto_webhook_update
from services.platega_webhook import handle_platega_webhook_update
from services.marzban_api import marzban_service


@web.middleware
async def cors_middleware(request: web.Request, handler: Callable[[web.Request], Awaitable[web.StreamResponse]]) -> web.StreamResponse:
    """
    Middleware для обработки CORS (Cross-Origin Resource Sharing).
    Необходимо, чтобы Mini App на Vercel/Netlify мог делать запросы к нашему серверу.
    """
    is_options = request.method == 'OPTIONS'
    
    if is_options:
        response = web.Response()
    else:
        try:
            response = await handler(request)
        except web.HTTPException as ex:
            response = ex
            
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    
    return response


class WebhookHandler:
    """Обработчик HTTP-запросов для вебхуков и API."""

    def __init__(self, bot):
        self.bot = bot

    # ==========================================
    # СТАРЫЕ РОУТЫ ВЕБХУКОВ (НЕ ТРОГАЕМ ЛОГИКУ)
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
        """Получить данные пользователя для отображения в Mini App."""
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
                
                # Считаем оставшиеся дни
                days_left = 0
                if user.expire_date and user.expire_date > datetime.utcnow():
                    delta = user.expire_date - datetime.utcnow()
                    days_left = delta.days

                return web.json_response({
                    "user_id": user.user_id,
                    "tier": user.tier,
                    "days_left": days_left,
                    "device_count": user.device_count,
                    "gb_limit": user.gb_limit, # None значит безлимит (для старых)
                    "task_channel_sub": user.task_channel_sub,
                    "refs_paid_count": user.refs_paid_count,
                    "balance": user.balance,
                    "referral_balance": user.referral_balance
                })
        except Exception as e:
            logger.error(f"API Get User Error: {e}")
            return web.json_response({"error": "Internal server error"}, status=500)

    async def api_check_task(self, request: web.Request) -> web.Response:
        """Проверка подписки на ТГ-канал NEMO VPN для выдачи +3 дней."""
        try:
            data = await request.json()
            tg_id = int(data.get("tg_id"))
            
            # ID или username канала из ТЗ
            channel_id = "@nemo_vpn_official" 
            
            async with get_session_factory()() as session:
                result = await session.execute(select(User).where(User.user_id == tg_id))
                user = result.scalar_one_or_none()
                
                if not user:
                    return web.json_response({"error": "user not found"}, status=404)
                    
                if user.task_channel_sub:
                    return web.json_response({"status": "already_done", "message": "Задание уже выполнено"})

                # Проверяем подписку через бота
                try:
                    chat_member = await self.bot.get_chat_member(chat_id=channel_id, user_id=tg_id)
                    is_member = chat_member.status in ["member", "administrator", "creator"]
                except Exception as e:
                    logger.error(f"Ошибка проверки подписки {tg_id} на {channel_id}: {e}")
                    is_member = False

                if is_member:
                    # Даем бонус +3 дня
                    bonus_days = 3
                    now = datetime.utcnow()
                    if user.expire_date and user.expire_date > now:
                        user.expire_date += timedelta(days=bonus_days)
                    else:
                        user.expire_date = now + timedelta(days=bonus_days)
                        
                    user.task_channel_sub = True
                    
                    # Продлеваем в Marzban
                    if user.marzban_username:
                        try:
                            await marzban_service.update_user_expiry(
                                marzban_username=user.marzban_username,
                                extra_days=bonus_days,
                                tier=user.tier
                            )
                        except Exception as e:
                            logger.error(f"Ошибка начисления +3 дней в Marzban: {e}")

                    await session.commit()
                    
                    # Отправляем уведомление
                    try:
                        await self.bot.send_message(
                            tg_id,
                            "🎉 <b>Спасибо за подписку!</b>\n\nВам начислено <b>+3 бонусных дня</b> использования VPN.",
                            parse_mode="HTML"
                        )
                    except:
                        pass
                        
                    return web.json_response({"status": "success", "bonus_days": bonus_days})
                else:
                    return web.json_response({"status": "not_subscribed", "message": "Вы еще не подписаны на канал"})

        except Exception as e:
            logger.error(f"API Check Task Error: {e}")
            return web.json_response({"error": "Internal server error"}, status=500)

    async def api_create_invoice(self, request: web.Request) -> web.Response:
        """
        Создание инвойса (предварительного счета) из Mini App.
        Фронтенд передает: tg_id, days, tier, device_count, amount, payment_method
        """
        try:
            data = await request.json()
            tg_id = int(data.get("tg_id"))
            days = int(data.get("days", 30))
            tier = data.get("tier", "premium") # premium - обход белых списков
            device_count = int(data.get("device_count", 1))
            amount = float(data.get("amount", 300))
            payment_method = data.get("payment_method", "cryptopay") # cryptopay или platega
            
            # Здесь можно реализовать логику вызова API CryptoPay/Platega для получения ссылки,
            # но пока мы просто создаем инвойс в нашей БД.
            # Для генерации уникального ID:
            import uuid
            invoice_uid = f"{payment_method}_{tg_id}_{uuid.uuid4().hex[:8]}"

            async with get_session_factory()() as session:
                invoice = PaymentInvoice(
                    user_id=tg_id,
                    invoice_id=invoice_uid,
                    amount=amount,
                    currency="RUB",
                    payment_method=payment_method,
                    status="pending",
                    # В payload сохраняем все настройки, чтобы при оплате выдать правильные лимиты
                    payload=json.dumps({
                        "days": days, 
                        "tier": tier, 
                        "device_count": device_count
                    }),
                    created_at=datetime.utcnow()
                )
                session.add(invoice)
                await session.commit()

            return web.json_response({
                "status": "success", 
                "invoice_id": invoice_uid,
                "amount": amount,
                "message": "Счет создан. Теперь бот должен сгенерировать ссылку."
            })
            
        except Exception as e:
            logger.error(f"API Create Invoice Error: {e}")
            return web.json_response({"error": str(e)}, status=500)


async def run_webhooks(bot=None):
    """Функция запуска веб-сервера."""
    await init_db()
    
    handler = WebhookHandler(bot=bot)
    
    # Добавляем middleware для CORS (чтобы Mini App работал)
    app = web.Application(middlewares=[cors_middleware])
    
    # Роуты вебхуков
    app.router.add_post('/cryptopay', handler.handle_crypto_webhook)
    app.router.add_post('/platega-webhook', handler.handle_platega_webhook)
    app.router.add_post('/webhook/platega', handler.handle_platega_webhook)
    
    # Роуты возврата пользователя (чтобы не было 521/404)
    app.router.add_get('/pay_success', handler.handle_pay_success)
    app.router.add_get('/pay_failed', handler.handle_pay_failed)
    
    app.router.add_get('/health', handler.health_check)

    # === НОВЫЕ РОУТЫ MINI APP ===
    app.router.add_get('/api/user', handler.api_get_user)
    app.router.add_post('/api/check_task', handler.api_check_task)
    app.router.add_post('/api/invoice', handler.api_create_invoice)
    # ============================

    runner = web.AppRunner(app)
    await runner.setup()
    
    # Порт по умолчанию 8080 (как было в ТЗ)
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    
    logger.info("=" * 50)
    logger.info("Вебхук-сервер Nemo VPN запущен (Порт 8080) с поддержкой Mini App API!")
    logger.info("=" * 50)
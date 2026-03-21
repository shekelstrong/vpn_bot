"""
HTTP сервер для обработки вебхуков от Platega.
Запускается вместе с ботом в основном процессе.
"""

import asyncio
import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import Callable

from aiohttp import web
from loguru import logger

from database.db import db
from database.session import async_session_maker
from services.platega_webhook import handle_platega_webhook_update
from config import settings


class WebhookServer:

    def __init__(self, host: str = "0.0.0.0", port: int = None):
        self.host = host
        self.port = port if port is not None else settings.WEB_PORT
        self.app = web.Application()
        self.bot = None

        # Регистрируем роуты
        self.app.router.add_post('/webhook/platega', self.handle_platega_webhook)
        self.app.router.add_get('/health', self.handle_health)
        # Роуты для возврата пользователя после оплаты
        self.app.router.add_get('/pay_success', self.handle_pay_success)
        self.app.router.add_get('/pay_failed', self.handle_pay_failed)

    async def handle_health(self, request: web.Request) -> web.Response:
        """Health check endpoint"""
        return web.json_response({"status": "ok"})

    async def handle_pay_success(self, request: web.Request) -> web.Response:
        """
        Обработчик возврата пользователя после успешной оплаты.
        Перенаправляет в бота с параметром для отображения успеха.
        """
        order_id = request.query.get('order_id')

        if order_id:
            redirect_url = f"https://t.me/{(await self.bot.get_me()).username}?start=pay_success_{order_id}"
        else:
            redirect_url = f"https://t.me/{(await self.bot.get_me()).username}"

        raise web.HTTPSeeOther(redirect_url)

    async def handle_pay_failed(self, request: web.Request) -> web.Response:
        """
        Обработчик возврата пользователя после неудачной оплаты.
        Перенаправляет в бота с параметром для отображения ошибки.
        """
        redirect_url = f"https://t.me/{(await self.bot.get_me()).username}?start=pay_failed"
        raise web.HTTPSeeOther(redirect_url)

    async def handle_platega_webhook(self, request: web.Request) -> web.Response:
        """
        Обработка вебхука от Platega.
        """
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
            amount = Decimal(str(data.get("amount") or data.get("Amount") or data.get("total") or 0))
            currency = data.get("currency") or data.get("Currency") or "RUB"

            if not order_id:
                logger.error("No payload/order_id in webhook data")
                return web.json_response({"status": "error", "msg": "no payload"}, status=400)

            # Обрабатываем платеж
            result = await handle_platega_webhook_update(data, self.bot)

            return web.json_response(result)

        except json.JSONDecodeError:
            logger.error("Invalid JSON in webhook")
            return web.json_response({"status": "error", "msg": "invalid json"}, status=400)
        except Exception as e:
            logger.exception(f"Webhook error: {e}")
            return web.json_response({"status": "error", "msg": str(e)}, status=500)

    async def start(self, bot):
        self.bot = bot
        runner = web.AppRunner(self.app)
        await runner.setup()
        
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        protocol = "http"
        logger.info(f"🌐 Webhook server started on http://{self.host}:{self.port}")

        if settings.BASE_URL.startswith("http://") or settings.BASE_URL.startswith("https://"):
            webhook_url = f"{settings.BASE_URL}/webhook/platega"
        else:
            webhook_url = f"{protocol}://{settings.BASE_URL}/webhook/platega"
            
        logger.info(f"  🔗 Platega webhook URL: {webhook_url}")
        logger.info(f"  Health check: GET /health")

        return runner

    async def stop(self, runner):
        if runner:
            await runner.cleanup()
            logger.info("Webhook server stopped")
        else:
            logger.info("Webhook server: runner is None, skipping cleanup")


webhook_server = WebhookServer()
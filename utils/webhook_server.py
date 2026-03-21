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
        Показывает HTML-страницу с сообщением об успехе.
        """
        order_id = request.query.get('order_id')
        
        html_content = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Оплата успешна</title>
            <style>
                body {
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    min-height: 100vh;
                    margin: 0;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                }
                .container {
                    text-align: center;
                    background: white;
                    padding: 40px;
                    border-radius: 20px;
                    box-shadow: 0 10px 40px rgba(0,0,0,0.2);
                    max-width: 400px;
                }
                .checkmark {
                    width: 80px;
                    height: 80px;
                    background: #4CAF50;
                    border-radius: 50%;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    margin: 0 auto 20px;
                    font-size: 40px;
                    color: white;
                }
                h1 {
                    color: #333;
                    margin: 0 0 10px;
                }
                p {
                    color: #666;
                    line-height: 1.5;
                }
                .btn {
                    display: inline-block;
                    margin-top: 20px;
                    padding: 12px 30px;
                    background: #667eea;
                    color: white;
                    text-decoration: none;
                    border-radius: 25px;
                    font-weight: 600;
                    transition: transform 0.2s;
                }
                .btn:hover {
                    transform: scale(1.05);
                }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="checkmark">✓</div>
                <h1>Оплата успешна!</h1>
                <p>Ваша подписка активирована автоматически.</p>
                <p>Проверьте Telegram - там должно быть сообщение с доступом к VPN.</p>
                <a href="https://t.me/""" + (await self.bot.get_me()).username + """" class="btn">Открыть бота</a>
            </div>
        </body>
        </html>
        """
        
        return web.Response(text=html_content, content_type='text/html')

    async def handle_pay_failed(self, request: web.Request) -> web.Response:
        """
        Обработчик возврата пользователя после неудачной оплаты.
        Показывает HTML-страницу с сообщением об ошибке.
        """
        html_content = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Оплата не удалась</title>
            <style>
                body {
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    min-height: 100vh;
                    margin: 0;
                    background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
                }
                .container {
                    text-align: center;
                    background: white;
                    padding: 40px;
                    border-radius: 20px;
                    box-shadow: 0 10px 40px rgba(0,0,0,0.2);
                    max-width: 400px;
                }
                .cross {
                    width: 80px;
                    height: 80px;
                    background: #f5576c;
                    border-radius: 50%;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    margin: 0 auto 20px;
                    font-size: 40px;
                    color: white;
                }
                h1 {
                    color: #333;
                    margin: 0 0 10px;
                }
                p {
                    color: #666;
                    line-height: 1.5;
                }
                .btn {
                    display: inline-block;
                    margin-top: 20px;
                    padding: 12px 30px;
                    background: #f5576c;
                    color: white;
                    text-decoration: none;
                    border-radius: 25px;
                    font-weight: 600;
                    transition: transform 0.2s;
                }
                .btn:hover {
                    transform: scale(1.05);
                }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="cross">✕</div>
                <h1>Оплата не удалась</h1>
                <p>Платеж был отменен или не прошел.</p>
                <p>Вы можете попробовать еще раз или обратиться в поддержку.</p>
                <a href="https://t.me/""" + (await self.bot.get_me()).username + """" class="btn">Открыть бота</a>
            </div>
        </body>
        </html>
        """
        
        return web.Response(text=html_content, content_type='text/html')

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
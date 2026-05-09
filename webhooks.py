#!/usr/bin/env python3
"""
Вебхук-сервер для обработки платежей от CryptoBot и Platega.

ИЗМЕНЕНИЯ:
1. Два тарифа одновременно — inbound-ы суммируются (standard + premium)
2. Раздельные сроки: expire_standard и expire_premium в БД
3. Бонус +3 дня за подписку на @nemo_vpn_official (один раз)
4. Уведомление пользователю: ключи, инструкция (Happ, не V2Box)
5. Marzban: expire = max(expire_standard, expire_premium), inbounds = активные тарифы
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

# Ключ маршрутизации Happ (обход белых списков, РФ напрямую + DNS без утечек)
ROUTE_HAPP = "happ://routing/add/eyJOYW1lIjoi0KDQpCIsIkdsb2JhbFByb3h5Ijp0cnVlLCJEb21haW5TdHJhdGVneSI6IklQSWZOb25NYXRjaCIsIlJvdXRlT3JkZXIiOiJibG9jay1kaXJlY3QtcHJveHkiLCJEaXJlY3RTaXRlcyI6WyJnZW9zaXRlOmNhdGVnb3J5LXJ1Il0sIkRpcmVjdElwIjpbIjEwLjAuMC4wLzgiLCIxMDAuNjQuMC4wLzEwIiwiMTcyLjE2LjAuMC8xMiIsIjE5Mi4xNjguMC4wLzE2IiwiMTY5LjI1NC4wLjAvMTYiLCIyMjQuMC4wLjAvNCIsIjI1NS4yNTUuMjU1LjI1NSIsImdlb2lwOnJ1Il0sIlByb3h5U2l0ZXMiOltdLCJQcm94eUlwIjpbXSwiQmxvY2tTaXRlcyI6WyJnZW9zaXRlOmFkcyJdLCJCbG9ja0lwIjpbXSwiRG9tZXN0aWNETlNUeXBlIjoiRG9IIiwiRG9tZXN0aWNETlNJcCI6Ijc3Ljg4LjguOCIsIkRvbWVzdGljRE5TRG9tYWluIjoiaHR0cHM6Ly83Ny44OC44LjgvZG5zLXF1ZXJ5IiwiUmVtb3RlRE5TVHlwZSI6IkRvSCIsIlJlbW90ZUROU0lwIjoiMS4xLjEuMSIsIlJlbW90ZUROU0RvbWFpbiI6Imh0dHBzOi8vY2xvdWRmbGFyZS1kbnMuY29tL2Rucy1xdWVyeSIsIkRuc0hvc3RzIjp7ImxrZmwyLm5hbG9nLnJ1IjoiMjEzLjI0LjY0LjE3NSIsImxrbnBkLm5hbG9nLnJ1IjoiMjEzLjI0LjY0LjE4MSJ9LCJHZW9pcFVybCI6Imh0dHBzOi8vZ2l0aHViLmNvbS9Mb3lhbHNvbGRpZXIvdjJyYXktcnVsZXMtZGF0L3JlbGVhc2VzL2xhdGVzdC9kb3dubG9hZC9nZW9pcC5kYXQiLCJHZW9zaXRlVXJsIjoiaHR0cHM6Ly9naXRodWIuY29tL0xveWFsc29sZGllci92MnJheS1ydWxlcy1kYXQvcmVsZWFzZXMvbGF0ZXN0L2Rvd25sb2FkL2dlb3NpdGUuZGF0IiwiRmFrZURucyI6ZmFsc2UsIlVzZUNodW5rRmlsZXMiOnRydWUsIkxhc3RVcGRhdGVkIjowfQ=="


def append_singbox(url: str) -> str:
    """Добавить /sing-box к URL подписки, если ещё не добавлен."""
    if url and not url.endswith("/sing-box"):
        return f"{url.rstrip('/')}/sing-box"
    return url

# Канал Nemo VPN
CHANNEL_USERNAME = settings.CHANNEL_USERNAME

logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> - <level>{message}</level>",
    level="INFO",
)

log_path = Path("logs")
log_path.mkdir(exist_ok=True)
logger.add(log_path / "webhooks_{time:YYYY-MM-DD}.log", rotation="00:00", retention="7 days", level="DEBUG")


def validate_webhook_signature(body_text: str, signature: str, token: Optional[str] = None) -> bool:
    if token is None:
        token = settings.CRYPTO_BOT_TOKEN
    if not token or not signature:
        return False
    try:
        import hmac, hashlib
        secret = hashlib.sha256(token.encode()).digest()
        hmac_obj = hmac.new(secret, body_text.encode(), hashlib.sha256)
        return hmac_obj.hexdigest() == signature
    except Exception as e:
        logger.error(f"Ошибка проверки подписи: {e}")
        return False


async def check_channel_subscription(bot, user_id: int) -> bool:
    """Проверить подписку на канал @nemo_vpn_official."""
    try:
        from aiogram.types import ChatMemberMember, ChatMemberAdministrator, ChatMemberOwner, ChatMemberRestricted
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return isinstance(member, (ChatMemberMember, ChatMemberAdministrator, ChatMemberOwner, ChatMemberRestricted))
    except Exception as e:
        logger.warning(f"Не удалось проверить подписку на канал для {user_id}: {e}")
        return False


class WebhookHandler:
    def __init__(self):
        self.session_factory = get_session_factory()

    async def handle_pay_success(self, request: web.Request) -> web.Response:
        raise web.HTTPSeeOther("https://t.me/nemo_vpn_bot")

    async def handle_pay_failed(self, request: web.Request) -> web.Response:
        raise web.HTTPSeeOther("https://t.me/nemo_vpn_bot")

    async def handle_crypto_webhook(self, request: web.Request) -> web.Response:
        try:
            body_bytes = await request.read()
            body_text = body_bytes.decode('utf-8')
            signature = request.headers.get('crypto-pay-api-signature')
            if settings.CRYPTO_BOT_TOKEN and signature:
                if not check_webhook_signature(body_text, signature, settings.CRYPTO_BOT_TOKEN):
                    return web.json_response({"error": "Invalid signature"}, status=403)
            data = await request.json()
            if data.get("update_type") != "invoice_paid":
                return web.json_response({"status": "ok", "msg": "ignored type"})
            invoice = data.get("payload", {})
            order_id_str = invoice.get("payload")
            invoice_id = invoice.get("invoice_id")
            if not order_id_str:
                return web.json_response({"status": "ok"})
            try:
                order_id = int(order_id_str)
            except ValueError:
                return web.json_response({"status": "ok"})

            async with self.session_factory() as session:
                result = await session.execute(select(PaymentInvoice).where(PaymentInvoice.id == order_id))
                payment_invoice = result.scalar_one_or_none()
                if not payment_invoice:
                    return web.json_response({"status": "ok"})
                if payment_invoice.status == "paid":
                    return web.json_response({"status": "ok"})
                payment_invoice.status = "paid"
                payment_invoice.invoice_id = str(invoice_id)
                await session.commit()
                await session.refresh(payment_invoice)

                days = 30
                tier = "standard"
                device_count = 1
                gb_limit = 0
                if payment_invoice.payload:
                    try:
                        payload = json.loads(payment_invoice.payload)
                        days = payload.get("days", 30)
                        tier = payload.get("tier", "standard")
                        device_count = payload.get("device_count", 1)
                        gb_limit = payload.get("gb_limit", 0)
                    except:
                        pass

                await self.process_payment(
                    tg_user_id=payment_invoice.user_id,
                    amount=payment_invoice.amount,
                    currency=payment_invoice.currency,
                    payment_method='cryptobot',
                    payment_id=str(invoice_id),
                    days=days,
                    tier=tier,
                    device_count=device_count,
                    gb_limit=gb_limit
                )
                return web.json_response({"status": "ok"})
        except Exception as e:
            logger.error(f"CryptoBot webhook error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def handle_platega_webhook(self, request: web.Request) -> web.Response:
        try:
            try:
                data = await request.json()
            except json.JSONDecodeError:
                form_data = await request.post()
                data = dict(form_data)

            status = str(data.get("status") or data.get("Status") or data.get("STATUS", "")).upper()
            if status not in ("CONFIRMED", "SUCCESS", "PAID", "COMPLETED"):
                return web.json_response({"status": "ignored"})

            order_id = data.get("payload") or data.get("order_id") or data.get("orderId") or data.get("merchant_order_id")
            if not order_id:
                return web.json_response({"status": "error", "msg": "no payload"}, status=400)

            from services.platega_webhook import handle_platega_webhook_update
            from aiogram import Bot
            bot = Bot(token=settings.BOT_TOKEN)
            result = await handle_platega_webhook_update(data, bot)
            await bot.session.close()
            return web.json_response(result)
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
        days: int = 30,
        tier: str = "standard",
        device_count: int = 1,
        gb_limit: float = 0
    ):
        """Обработка успешного платежа: два тарифа, бонус за канал, раздельные сроки."""
        from aiogram import Bot
        bot = Bot(token=settings.BOT_TOKEN)

        async with self.session_factory() as session:
            try:
                result = await session.execute(select(User).where(User.user_id == tg_user_id))
                user = result.scalar_one_or_none()
                if not user:
                    logger.error(f"User {tg_user_id} not found during payment process")
                    return

                # Обновляем статус счета
                await session.execute(
                    update(PaymentInvoice)
                    .where(PaymentInvoice.invoice_id == payment_id)
                    .values(status="paid")
                )

                # Транзакция
                transaction = Transaction(
                    user_id=tg_user_id,
                    amount=amount,
                    currency=currency,
                    payment_method=payment_method,
                    status="paid",
                    payment_id=payment_id,
                    description=f"Оплата подписки на {days} дней ({'VIP' if tier == 'premium' else 'Обычный'}) | Устройств: {device_count}",
                )
                session.add(transaction)

                # === РАЗДЕЛЬНЫЕ СРОКИ ===
                now = datetime.utcnow()
                if tier == "premium":
                    if user.expire_premium and user.expire_premium > now:
                        user.expire_premium = user.expire_premium + timedelta(days=days)
                    else:
                        user.expire_premium = now + timedelta(days=days)
                    if gb_limit > 0:
                        user.gb_limit = gb_limit
                else:
                    if user.expire_standard and user.expire_standard > now:
                        user.expire_standard = user.expire_standard + timedelta(days=days)
                    else:
                        user.expire_standard = now + timedelta(days=days)

                # Пересчитываем единый expire_date
                user.recalculate_expire_date()
                # Tier: не понижаем. Если уже premium — остаётся premium
                if tier == "premium" or user.tier != "premium":
                    user.tier = tier
                user.device_count = device_count

                # === БОНУС ЗА ПОДПИСКУ НА КАНАЛ (+3 дня, один раз) ===
                channel_bonus_days = 0
                if not user.channel_bonus_given:
                    is_subscribed = await check_channel_subscription(bot, tg_user_id)
                    if is_subscribed:
                        channel_bonus_days = 3
                        # Бонус прибавляем к текущему тарифу
                        if tier == "premium":
                            user.expire_premium = user.expire_premium + timedelta(days=channel_bonus_days)
                        else:
                            user.expire_standard = user.expire_standard + timedelta(days=channel_bonus_days)
                        user.recalculate_expire_date()
                        user.channel_bonus_given = True
                        user.task_channel_sub = True
                        logger.info(f"Бонус +3 дня за подписку на канал начислен пользователю {tg_user_id}")

                # === РЕФЕРАЛЬНАЯ ЛОГИКА ===
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
                    bonus_amount = amount * (pct / 100)
                    referrer.referral_balance += bonus_amount
                    referrers_bonuses.append({
                        'level': level, 'id': referrer.user_id,
                        'username': referrer.username, 'bonus': bonus_amount
                    })
                    await notify_referrer_payment(
                        bot=bot, referrer_id=referrer.user_id,
                        referral_id=tg_user_id, bonus_amount=bonus_amount,
                        level=level, referral_username=user.username
                    )
                    current_referrer_id = referrer.referrer_id

                # === ОПРЕДЕЛЯЕМ АКТИВНЫЕ INBOUND-Ы ===
                active_inbounds = []
                if user.expire_standard and user.expire_standard > now:
                    active_inbounds.append("vless-reality-standard")
                if user.expire_premium and user.expire_premium > now:
                    active_inbounds.append("vless-reality-whitelist")

                # Вычисляем total_days для Marzban expire
                total_days = 0
                if user.expire_date and user.expire_date > now:
                    total_days = (user.expire_date - now).days
                else:
                    total_days = days + channel_bonus_days

                # === ОБНОВЛЯЕМ MARZBAN ===
                marzban_account_exists = False
                marzban_data = None
                if user.marzban_username:
                    try:
                        marzban_data = await marzban_service.get_user(user.marzban_username)
                        if marzban_data:
                            marzban_account_exists = True
                    except:
                        pass

                if marzban_account_exists:
                    # Обновляем существующий аккаунт: expire + inbounds + data_limit
                    current_used = (marzban_data or {}).get("used_traffic", 0) or 0
                    
                    # Рассчитываем data_limit
                    new_data_limit = None
                    if user.expire_premium and user.expire_premium > now and user.gb_limit and user.gb_limit > 0:
                        new_data_limit = int(current_used + user.gb_limit * 1024**3)

                    # Определяем proxies по активным inbound-ам
                    proxies = {"vless": {"flow": ""}}
                    if "vless-reality-whitelist" in active_inbounds:
                        proxies = {"vless": {"flow": "xtls-rprx-vision"}}

                    update_data = {
                        "expire": int((now + timedelta(days=total_days)).timestamp()),
                        "status": "active",
                        "proxies": proxies,
                        "inbounds": {"vless": active_inbounds},
                        "ip_limit": device_count,
                    }
                    if new_data_limit is not None:
                        update_data["data_limit"] = new_data_limit

                    await marzban_service._request("PUT", f"/user/{user.marzban_username}", json=update_data)
                    logger.info(f"Marzban обновлён для {user.marzban_username}: inbounds={active_inbounds}, +{total_days}д")
                else:
                    # Создаём новый аккаунт
                    gb_new = 0
                    if tier == "premium":
                        GB_MAP = {3: 3, 30: 100, 90: 350, 180: 800, 365: 2048}
                        gb_new = GB_MAP.get(days, days * 3)

                    new_acc = await marzban_service.create_user(
                        tg_id=tg_user_id,
                        username=user.username,
                        expire_days=total_days,
                        data_limit_gb=gb_new,
                        tier=tier,
                        device_count=device_count
                    )
                    user.marzban_username = new_acc.get('username')

                    # Если есть оба inbound-а — обновляем
                    if len(active_inbounds) > 1:
                        await marzban_service._request("PUT", f"/user/{user.marzban_username}", json={
                            "inbounds": {"vless": active_inbounds}
                        })

                await session.commit()

                # === УВЕДОМЛЕНИЕ ПОЛЬЗОВАТЕЛЮ ===
                try:
                    tier_name = "🚀 Обход белых списков (VIP)" if tier == "premium" else "🛡 Обычный VPN"
                    
                    sub_url = ""
                    vless_link = ""
                    if user.marzban_username:
                        sub_url = await marzban_service.get_user_subscription(user.marzban_username)
                        vless_link = await marzban_service.get_user_vless_link(user.marzban_username)
                        sub_url = append_singbox(sub_url)

                    msg = (
                        f"✅ <b>Оплата прошла успешно!</b>\n\n"
                        f"💎 Тариф: <b>{tier_name}</b>\n"
                        f"⏳ Подписка: <b>{days} дней</b>\n"
                        f"📱 Доступно устройств: <b>{device_count}</b>\n"
                        f"💰 Сумма: <b>{amount:.2f} {currency}</b>\n\n"
                    )

                    if channel_bonus_days > 0:
                        msg += f"🎁 <b>Бонус за подписку на канал:</b> +{channel_bonus_days} дня!\n\n"

                    if sub_url:
                        msg += (
                            f"🔑 <b>Ваш ключ подписки (Subscription URL):</b>\n"
                            f"<code>{sub_url}</code>\n\n"
                            f"📖 <b>Инструкция по подключению:</b>\n"
                            f"1. Нажмите на ключ выше, чтобы скопировать.\n"
                            f"2. Откройте приложение <b>Happ</b>.\n"
                            f"3. Нажмите «+» → <b>Import from Clipboard</b>.\n"
                            f"4. Обновите подписку и выберите сервер.\n"
                            f"5. Нажмите кнопку подключения — готово! 🎉\n\n"
                            f"📱 <b>Скачать Happ:</b>\n"
                            f"• <a href='https://apps.apple.com/us/app/happ-proxy-utility/id6504287215'>iOS / macOS</a>\n"
                            f"• <a href='https://play.google.com/store/apps/details?id=com.happproxy'>Android</a>\n"
                            f"• <a href='https://github.com/Happ-proxy/happ-desktop/releases/latest/download/setup-Happ.x64.exe'>Windows</a>\n"
                            f"• <a href='https://github.com/Happ-proxy/happ-desktop/releases/latest'>Linux</a>\n\n"
                        )
                        if tier == "premium":
                            msg += (
                                "💎 <b>Настройка маршрутизации (VIP):</b>\n\n"
                                "Российские сайты будут работать напрямую, а заблокированные — через VPN. "
                                "Нажмите кнопку ниже, чтобы применить ключ маршрутизации.\n\n"
                                f"📽 <a href='https://t.me/{settings.CHANNEL_USERNAME.lstrip('@')}/56'><b>Видео-инструкция</b></a>\n\n"
                                "На уровне сервера для вас включен БЛОК на посещение RU-сервисов через VPN — "
                                "они работают только напрямую, что делает ваш серфинг невидимым для проверок! 🔒\n"
                            )
                    else:
                        msg += "🔗 Ваша подписка активирована!\nПроверьте профиль для подключения."

                    await bot.send_message(tg_user_id, msg, parse_mode="HTML", disable_web_page_preview=True)

                    if sub_url and tier == "premium":
                        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                        routing_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="🔑 Импортировать маршрутизацию в Happ", url=ROUTE_HAPP)]
                        ])
                        await bot.send_message(
                            tg_user_id,
                            "👆 Нажмите кнопку выше, чтобы автоматически применить маршрутизацию в Happ.",
                            reply_markup=routing_keyboard,
                            parse_mode="HTML"
                        )

                    logger.info(f"Уведомление об успешной покупке доставлено пользователю {tg_user_id}")
                except Exception as e:
                    logger.warning(f"Не удалось отправить сообщение об успехе пользователю {tg_user_id}: {e}")

                await notify_admin_payment(
                    bot=bot, user_id=tg_user_id, amount_rub=amount,
                    username=user.username,
                    method=f"{payment_method} | Устройств: {device_count}",
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
    app.router.add_post('/cryptopay', handler.handle_crypto_webhook)
    app.router.add_post('/platega-webhook', handler.handle_platega_webhook)
    app.router.add_post('/webhook/platega', handler.handle_platega_webhook)
    app.router.add_get('/pay_success', handler.handle_pay_success)
    app.router.add_get('/pay_failed', handler.handle_pay_failed)
    app.router.add_get('/health', handler.health_check)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()

    logger.info("=" * 50)
    logger.info("Вебхук-сервер Nemo VPN запущен (Порт 8080)!")
    logger.info("Webhooks:")
    logger.info(f"  - https://{settings.BASE_URL}/cryptopay (CryptoBot)")
    logger.info(f"  - https://{settings.BASE_URL}/webhook/platega (Platega)")
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

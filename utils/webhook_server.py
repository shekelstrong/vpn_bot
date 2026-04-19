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

# Импорты обработчиков
from services.crypto_webhook import handle_crypto_webhook_update
from services.platega_webhook import handle_platega_webhook_update
from services.marzban_api import marzban_service
from services.payment_crypto import crypto_bot_service


@web.middleware
async def cors_middleware(request: web.Request, handler: Callable[[web.Request], Awaitable[web.StreamResponse]]) -> web.StreamResponse:
    """Middleware для обработки CORS."""
    # Логируем входящий путь для отладки
    logger.info(f"📡 API Request: {request.method} {request.path}")
    
    is_options = request.method == 'OPTIONS'
    
    if is_options:
        response = web.Response()
    else:
        try:
            response = await handler(request)
        except web.HTTPException as ex:
            response = ex
        except Exception as e:
            logger.error(f"Middleware Error: {e}")
            response = web.json_response({"error": "internal_server_error"}, status=500)
            
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With'
    
    return response


class WebhookHandler:
    """Обработчик HTTP-запросов для вебхуков и API."""

    def __init__(self, bot):
        self.bot = bot

    # ==========================================
    # РОУТЫ ВЕБХУКОВ
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
    # РОУТЫ ДЛЯ MINI APP (API)
    # ==========================================

    async def api_get_user(self, request: web.Request) -> web.Response:
        """Получить данные пользователя для отображения в Mini App."""
        try:
            tg_id_str = request.query.get("tg_id")
            if not tg_id_str:
                return web.json_response({"error": "tg_id is required"}, status=400)
                
            tg_id = int(tg_id_str)
            logger.info(f"👤 Запрос профиля для ID {tg_id}")
            
            async with get_session_factory()() as session:
                result = await session.execute(select(User).where(User.user_id == tg_id))
                user = result.scalar_one_or_none()
                
                if not user:
                    return web.json_response({"error": "user not found"}, status=404)
                
                used_traffic_gb = 0.0
                sub_url = ""
                vless_link = ""
                
                if user.marzban_username:
                    try:
                        mz_data = await marzban_service.get_user(user.marzban_username)
                        if mz_data:
                            used_traffic_gb = round(mz_data.get('used_traffic', 0) / (1024**3), 2)
                        
                        sub_url = await marzban_service.get_user_subscription(user.marzban_username)
                        if sub_url:
                            vless_link = await marzban_service.get_user_vless_link(user.marzban_username)
                    except Exception as e: 
                        logger.error(f"Ошибка получения данных из Marzban для {user.marzban_username}: {e}")

                days_left = 0
                if user.expire_date and user.expire_date > datetime.utcnow():
                    delta = user.expire_date - datetime.utcnow()
                    days_left = delta.days

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
                        "referral_balance": user.referral_balance,
                        "sub_url": sub_url,
                        "vless_link": vless_link
                    }
                })
        except Exception as e:
            logger.error(f"API Get User Error: {e}")
            return web.json_response({"error": "Internal server error"}, status=500)

    async def api_check_task(self, request: web.Request) -> web.Response:
        """Проверка подписки на ТГ-канал NEMO VPN для выдачи +3 дней."""
        try:
            data = await request.json()
            tg_id_raw = data.get("tg_id")
            
            # ЗАЩИТА: Если tg_id не передан или передан пустой
            if not tg_id_raw:
                return web.json_response({"error": "tg_id is required"}, status=400)
                
            tg_id = int(tg_id_raw)
            channel_id = "@nemo_vpn_official" 
            
            async with get_session_factory()() as session:
                result = await session.execute(select(User).where(User.user_id == tg_id))
                user = result.scalar_one_or_none()
                
                if not user:
                    return web.json_response({"error": "user not found"}, status=404)
                    
                if user.task_channel_sub:
                    return web.json_response({"status": "already_done", "message": "Задание уже выполнено"})

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
                        except Exception as e:
                            logger.error(f"Ошибка начисления +3 дней в Marzban: {e}")

                    await session.commit()
                    
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
        Создание реального инвойса и ссылки на оплату для Mini App.
        """
        try:
            data = await request.json()
            tg_id_raw = data.get("tg_id")
            
            # ЗАЩИТА: Если tg_id не передан
            if not tg_id_raw:
                return web.json_response({"error": "tg_id is required"}, status=400)
                
            tg_id = int(tg_id_raw)
            days = int(data.get("days", 30))
            tier = data.get("tier", "premium") 
            device_count = int(data.get("device_count", 1))
            gb_limit = float(data.get("gb_limit", 0))
            amount = float(data.get("amount", 300))
            payment_method = data.get("payment_method", "cryptopay")
            
            logger.info(f"💳 Создание счета для {tg_id} через {payment_method} на {amount} руб. Устройств: {device_count}, Лимит: {gb_limit} ГБ")

            pay_url = None
            final_invoice_id = ""

            # === СНАЧАЛА СОЗДАЕМ ЗАПИСЬ В БД ДЛЯ ПОЛУЧЕНИЯ РОДНОГО ID ===
            async with get_session_factory()() as session:
                import uuid
                # Временный ID для обхода ограничения UNIQUE
                temp_uid = f"temp_{uuid.uuid4().hex[:8]}"
                
                invoice = PaymentInvoice(
                    user_id=tg_id,
                    invoice_id=temp_uid,
                    amount=amount,
                    currency="RUB",
                    payment_method=payment_method,
                    status="pending",
                    payload=json.dumps({
                        "days": days, 
                        "tier": tier, 
                        "device_count": device_count,
                        "gb_limit": gb_limit
                    }),
                    created_at=datetime.utcnow()
                )
                session.add(invoice)
                await session.flush() # Получаем настоящий числовой ID из базы
                
                # Формируем правильные ID, которые понимают старые вебхуки
                if payment_method == "cryptopay":
                    # CryptoBot ожидает, что payload будет просто числом (ID)
                    final_invoice_id = str(invoice.id)
                elif payment_method == "platega":
                    # Platega ожидает строго формат 'platega_{tg_id}_{id}'
                    final_invoice_id = f"platega_{tg_id}_{invoice.id}"
                    
                invoice.invoice_id = final_invoice_id
                await session.commit()
                invoice_db_id = invoice.id

            # ЗАПРАШИВАЕМ ССЫЛКУ У ПЛАТЕЖЕК
            if payment_method == "cryptopay":
                try:
                    rate = getattr(settings, 'USDT_TO_RUB_RATE', 95.0)
                    price_usdt = round(amount / rate, 2)
                    
                    res = await crypto_bot_service.create_invoice(
                        amount_usdt=price_usdt,
                        order_id=final_invoice_id, 
                        description=f"Nemo VIP: {days} дней ({device_count} устр.)"
                    )
                    if res: pay_url = res[0]
                except Exception as e:
                    logger.error(f"Ошибка CryptoBot API: {e}")
                    raise Exception(f"Ошибка CryptoBot: {e}")
            
            elif payment_method == "platega":
                from services.payment_platega import create_invoice as create_sbp
                pay_url = await create_sbp(
                    amount_rub=int(amount),
                    order_id=final_invoice_id,
                    user_id=tg_id,
                    description=f"Nemo VIP: {days} дней ({device_count} устр.)"
                )

            # ЕСЛИ ПЛАТЕЖКА ВЕРНУЛА ОШИБКУ — УДАЛЯЕМ МУСОР ИЗ БАЗЫ
            if not pay_url:
                async with get_session_factory()() as session:
                    result = await session.execute(select(PaymentInvoice).where(PaymentInvoice.id == invoice_db_id))
                    inv_to_del = result.scalar_one_or_none()
                    if inv_to_del:
                        await session.delete(inv_to_del)
                        await session.commit()
                return web.json_response({"error": "Не удалось сгенерировать ссылку в платежной системе"}, status=500)

            return web.json_response({
                "status": "success", 
                "pay_url": pay_url,
                "invoice_id": final_invoice_id
            })
            
        except Exception as e:
            logger.error(f"API Create Invoice Error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return web.json_response({"error": str(e)}, status=500)

    async def api_pay_from_balance(self, request: web.Request) -> web.Response:
        """Оплата подписки с внутреннего/реферального баланса."""
        try:
            data = await request.json()
            tg_id_raw = data.get("tg_id")
            
            if not tg_id_raw:
                return web.json_response({"error": "tg_id is required"}, status=400)
                
            tg_id = int(tg_id_raw)
            days = int(data.get("days", 30))
            tier = data.get("tier", "premium") 
            device_count = int(data.get("device_count", 1))
            amount = float(data.get("amount", 300))
            
            logger.info(f"💰 Запрос на оплату с баланса: {tg_id}, сумма {amount} руб.")

            async with get_session_factory()() as session:
                # Находим пользователя
                result = await session.execute(select(User).where(User.user_id == tg_id))
                user = result.scalar_one_or_none()
                
                if not user:
                    return web.json_response({"error": "Пользователь не найден"}, status=404)
                    
                # Считаем общий баланс
                total_balance = user.balance + user.referral_balance
                
                if total_balance < amount:
                    return web.json_response({"error": f"Недостаточно средств. Ваш баланс: {total_balance} руб."}, status=400)
                    
                # Списываем средства (сначала с основного баланса, остаток с реферального)
                remaining_amount = amount
                if user.balance >= remaining_amount:
                    user.balance -= remaining_amount
                else:
                    remaining_amount -= user.balance
                    user.balance = 0.0
                    user.referral_balance -= remaining_amount
                
                import uuid
                payment_id = f"balance_{uuid.uuid4().hex[:8]}"

                # Записываем транзакцию
                from database.models import Transaction
                transaction = Transaction(
                    user_id=tg_id,
                    amount=amount,
                    currency="RUB",
                    payment_method="balance",
                    status="paid",
                    payment_id=payment_id,
                    description=f"Оплата с баланса на {days} дней ({'VIP' if tier == 'premium' else 'Обычный'}) | Устройств: {device_count}"
                )
                session.add(transaction)
                
                # Продлеваем подписку в БД
                now = datetime.utcnow()
                if user.expire_date and user.expire_date > now:
                    user.expire_date = user.expire_date + timedelta(days=days)
                else:
                    user.expire_date = now + timedelta(days=days)
                    
                user.tier = tier
                user.device_count = device_count
                
                # Обновляем Marzban
                try:
                    gb_limit_val = user.gb_limit or 0
                    if user.marzban_username:
                        marzban_data = await marzban_service.get_user(user.marzban_username)
                        if marzban_data:
                            await marzban_service.update_user_full(user.marzban_username, extra_days=days, tier=tier, device_count=device_count, data_limit_gb=gb_limit_val)
                        else:
                            new_acc = await marzban_service.create_user(tg_id, user.username, days, data_limit_gb=gb_limit_val, tier=tier, device_count=device_count)
                            user.marzban_username = new_acc.get('username')
                    else:
                        new_acc = await marzban_service.create_user(tg_id, user.username, days, data_limit_gb=gb_limit_val, tier=tier, device_count=device_count)
                        user.marzban_username = new_acc.get('username')
                except Exception as e:
                    logger.error(f"Ошибка Marzban при оплате с баланса: {e}")

                await session.commit()
                
            # Уведомляем юзера в телеграм
            try:
                tier_name = "🚀 Обход белых списков (VIP)" if tier == "premium" else "🛡 Обычный VPN"
                sub_url = ""
                vless_link = ""
                if user.marzban_username:
                    sub_url = await marzban_service.get_user_subscription(user.marzban_username)
                    vless_link = await marzban_service.get_user_vless_link(user.marzban_username)
                
                msg = (
                    f"✅ <b>Оплата с баланса прошла успешно!</b>\n\n"
                    f"💎 Тариф: <b>{tier_name}</b>\n"
                    f"⏳ Подписка: <b>{days} дней</b>\n"
                    f"📱 Доступно устройств: <b>{user.device_count}</b>\n"
                    f"💰 Списано: <b>{amount:.2f} RUB</b>\n\n"
                )
                
                if sub_url:
                    msg += (
                        f"🔑 <b>Ваш ключ доступа (Subscription URL):</b>\n<code>{sub_url}</code>\n\n"
                        f"🔗 <b>Прямой VLESS ключ:</b>\n<code>{vless_link}</code>\n\n"
                        f"Приятного пользования! 🎉"
                    )
                else:
                    msg += "🔗 Ваша подписка активирована!\nПроверьте профиль для подключения."
                    
                await self.bot.send_message(tg_id, msg, parse_mode="HTML")
            except Exception as e:
                logger.warning(f"Не удалось отправить уведомление {tg_id}: {e}")
                
            # Уведомляем админов
            try:
                user_display = f" @{user.username}" if user.username else f"ID: {tg_id}"
                admin_msg = (
                    f"💰 <b>Покупка с внутреннего баланса!</b>\n\n"
                    f"🆔 ID: <code>{tg_id}</code>\n"
                    f"👤 Профиль: {user_display}\n"
                    f"💵 Сумма: <b>{amount:.2f}₽</b>\n"
                    f"📦 Тариф: <b>{'VIP' if tier == 'premium' else 'Обычный'} ({days} дней)</b>\n"
                    f"📱 Устройств: <b>{device_count}</b>"
                )
                for admin_id in settings.admin_ids_list:
                    await self.bot.send_message(admin_id, admin_msg, parse_mode="HTML")
            except Exception as e:
                logger.error(f"Ошибка уведомления админов: {e}")

            return web.json_response({"status": "success", "message": "Оплата прошла успешно"})
            
        except Exception as e:
            logger.error(f"API Pay From Balance Error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return web.json_response({"error": str(e)}, status=500)

    # ==========================================
    # НОВЫЕ API ENDPOINTS: TRAFFIC / GIFT / REFERRAL
    # ==========================================

    async def api_buy_traffic(self, request: web.Request) -> web.Response:
        """Создание инвойса для покупки дополнительного трафика."""
        try:
            data = await request.json()
            tg_id_raw = data.get("tg_id")

            if not tg_id_raw:
                return web.json_response({"error": "tg_id is required"}, status=400)

            tg_id = int(tg_id_raw)
            gb = int(data["gb"])          # 50, 100, 300, 500
            price = int(data["price"])     # 100, 200, 600, 1000
            payment_method = data.get("payment_method", "cryptopay")

            logger.info(f"📦 Создание инвойса на трафик: {tg_id}, {gb} ГБ, {price}₽ через {payment_method}")

            # Проверяем что у пользователя есть активная подписка
            async with get_session_factory()() as session:
                result = await session.execute(select(User).where(User.user_id == tg_id))
                user = result.scalar_one_or_none()
                if not user:
                    return web.json_response({"error": "Пользователь не найден"}, status=404)
                if not user.marzban_username:
                    return web.json_response({"error": "У вас нет активной подписки"}, status=400)

            pay_url = None
            final_invoice_id = ""

            async with get_session_factory()() as session:
                import uuid
                temp_uid = f"temp_{uuid.uuid4().hex[:8]}"

                invoice = PaymentInvoice(
                    user_id=tg_id,
                    invoice_id=temp_uid,
                    amount=price,
                    currency="RUB",
                    payment_method=payment_method,
                    status="pending",
                    payload=json.dumps({
                        "type": "traffic",
                        "gb": gb,
                        "price": price
                    }),
                    created_at=datetime.utcnow()
                )
                session.add(invoice)
                await session.flush()

                if payment_method == "cryptopay":
                    final_invoice_id = str(invoice.id)
                elif payment_method == "platega":
                    final_invoice_id = f"platega_{tg_id}_{invoice.id}"

                invoice.invoice_id = final_invoice_id
                await session.commit()
                invoice_db_id = invoice.id

            # Запрашиваем ссылку у платёжки
            if payment_method == "cryptopay":
                try:
                    rate = getattr(settings, 'USDT_TO_RUB_RATE', 95.0)
                    price_usdt = round(price / rate, 2)

                    res = await crypto_bot_service.create_invoice(
                        amount_usdt=price_usdt,
                        order_id=final_invoice_id,
                        description=f"Nemo VPN: +{gb} ГБ трафика"
                    )
                    if res:
                        pay_url = res[0]
                except Exception as e:
                    logger.error(f"Ошибка CryptoBot API (traffic): {e}")
                    raise Exception(f"Ошибка CryptoBot: {e}")

            elif payment_method == "platega":
                from services.payment_platega import create_invoice as create_sbp
                pay_url = await create_sbp(
                    amount_rub=price,
                    order_id=final_invoice_id,
                    user_id=tg_id,
                    description=f"Nemo VPN: +{gb} ГБ трафика"
                )

            if not pay_url:
                async with get_session_factory()() as session:
                    result = await session.execute(select(PaymentInvoice).where(PaymentInvoice.id == invoice_db_id))
                    inv_to_del = result.scalar_one_or_none()
                    if inv_to_del:
                        await session.delete(inv_to_del)
                        await session.commit()
                return web.json_response({"error": "Не удалось сгенерировать ссылку"}, status=500)

            return web.json_response({
                "status": "success",
                "pay_url": pay_url,
                "invoice_id": final_invoice_id
            })

        except Exception as e:
            logger.error(f"API Buy Traffic Error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return web.json_response({"error": str(e)}, status=500)

    async def api_create_gift(self, request: web.Request) -> web.Response:
        """Создание инвойса для подарочной подписки."""
        try:
            data = await request.json()
            tg_id_raw = data.get("tg_id")

            if not tg_id_raw:
                return web.json_response({"error": "tg_id is required"}, status=400)

            tg_id = int(tg_id_raw)
            tier = data.get("tier", "premium")
            days = int(data.get("days", 30))
            payment_method = data.get("payment_method", "cryptopay")

            # Рассчитываем цену и gb_limit
            # Маппинг: 1 мес = 30 дней, 3 мес = 90, 6 мес = 180, 12 мес = 365
            months_map = {30: 1, 90: 3, 180: 6, 365: 12}
            months = months_map.get(days, 1)

            # GB лимиты по тарифу
            GB_LIMITS = {
                1: 100,   # 1 месяц — 100 ГБ
                3: 300,   # 3 месяца — 300 ГБ
                6: 600,   # 6 месяцев — 600 ГБ
                12: 0,    # 12 месяцев — безлимит
            }
            gb_limit = GB_LIMITS.get(months, 100)

            # Цены подарка (можно вынести в настройки)
            GIFT_PRICES = {
                ("premium", 30): 300,
                ("premium", 90): 800,
                ("premium", 180): 1400,
                ("premium", 365): 2500,
                ("standard", 30): 150,
                ("standard", 90): 400,
                ("standard", 180): 700,
                ("standard", 365): 1200,
            }
            price = data.get("price") or GIFT_PRICES.get((tier, days), 300)

            logger.info(f"🎁 Создание подарочного инвойса: {tg_id}, {tier}, {days}дн, {price}₽, {gb_limit} ГБ")

            pay_url = None
            final_invoice_id = ""

            async with get_session_factory()() as session:
                import uuid
                temp_uid = f"temp_{uuid.uuid4().hex[:8]}"

                invoice = PaymentInvoice(
                    user_id=tg_id,
                    invoice_id=temp_uid,
                    amount=price,
                    currency="RUB",
                    payment_method=payment_method,
                    status="pending",
                    payload=json.dumps({
                        "type": "gift",
                        "tier": tier,
                        "days": days,
                        "gb_limit": gb_limit,
                        "price": price
                    }),
                    created_at=datetime.utcnow()
                )
                session.add(invoice)
                await session.flush()

                if payment_method == "cryptopay":
                    final_invoice_id = str(invoice.id)
                elif payment_method == "platega":
                    final_invoice_id = f"platega_{tg_id}_{invoice.id}"

                invoice.invoice_id = final_invoice_id
                await session.commit()
                invoice_db_id = invoice.id

            # Запрашиваем ссылку у платёжки
            if payment_method == "cryptopay":
                try:
                    rate = getattr(settings, 'USDT_TO_RUB_RATE', 95.0)
                    price_usdt = round(price / rate, 2)

                    res = await crypto_bot_service.create_invoice(
                        amount_usdt=price_usdt,
                        order_id=final_invoice_id,
                        description=f"Nemo VPN: подарок ({tier}, {days}дн)"
                    )
                    if res:
                        pay_url = res[0]
                except Exception as e:
                    logger.error(f"Ошибка CryptoBot API (gift): {e}")
                    raise Exception(f"Ошибка CryptoBot: {e}")

            elif payment_method == "platega":
                from services.payment_platega import create_invoice as create_sbp
                pay_url = await create_sbp(
                    amount_rub=int(price),
                    order_id=final_invoice_id,
                    user_id=tg_id,
                    description=f"Nemo VPN: подарок ({tier}, {days}дн)"
                )

            if not pay_url:
                async with get_session_factory()() as session:
                    result = await session.execute(select(PaymentInvoice).where(PaymentInvoice.id == invoice_db_id))
                    inv_to_del = result.scalar_one_or_none()
                    if inv_to_del:
                        await session.delete(inv_to_del)
                        await session.commit()
                return web.json_response({"error": "Не удалось сгенерировать ссылку"}, status=500)

            return web.json_response({
                "status": "success",
                "pay_url": pay_url,
                "invoice_id": final_invoice_id
            })

        except Exception as e:
            logger.error(f"API Create Gift Error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return web.json_response({"error": str(e)}, status=500)

    async def api_pay_referral(self, request: web.Request) -> web.Response:
        """Оплата подписки из реферального баланса."""
        try:
            data = await request.json()
            tg_id_raw = data.get("tg_id")

            if not tg_id_raw:
                return web.json_response({"error": "tg_id is required"}, status=400)

            tg_id = int(tg_id_raw)
            days = int(data.get("days", 30))
            tier = data.get("tier", "premium")

            # Определяем цену (аналогично gift/subscription)
            GIFT_PRICES = {
                ("premium", 30): 300,
                ("premium", 90): 800,
                ("premium", 180): 1400,
                ("premium", 365): 2500,
                ("standard", 30): 150,
                ("standard", 90): 400,
                ("standard", 180): 700,
                ("standard", 365): 1200,
            }
            amount = float(data.get("amount") or GIFT_PRICES.get((tier, days), 300))

            logger.info(f"👥 Оплата с реферального баланса: {tg_id}, {amount}₽, {tier}, {days}дн")

            async with get_session_factory()() as session:
                result = await session.execute(select(User).where(User.user_id == tg_id))
                user = result.scalar_one_or_none()

                if not user:
                    return web.json_response({"error": "Пользователь не найден"}, status=404)

                if user.referral_balance < amount:
                    return web.json_response({
                        "error": f"Недостаточно средств на реферальном балансе. Баланс: {user.referral_balance:.2f}₽, нужно: {amount:.2f}₽"
                    }, status=400)

                # Списываем с реферального баланса
                user.referral_balance -= amount

                import uuid
                from database.models import Transaction
                payment_id = f"referral_{uuid.uuid4().hex[:8]}"

                transaction = Transaction(
                    user_id=tg_id,
                    amount=amount,
                    currency="RUB",
                    payment_method="referral_balance",
                    status="paid",
                    payment_id=payment_id,
                    description=f"Оплата с реферального баланса на {days} дней ({'VIP' if tier == 'premium' else 'Обычный'})"
                )
                session.add(transaction)

                # Продлеваем подписку
                now = datetime.utcnow()
                if user.expire_date and user.expire_date > now:
                    user.expire_date = user.expire_date + timedelta(days=days)
                else:
                    user.expire_date = now + timedelta(days=days)

                user.tier = tier

                # Обновляем Marzban
                try:
                    gb_limit_val = user.gb_limit or 0
                    if user.marzban_username:
                        marzban_data = await marzban_service.get_user(user.marzban_username)
                        if marzban_data:
                            await marzban_service.update_user_full(
                                user.marzban_username,
                                extra_days=days,
                                tier=tier,
                                device_count=user.device_count,
                                data_limit_gb=gb_limit_val
                            )
                        else:
                            new_acc = await marzban_service.create_user(
                                tg_id, user.username, days,
                                data_limit_gb=gb_limit_val, tier=tier, device_count=user.device_count
                            )
                            user.marzban_username = new_acc.get('username')
                    else:
                        new_acc = await marzban_service.create_user(
                            tg_id, user.username, days,
                            data_limit_gb=gb_limit_val, tier=tier, device_count=user.device_count
                        )
                        user.marzban_username = new_acc.get('username')
                except Exception as e:
                    logger.error(f"Ошибка Marzban при оплате с реферального баланса: {e}")

                # Реферальные бонусы пригласившему
                referrers_bonuses = []
                try:
                    percentages = settings.referral_percentages_list
                    current_referrer_id = user.referrer_id

                    for level, pct in enumerate(percentages, 1):
                        if not current_referrer_id:
                            break
                        ref_res = await session.execute(select(User).where(User.user_id == current_referrer_id))
                        referrer = ref_res.scalar_one_or_none()
                        if not referrer:
                            break

                        bonus = amount * (pct / 100.0)
                        referrer.referral_balance += bonus
                        referrers_bonuses.append({
                            'level': level, 'id': referrer.user_id,
                            'username': referrer.username, 'bonus': bonus
                        })

                        # Уведомляем реферера
                        try:
                            await self.bot.send_message(
                                referrer.user_id,
                                f"💸 <b>Реферальное начисление!</b>\n\n"
                                f"Ваш реферал (ID: {tg_id}) оплатил подписку с реферального баланса.\n"
                                f"Вам начислено: <b>+{bonus:.2f}₽</b> ({level} уровень, {pct}%)\n\n"
                                f"Реферальный баланс: {referrer.referral_balance:.2f}₽",
                                parse_mode="HTML"
                            )
                        except Exception as e:
                            logger.warning(f"Не удалось уведомить реферера {referrer.user_id}: {e}")

                        current_referrer_id = referrer.referrer_id
                except Exception as e:
                    logger.error(f"Ошибка начисления реферальных бонусов: {e}")

                await session.commit()

            # Уведомляем пользователя
            try:
                tier_name = "🚀 Обход белых списков (VIP)" if tier == "premium" else "🛡 Обычный VPN"
                sub_url = ""
                vless_link = ""
                if user.marzban_username:
                    sub_url = await marzban_service.get_user_subscription(user.marzban_username)
                    vless_link = await marzban_service.get_user_vless_link(user.marzban_username)

                msg = (
                    f"✅ <b>Оплата с реферального баланса прошла успешно!</b>\n\n"
                    f"💎 Тариф: <b>{tier_name}</b>\n"
                    f"⏳ Подписка: <b>{days} дней</b>\n"
                    f"💰 Списано: <b>{amount:.2f}₽</b> с реферального баланса\n\n"
                )
                if sub_url:
                    msg += (
                        f"🔑 <b>Subscription URL:</b>\n<code>{sub_url}</code>\n\n"
                        f"🔗 <b>VLESS ключ:</b>\n<code>{vless_link}</code>\n\n"
                        f"Приятного пользования! 🎉"
                    )
                else:
                    msg += "🔗 Подписка активирована!\nПроверьте профиль для подключения."

                await self.bot.send_message(tg_id, msg, parse_mode="HTML")
            except Exception as e:
                logger.warning(f"Не удалось уведомить {tg_id}: {e}")

            # Уведомляем админов
            try:
                user_display = f" @{user.username}" if user.username else f"ID: {tg_id}"
                admin_msg = (
                    f"👥 <b>Покупка с реферального баланса!</b>\n\n"
                    f"🆔 ID: <code>{tg_id}</code>\n"
                    f"👤 Профиль: {user_display}\n"
                    f"💵 Сумма: <b>{amount:.2f}₽</b>\n"
                    f"📦 Тариф: <b>{'VIP' if tier == 'premium' else 'Обычный'} ({days} дней)</b>"
                )
                for admin_id in settings.admin_ids_list:
                    await self.bot.send_message(admin_id, admin_msg, parse_mode="HTML")
            except Exception as e:
                logger.error(f"Ошибка уведомления админов: {e}")

            return web.json_response({"status": "success", "message": "Оплата прошла успешно"})

        except Exception as e:
            logger.error(f"API Pay Referral Error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return web.json_response({"error": str(e)}, status=500)


async def run_webhooks(bot=None):
    """Функция запуска веб-сервера."""
    await init_db()
    
    handler = WebhookHandler(bot=bot)
    
    # Добавляем middleware для CORS
    app = web.Application(middlewares=[cors_middleware])
    
    # Роуты вебхуков
    app.router.add_post('/cryptopay', handler.handle_crypto_webhook)
    app.router.add_post('/platega-webhook', handler.handle_platega_webhook)
    app.router.add_post('/webhook/platega', handler.handle_platega_webhook)
    
    # Роуты возврата пользователя
    app.router.add_get('/pay_success', handler.handle_pay_success)
    app.router.add_get('/pay_failed', handler.handle_pay_failed)
    
    app.router.add_get('/health', handler.health_check)

    # === РОУТЫ MINI APP API ===
    app.router.add_get('/api/user', handler.api_get_user)
    app.router.add_post('/api/check_task', handler.api_check_task)
    app.router.add_post('/api/invoice', handler.api_create_invoice)
    app.router.add_post('/api/pay_balance', handler.api_pay_from_balance)
    
    # === НОВЫЕ РОУТЫ: TRAFFIC / GIFT / REFERRAL ===
    app.router.add_post('/api/buy_traffic', handler.api_buy_traffic)
    app.router.add_post('/api/create_gift', handler.api_create_gift)
    app.router.add_post('/api/pay_referral', handler.api_pay_referral)
    # ============================================

    runner = web.AppRunner(app)
    await runner.setup()
    
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    
    logger.info("=" * 50)
    logger.info("Вебхук-сервер Nemo VPN запущен (Порт 8080) с поддержкой Mini App API!")
    logger.info("=" * 50)

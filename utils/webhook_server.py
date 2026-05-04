"""
Сервер вебхуков для Nemo VPN.
Обрабатывает платежи Platega, CryptoPay и предоставляет REST API для Telegram Mini App.
"""

from aiohttp import web
import json
from loguru import logger
from datetime import datetime, timedelta
from typing import Callable, Awaitable

import hashlib
import hmac
from urllib.parse import parse_qs

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from database.engine import get_session_factory, init_db
from database.models import User, PaymentInvoice
from config import settings

# Импорты обработчиков
from services.crypto_webhook import handle_crypto_webhook_update
from services.platega_webhook import handle_platega_webhook_update
from services.marzban_api import marzban_service
from services.payment_crypto import crypto_bot_service


async def _find_orphan_marzban_account(tg_id: int) -> str | None:
    """Найти сиротский Marzban-аккаунт для данного tg_id.
    Ищет по паттернам user_{tg_id}_* и tg_{tg_id}_*."""
    try:
        import httpx
        token = await marzban_service.get_token()
        headers = {"Authorization": f"Bearer {token}"}
        base = marzban_service.base_url
        async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
            resp = await client.get(f"{base}/users", headers=headers, params={"username": f"user_{tg_id}_"})
            if resp.status_code == 200:
                data = resp.json()
                for u in data.get("users", []):
                    uname = u.get("username", "")
                    if uname.startswith(f"user_{tg_id}_") or uname.startswith(f"tg_{tg_id}_"):
                        return uname
    except Exception as e:
        logger.warning(f"Marzban lookup сироты {tg_id}: {e}")
    return None


async def _sync_marzban_to_user(user: User) -> None:
    """Синхронизировать данные из Marzban в локальную модель User.
    Подтягивает tier, expire, data_limit из активного Marzban-аккаунта."""
    if not user.marzban_username:
        return
    try:
        mz = await marzban_service.get_user(user.marzban_username)
        if not mz:
            return

        now = datetime.utcnow()
        expire_ts = mz.get("expire") or 0
        data_limit = mz.get("data_limit") or 0
        used_traffic = mz.get("used_traffic") or 0
        inbounds = mz.get("inbounds", {}).get("vless", [])

        # Определяем tier по inbound-ам
        if "vless-reality-whitelist" in inbounds:
            user.tier = "premium"
            if expire_ts > int(now.timestamp()):
                user.expire_premium = datetime.utcfromtimestamp(expire_ts)
        else:
            user.tier = "standard"
            if expire_ts > int(now.timestamp()):
                user.expire_standard = datetime.utcfromtimestamp(expire_ts)

        # Общий expire_date
        if expire_ts > 0:
            user.expire_date = datetime.utcfromtimestamp(expire_ts) if expire_ts > int(now.timestamp()) else None

        # Трафик
        if data_limit > 0:
            user.gb_limit = round(data_limit / (1024**3), 2)

        # ip_limit
        ip_limit = mz.get("ip_limit") or 1
        user.device_count = ip_limit

        user.recalculate_expire_date()
        logger.info(f"🔧 Синхронизированы данные Marzban → User для {user.user_id}: tier={user.tier}, expire={user.expire_date}")
    except Exception as e:
        logger.error(f"Ошибка синхронизации Marzban для {user.user_id}: {e}")


async def _ensure_user_exists(session, tg_id: int, username: str = None) -> User:
    """Убедиться что пользователь существует в БД бота.
    Если нет — создать запись. Если есть Marzban-аккаунт — привязать и синхронизировать."""
    result = await session.execute(select(User).where(User.user_id == tg_id))
    user = result.scalar_one_or_none()
    if user:
        return user

    import uuid as _uuid
    marzban_username = f"tg_{tg_id}_{_uuid.uuid4().hex[:6]}"

    # Ищем сиротский аккаунт в Marzban
    orphan = await _find_orphan_marzban_account(tg_id)
    if orphan:
        marzban_username = orphan

    user = User(
        user_id=tg_id,
        username=username,
        marzban_username=marzban_username,
    )

    # Если нашли сироту — синхронизируем данные
    if orphan:
        await _sync_marzban_to_user(user)

    session.add(user)
    try:
        await session.commit()
        logger.info(f"🔧 Авто-создан пользователь {tg_id} (marzban: {marzban_username}, tier: {user.tier})")
    except IntegrityError:
        await session.rollback()
        result = await session.execute(select(User).where(User.user_id == tg_id))
        user = result.scalar_one_or_none()
    return user


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
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With, X-Telegram-InitData'
    
    return response


class WebhookHandler:
    """Обработчик HTTP-запросов для вебхуков и API."""

    def __init__(self, bot):
        self.bot = bot

    def _validate_tg_init_data(self, request: web.Request, expected_tg_id: int = None) -> bool:
        """Валидация Telegram WebApp initData.
        Если заголовок есть — проверяем подпись и tg_id.
        Если заголовка нет — пропускаем (для обратной совместимости).
        """
        init_data = request.headers.get('X-Telegram-InitData')
        if not init_data:
            # Нет заголовка — старый клиент, пропускаем
            return True

        try:
            # Парсим initData
            parsed = parse_qs(init_data)
            hash_val = parsed.get('hash', [None])[0]
            if not hash_val:
                return False

            # Проверяем HMAC-SHA256
            secret_key = hmac.new(b'WebAppData', settings.BOT_TOKEN.encode(), hashlib.sha256).digest()
            check_string = '\n'.join(f'{k}={v[0]}' for k, v in sorted(parsed.items()) if k != 'hash')
            computed = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()

            if computed != hash_val:
                logger.warning(f"Invalid initData signature from {expected_tg_id}")
                return False

            # Проверяем tg_id если передан
            if expected_tg_id:
                user_data = parsed.get('user', [None])[0]
                if user_data:
                    user_json = json.loads(user_data)
                    if user_json.get('id') != expected_tg_id:
                        logger.warning(f"initData tg_id mismatch: {user_json.get('id')} != {expected_tg_id}")
                        return False
            return True
        except Exception as e:
            logger.error(f"initData validation error: {e}")
            return False

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

    async def api_regenerate_key(self, request: web.Request) -> web.Response:
        """Перегенерация VPN ключа через мини-апп. Delete + Create (Marzban 0.8.4)."""
        try:
            data = await request.json()
            tg_id = int(data.get("tg_id"))
            if not self._validate_tg_init_data(request, tg_id):
                return web.json_response({"error": "Unauthorized"}, status=401)

            async with get_session_factory()() as session:
                result = await session.execute(select(User).where(User.user_id == tg_id))
                user = result.scalar_one_or_none()
                if not user:
                    return web.json_response({"error": "Пользователь не найден"}, status=404)
                if not user.marzban_username:
                    return web.json_response({"error": "Нет активной подписки"}, status=400)

                # Получаем текущие данные
                marzban_data = await marzban_service.get_user(user.marzban_username)
                if not marzban_data:
                    return web.json_response({"error": "Аккаунт не найден в Marzban"}, status=404)

                current_expire = marzban_data.get("expire") or 0
                current_data_limit = marzban_data.get("data_limit")
                current_ip_limit = marzban_data.get("ip_limit", 1) or 1
                current_inbounds = marzban_data.get("inbounds", {}).get("vless", ["vless-reality-standard"])
                current_used = marzban_data.get("used_traffic", 0) or 0

                now = datetime.utcnow()
                current_ts = int(now.timestamp())
                days_left = (current_expire - current_ts) // 86400 + 1 if current_expire > current_ts else 0
                if days_left <= 0:
                    return web.json_response({"error": "Подписка истекла"}, status=400)

                # Delete + Create
                await marzban_service.delete_user(user.marzban_username)

                new_gb = 0
                if current_data_limit and current_data_limit > 0:
                    new_gb = max(0, (current_data_limit - current_used) / (1024**3))

                new_acc = await marzban_service.create_user(
                    tg_id=tg_id, username=user.username,
                    expire_days=days_left, data_limit_gb=new_gb,
                    tier=user.tier or "standard", device_count=current_ip_limit,
                    inbounds=current_inbounds
                )
                user.marzban_username = new_acc.get('username')
                await session.commit()

                sub_url = new_acc.get("subscription_url", "")
                if sub_url and sub_url.startswith("/"):
                    sub_url = f"{settings.MARZBAN_URL.rstrip('/')}{sub_url}"

                return web.json_response({"status": "ok", "sub_url": sub_url})

        except Exception as e:
            logger.error(f"API regenerate_key error: {e}")
            return web.json_response({"error": str(e)}, status=500)

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
            if not self._validate_tg_init_data(request, tg_id):
                return web.json_response({"error": "Unauthorized"}, status=401)
            logger.info(f"👤 Запрос профиля для ID {tg_id}")
            
            async with get_session_factory()() as session:
                result = await session.execute(select(User).where(User.user_id == tg_id))
                user = result.scalar_one_or_none()
                
                if not user:
                    # Авто-создание юзера, если его нет в БД (зашёл через Mini App минуя /start)
                    logger.info(f"🔧 Пользователь {tg_id} не найден в БД, авто-создание...")
                    try:
                        user = await _ensure_user_exists(session, tg_id, None)
                    except Exception as e:
                        logger.error(f"Ошибка авто-создания юзера {tg_id}: {e}")
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

                # Раздельные сроки подписок
                now = datetime.utcnow()
                standard_days = 0
                premium_days = 0
                standard_expire = None
                premium_expire = None
                if user.expire_standard and user.expire_standard > now:
                    standard_days = (user.expire_standard - now).days
                    standard_expire = user.expire_standard.strftime('%d.%m.%Y')
                if user.expire_premium and user.expire_premium > now:
                    premium_days = (user.expire_premium - now).days
                    premium_expire = user.expire_premium.strftime('%d.%m.%Y')

                bot_info = await self.bot.get_me()
                ref_link = f"https://t.me/{bot_info.username}?start={user.user_id}"

                return web.json_response({
                    "status": "success",
                    "user": {
                        "user_id": user.user_id,
                        "username": user.username or "Пользователь",
                        "tier": user.tier,
                        "days_left": days_left,
                        "standard_days": standard_days,
                        "standard_expire": standard_expire,
                        "premium_days": premium_days,
                        "premium_expire": premium_expire,
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
            if not self._validate_tg_init_data(request, tg_id):
                return web.json_response({"error": "Unauthorized"}, status=401)
            channel_id = settings.CHANNEL_USERNAME 
            
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
            if not self._validate_tg_init_data(request, tg_id):
                return web.json_response({"error": "Unauthorized"}, status=401)
            days = int(data.get("days", 30))
            tier = data.get("tier", "premium") 
            device_count = int(data.get("device_count", 1))
            gb_limit = float(data.get("gb_limit", 0))
            amount = float(data.get("amount", 300))
            payment_method = data.get("payment_method", "cryptopay")
            
            logger.info(f"💳 Создание счета для {tg_id} через {payment_method} на {amount} руб. Устройств: {device_count}, Лимит: {gb_limit} ГБ")

            # УБЕДИТЬСЯ ЧТО ЮЗЕР СУЩЕСТВУЕТ В БД (иначе FOREIGN KEY на PaymentInvoice упадёт)
            async with get_session_factory()() as ensure_session:
                try:
                    await _ensure_user_exists(ensure_session, tg_id, None)
                except Exception as e:
                    logger.error(f"Ошибка обеспечения юзера {tg_id}: {e}")

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
            if not self._validate_tg_init_data(request, tg_id):
                return web.json_response({"error": "Unauthorized"}, status=401)
            days = int(data.get("days", 30))
            tier = data.get("tier", "premium") 
            device_count = int(data.get("device_count", 1))
            amount = float(data.get("amount", 300))
            gb_limit = float(data.get("gb_limit", 0))
            
            logger.info(f"💰 Запрос на оплату с баланса: {tg_id}, сумма {amount} руб.")

            async with get_session_factory()() as session:
                # Находим пользователя (с блокировкой от race condition)
                result = await session.execute(select(User).where(User.user_id == tg_id).with_for_update())
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
                
                # === РАЗДЕЛЬНЫЕ СРОКИ (как в webhooks.py) ===
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
                # Tier: не понижаем
                if tier == "premium" or user.tier != "premium":
                    user.tier = tier
                user.device_count = device_count

                # === АКТИВНЫЕ INBOUNDS ===
                active_inbounds = []
                if user.expire_standard and user.expire_standard > now:
                    active_inbounds.append("vless-reality-standard")
                if user.expire_premium and user.expire_premium > now:
                    active_inbounds.append("vless-reality-whitelist")

                # === ОБНОВЛЯЕМ MARZBAN ===
                try:
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
                        current_used = (marzban_data or {}).get("used_traffic", 0) or 0

                        # data_limit — ТОЛЬКО для premium
                        new_data_limit = None
                        if user.expire_premium and user.expire_premium > now and user.gb_limit and user.gb_limit > 0:
                            new_data_limit = int(current_used + user.gb_limit * 1024**3)

                        proxies = {"vless": {"flow": ""}}
                        if "vless-reality-whitelist" in active_inbounds:
                            proxies = {"vless": {"flow": "xtls-rprx-vision"}}

                        total_days = 0
                        if user.expire_date and user.expire_date > now:
                            total_days = (user.expire_date - now).days
                        else:
                            total_days = days

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
                        logger.info(f"Marzban обновлён [balance]: {user.marzban_username}, inbounds={active_inbounds}, +{total_days}д")
                    else:
                        gb_new = 0
                        if tier == "premium":
                            GB_MAP = {3: 3, 30: 100, 90: 350, 180: 800, 365: 2048}
                            gb_new = GB_MAP.get(days, days * 3)
                        new_acc = await marzban_service.create_user(tg_id, user.username, days, data_limit_gb=gb_new, tier=tier, device_count=device_count)
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
            if not self._validate_tg_init_data(request, tg_id):
                return web.json_response({"error": "Unauthorized"}, status=401)
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
                if user.tier != "premium":
                    return web.json_response({"error": "Докупка трафика доступна только для VIP-тарифа. У вас безлимитный трафик!"}, status=400)

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
            if not self._validate_tg_init_data(request, tg_id):
                return web.json_response({"error": "Unauthorized"}, status=401)

            tg_id = int(tg_id_raw)
            tier = data.get("tier", "premium")
            days = int(data.get("days", 30))
            payment_method = data.get("payment_method", "cryptopay")

            # Рассчитываем цену и gb_limit
            # Маппинг: 1 мес = 30 дней, 3 мес = 90, 6 мес = 180, 12 мес = 365
            months_map = {30: 1, 90: 3, 180: 6, 365: 12}
            months = months_map.get(days, 1)

            # GB лимиты только для VIP (стандарт = безлимит)
            if tier == "standard":
                gb_limit = 0
            else:
                GB_LIMITS = {
                    30: 100,   # 1 месяц — 100 ГБ
                    90: 350,   # 3 месяца — 350 ГБ
                    180: 800,  # 6 месяцев — 800 ГБ
                    365: 2048, # 12 месяцев — 2 ТБ
                }
                gb_limit = GB_LIMITS.get(days, days * 3)

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
            if not self._validate_tg_init_data(request, tg_id):
                return web.json_response({"error": "Unauthorized"}, status=401)
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
                result = await session.execute(select(User).where(User.user_id == tg_id).with_for_update())
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

                # === РАЗДЕЛЬНЫЕ СРОКИ (как в webhooks.py) ===
                now = datetime.utcnow()
                if tier == "premium":
                    if user.expire_premium and user.expire_premium > now:
                        user.expire_premium = user.expire_premium + timedelta(days=days)
                    else:
                        user.expire_premium = now + timedelta(days=days)
                else:
                    if user.expire_standard and user.expire_standard > now:
                        user.expire_standard = user.expire_standard + timedelta(days=days)
                    else:
                        user.expire_standard = now + timedelta(days=days)

                # Пересчитываем единый expire_date
                user.recalculate_expire_date()
                # Tier: не понижаем
                if tier == "premium" or user.tier != "premium":
                    user.tier = tier

                # === АКТИВНЫЕ INBOUNDS ===
                active_inbounds = []
                if user.expire_standard and user.expire_standard > now:
                    active_inbounds.append("vless-reality-standard")
                if user.expire_premium and user.expire_premium > now:
                    active_inbounds.append("vless-reality-whitelist")

                # === ОБНОВЛЯЕМ MARZBAN ===
                try:
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
                        current_used = (marzban_data or {}).get("used_traffic", 0) or 0

                        # data_limit — ТОЛЬКО для premium
                        new_data_limit = None
                        if user.expire_premium and user.expire_premium > now and user.gb_limit and user.gb_limit > 0:
                            new_data_limit = int(current_used + user.gb_limit * 1024**3)

                        proxies = {"vless": {"flow": ""}}
                        if "vless-reality-whitelist" in active_inbounds:
                            proxies = {"vless": {"flow": "xtls-rprx-vision"}}

                        total_days = 0
                        if user.expire_date and user.expire_date > now:
                            total_days = (user.expire_date - now).days
                        else:
                            total_days = days

                        update_data = {
                            "expire": int((now + timedelta(days=total_days)).timestamp()),
                            "status": "active",
                            "proxies": proxies,
                            "inbounds": {"vless": active_inbounds},
                            "ip_limit": user.device_count or 1,
                        }
                        if new_data_limit is not None:
                            update_data["data_limit"] = new_data_limit

                        await marzban_service._request("PUT", f"/user/{user.marzban_username}", json=update_data)
                        logger.info(f"Marzban обновлён [referral]: {user.marzban_username}, inbounds={active_inbounds}, +{total_days}д")
                    else:
                        gb_new = 0
                        if tier == "premium":
                            GB_MAP = {3: 3, 30: 100, 90: 350, 180: 800, 365: 2048}
                            gb_new = GB_MAP.get(days, days * 3)
                        new_acc = await marzban_service.create_user(
                            tg_id, user.username, days,
                            data_limit_gb=gb_new, tier=tier, device_count=user.device_count
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

    async def api_buy_traffic_referral(self, request: web.Request) -> web.Response:
        """Докупка трафика из реферального баланса."""
        try:
            data = await request.json()
            tg_id = int(data.get("tg_id"))
            if not self._validate_tg_init_data(request, tg_id):
                return web.json_response({"error": "Unauthorized"}, status=401)
            gb = int(data.get("gb"))
            price = int(data.get("price"))
            
            logger.info(f"📦 Докупка трафика из реф баланса: {tg_id}, +{gb}ГБ, {price}₽")
            
            async with get_session_factory()() as session:
                result = await session.execute(select(User).where(User.user_id == tg_id).with_for_update())
                user = result.scalar_one_or_none()
                if not user:
                    return web.json_response({"error": "Пользователь не найден"}, status=404)
                
                if user.tier != "premium":
                    return web.json_response({"error": "Докупка трафика доступна только для VIP-тарифа. У вас безлимитный трафик!"}, status=400)
                
                if user.referral_balance < price:
                    return web.json_response({"error": f"Недостаточно средств. Баланс: {user.referral_balance:.0f}₽, нужно: {price}₽"}, status=400)
                
                # Confirm handled on frontend
                user.referral_balance -= price
                
                # Add GB cumulatively: старый лимит + докупка
                if user.marzban_username:
                    try:
                        mdata = await marzban_service.get_user(user.marzban_username)
                        if mdata:
                            old_limit_bytes = mdata.get("data_limit") or 0
                            old_limit_gb = old_limit_bytes / (1024**3)
                            new_limit_gb = old_limit_gb + gb
                        else:
                            new_limit_gb = gb
                    except:
                        new_limit_gb = (user.gb_limit or 0) + gb
                else:
                    new_limit_gb = (user.gb_limit or 0) + gb
                user.gb_limit = new_limit_gb
                
                # Update Marzban
                if user.marzban_username:
                    try:
                        await marzban_service.update_user_data_limit(user.marzban_username, new_limit_gb)
                    except Exception as e:
                        logger.error(f"Marzban error traffic topup: {e}")
                
                # Transaction
                import uuid
                from database.models import Transaction
                txn = Transaction(
                    user_id=tg_id, amount=price, currency="RUB",
                    payment_method="referral_balance_traffic", status="paid",
                    payment_id=f"ref_traffic_{uuid.uuid4().hex[:8]}",
                    description=f"Докупка {gb} ГБ из реферального баланса"
                )
                session.add(txn)
                await session.commit()
                
                # Notify user
                try:
                    await self.bot.send_message(tg_id, 
                        f"✅ <b>+{gb} ГБ добавлено!</b>\n"
                        f"Списано {price}₽ с реферального баланса\n"
                        f"Новый лимит: {new_limit_gb:.0f} ГБ",
                        parse_mode="HTML")
                except: pass
                
                # Notify admins
                try:
                    for admin_id in settings.admin_ids_list:
                        await self.bot.send_message(admin_id,
                            f"📦 <b>Докупка трафика (реф баланс)</b>\n"
                            f"ID: <code>{tg_id}</code>\n"
                            f"+{gb} ГБ за {price}₽\n"
                            f"Новый лимит: {new_limit_gb:.0f} ГБ",
                            parse_mode="HTML")
                except: pass
                
                # Referrer bonuses
                try:
                    from services.crypto_webhook import _process_referrer_bonuses
                    async with get_session_factory()() as ref_session:
                        await _process_referrer_bonuses(ref_session, self.bot, user, price, "докупил трафик")
                        await ref_session.commit()
                except Exception as e:
                    logger.error(f"Referrer bonus error (traffic): {e}")
                
                return web.json_response({"status": "success", "gb": gb, "new_limit": new_limit_gb})
        except Exception as e:
            logger.error(f"API Buy Traffic Referral Error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def api_gift_referral(self, request: web.Request) -> web.Response:
        """Подарок из реферального баланса."""
        try:
            data = await request.json()
            tg_id = int(data.get("tg_id"))
            if not self._validate_tg_init_data(request, tg_id):
                return web.json_response({"error": "Unauthorized"}, status=401)
            tier = data.get("tier", "premium")
            days = int(data.get("days", 30))
            amount = float(data.get("amount", 300))
            
            logger.info(f"🎁 Подарок из реф баланса: {tg_id}, {amount}₽, {tier}, {days}дн")
            
            async with get_session_factory()() as session:
                result = await session.execute(select(User).where(User.user_id == tg_id).with_for_update())
                user = result.scalar_one_or_none()
                if not user:
                    return web.json_response({"error": "Пользователь не найден"}, status=404)
                if user.referral_balance < amount:
                    return web.json_response({"error": f"Недостаточно средств. Баланс: {user.referral_balance:.0f}₽"}, status=400)
                
                user.referral_balance -= amount
                
                # Create gift code
                import uuid
                from database.models import Transaction, GiftCode
                code = str(uuid.uuid4())
                gb = 0 if tier == "standard" else {30: 100, 90: 350, 180: 800, 365: 2048}.get(days, days * 3)
                gift = GiftCode(code=code, creator_id=tg_id, tier=tier, days=days, gb_limit=gb,
                    expires_at=datetime.utcnow() + timedelta(days=30))
                session.add(gift)
                
                txn = Transaction(user_id=tg_id, amount=amount, currency="RUB",
                    payment_method="referral_balance_gift", status="paid",
                    payment_id=f"ref_gift_{uuid.uuid4().hex[:8]}",
                    description=f"Подарок из реф баланса ({tier}, {days}дн)")
                session.add(txn)
                await session.commit()
                
                bot_info = await self.bot.get_me()
                gift_link = f"https://t.me/{bot_info.username}?start=gift_{code}"
                
                # Notify user
                try:
                    await self.bot.send_message(tg_id,
                        f"🎁 <b>Подарок оплачен из реферального баланса!</b>\n\n"
                        f"Списано: {amount:.0f}₽\n"
                        f"Ссылка для друга: {gift_link}",
                        parse_mode="HTML")
                except: pass
                
                # Notify admins
                try:
                    for admin_id in settings.admin_ids_list:
                        await self.bot.send_message(admin_id,
                            f"🎁 <b>Подарок (реф баланс)</b>\n"
                            f"ID: <code>{tg_id}</code>\n"
                            f"Тариф: {'VIP' if tier == 'premium' else 'Стандарт'}, {days} дней\n"
                            f"Сумма: {amount:.0f}₽",
                            parse_mode="HTML")
                except: pass
                
                # Referrer bonuses
                try:
                    from services.crypto_webhook import _process_referrer_bonuses
                    async with get_session_factory()() as ref_session:
                        ref_result = await ref_session.execute(select(User).where(User.user_id == tg_id))
                        ref_user = ref_result.scalar_one_or_none()
                        if ref_user:
                            await _process_referrer_bonuses(ref_session, self.bot, ref_user, amount, "купил VPN в подарок")
                            await ref_session.commit()
                except Exception as e:
                    logger.error(f"Referrer bonus error (gift): {e}")
                
                return web.json_response({"status": "success", "gift_link": gift_link, "code": code})
        except Exception as e:
            logger.error(f"API Gift Referral Error: {e}")
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
    app.router.add_post('/api/buy_traffic_referral', handler.api_buy_traffic_referral)
    app.router.add_post('/api/gift_referral', handler.api_gift_referral)
    app.router.add_post('/api/create_gift', handler.api_create_gift)
    app.router.add_post('/api/pay_referral', handler.api_pay_referral)
    app.router.add_post('/api/regenerate_key', handler.api_regenerate_key)
    # ============================================

    runner = web.AppRunner(app)
    await runner.setup()
    
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    
    logger.info("=" * 50)
    logger.info("Вебхук-сервер Nemo VPN запущен (Порт 8080) с поддержкой Mini App API!")
    logger.info("=" * 50)

"""
Сервис для работы с 3x-ui API.
Замена marzban_api.py — работает напрямую с 3x-ui на nemo-entry.

Ключевые отличия от Marzban:
- 3x-ui управляет клиентами через inbound update (нет отдельного client CRUD)
- Один юзер = один UUID, добавляется в оба inbound'а (Standard + БС)
- Трафик считается ОТДЕЛЬНО на каждом inbound'е
- Standard (inbound 1, :8443): безлимит, без totalGB/expiryTime в клиенте
- Premium/БС (inbound 2, :2083): лимит totalGB, expiryTime, limitIp
"""

import asyncio
import httpx
import json
import uuid as uuid_mod
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from loguru import logger
from config import settings


# Inbound IDs на nemo-entry
INBOUND_STANDARD = 1  # port 8443
INBOUND_PREMIUM = 2   # port 2083


class XUIService:
    """Асинхронный клиент для 3x-ui API."""

    def __init__(self):
        self.base_url = settings.XUI_API_URL.rstrip("/")
        if not self.base_url.endswith("/panel/api"):
            self.base_url = f"{self.base_url}/panel/api"

        self._session_cookie: Optional[str] = None
        self._cookie_expires_at: Optional[datetime] = None
        self._client = httpx.AsyncClient(timeout=30.0, verify=False)

    def _get_cookies(self) -> Dict[str, str]:
        """Получить куки для авторизации."""
        if self._session_cookie:
            return {"3x-ui": self._session_cookie}
        return {}

    async def _ensure_login(self) -> None:
        """Проверить/обновить сессию 3x-ui."""
        if self._session_cookie and self._cookie_expires_at:
            if datetime.utcnow() < self._cookie_expires_at:
                return

        login_url = f"{self.base_url.split('/panel/api')[0]}/login"
        data = {
            "username": settings.XUI_USERNAME,
            "password": settings.XUI_PASSWORD,
        }

        try:
            response = await self._client.post(
                login_url, data=data, follow_redirects=True
            )
            response.raise_for_status()

            # Извлечь cookie из заголовка
            set_cookie = response.headers.get("set-cookie", "")
            if "3x-ui=" in set_cookie:
                self._session_cookie = set_cookie.split("3x-ui=")[1].split(";")[0]
                self._cookie_expires_at = datetime.utcnow() + timedelta(hours=23, minutes=59)
                logger.debug("Успешная авторизация в 3x-ui")
            else:
                logger.error("Не удалось получить сессию 3x-ui")
                raise Exception("Не удалось авторизоваться в 3x-ui")
        except httpx.HTTPError as e:
            logger.error(f"Ошибка авторизации 3x-ui: {e}")
            raise Exception(f"Не удалось авторизоваться в 3x-ui: {e}")

    async def _request(
        self,
        method: str,
        endpoint: str,
        json_data: Optional[Dict[str, Any]] = None,
        retry: int = 3,
    ) -> Dict[str, Any]:
        """Выполнить запрос к 3x-ui API с ретраями."""
        url = f"{self.base_url}/{endpoint.strip('/')}"
        cookies = self._get_cookies()

        for attempt in range(retry):
            try:
                response = await self._client.request(
                    method=method, url=url, cookies=cookies,
                    json=json_data, follow_redirects=True,
                )
                if response.status_code == 401 or response.status_code == 302:
                    self._session_cookie = None
                    await self._ensure_login()
                    cookies = self._get_cookies()
                    continue
                response.raise_for_status()
                result = response.json()
                if not result.get("success"):
                    logger.warning(f"3x-ui вернул ошибку: {result.get('msg', '')}")
                return result
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    raise
                logger.warning(f"HTTP ошибка 3x-ui (попытка {attempt + 1}/{retry}): {e}")
                if attempt == retry - 1:
                    raise
                await asyncio.sleep(1 * (attempt + 1))
            except httpx.RequestError as e:
                logger.warning(f"Ошибка запроса 3x-ui (попытка {attempt + 1}/{retry}): {e}")
                if attempt == retry - 1:
                    raise
                await asyncio.sleep(1 * (attempt + 1))
        raise Exception("Исчерпано количество попыток запроса к 3x-ui")

    async def _get_inbound(self, inbound_id: int) -> Dict[str, Any]:
        """Получить полный объект inbound."""
        result = await self._request("GET", f"inbounds/get/{inbound_id}")
        if not result.get("success"):
            raise Exception(f"Не удалось получить inbound {inbound_id}: {result.get('msg')}")
        return result["obj"]

    async def _add_client(self, inbound_id: int, client_data: Dict[str, Any]) -> bool:
        """Добавить клиента через /addClient (безопасно, не ломает inbound)."""
        result = await self._request(
            "POST", "inbounds/addClient",
            json_data={"id": inbound_id, "settings": json.dumps({"clients": [client_data]})},
        )
        success = result.get("success", False)
        if not success:
            logger.error(f"Ошибка addClient inbound {inbound_id}: {result.get('msg')}")
        return success

    async def _del_client(self, inbound_id: int, client_uuid: str) -> bool:
        """Удалить клиента через /{inbound_id}/delClient/{uuid}."""
        result = await self._request(
            "POST", f"inbounds/{inbound_id}/delClient/{client_uuid}"
        )
        success = result.get("success", False)
        if not success:
            logger.warning(f"Ошибка delClient {client_uuid} from inbound {inbound_id}: {result.get('msg')}")
        return success

    async def _update_inbound_safe(self, inbound_id: int, inbound_obj: Dict[str, Any]) -> bool:
        """
        Безопасное обновление inbound — ПРОВЕРЯЕТ критические поля перед отправкой.
        
        ⚠️  3x-ui /update/{id} ОПАСЕН: если отправить неполный объект,
        он ПЕРЕЗАПИШЕТ inbound дефолтами (port=0, enable=false, settings=пусто).
        Этот метод проверяет что port > 0, enable=True, settings непустой.
        """
        # Критические проверки
        port = inbound_obj.get("port", 0)
        enable = inbound_obj.get("enable", False)
        settings_raw = inbound_obj.get("settings", "")
        remark = inbound_obj.get("remark", "")

        if not port or port == 0:
            logger.error(f"БЛОКИРОВКА: попытка обновить inbound {inbound_id} с port={port}!")
            return False
        if not enable:
            logger.error(f"БЛОКИРОВКА: попытка обновить inbound {inbound_id} с enable=False!")
            return False
        if not settings_raw or len(settings_raw) < 10:
            logger.error(f"БЛОКИРОВКА: попытка обновить inbound {inbound_id} с пустым settings!")
            return False
        if not remark:
            logger.error(f"БЛОКИРОВКА: попытка обновить inbound {inbound_id} с пустым remark!")
            return False

        result = await self._request("POST", f"inbounds/update/{inbound_id}", json_data=inbound_obj)
        success = result.get("success", False)
        if not success:
            logger.error(f"Ошибка обновления inbound {inbound_id}: {result.get('msg')}")
        return success

    def _find_client_by_email(self, clients: list, email: str) -> Optional[Dict]:
        """Найти клиента в списке по email."""
        for cl in clients:
            if cl.get("email") == email:
                return cl
        return None

    def _find_client_by_uuid(self, clients: list, client_uuid: str) -> Optional[Dict]:
        """Найти клиента в списке по UUID."""
        for cl in clients:
            if cl.get("id") == client_uuid:
                return cl
        return None

    async def create_user(
        self,
        tg_id: int,
        username: Optional[str] = None,
        expire_days: int = 30,
        expire_hours: Optional[int] = None,
        data_limit_gb: float = 0.0,
        tier: str = "standard",
        device_count: int = 1,
        inbounds: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Создать нового пользователя в 3x-ui (в обоих inbound'ах).

        Одна подписка = два конфига (Standard + БС).
        UUID одинаковый для обоих inbound'ов.

        Возвращает dict с данными созданного клиента.
        """
        await self._ensure_login()

        client_uuid = str(uuid_mod.uuid4())
        client_email = f"tg_{tg_id}"
        # Один subId для обоих inbound'ов (Happ sub-service ищет по subId)
        sub_id = uuid_mod.uuid4().hex[:16]

        # Расчёт expiry
        if expire_hours:
            expire_date = datetime.utcnow() + timedelta(hours=expire_hours)
        else:
            expire_date = datetime.utcnow() + timedelta(days=expire_days)
        expiry_ms = int(expire_date.timestamp() * 1000)

        # data_limit: 0 = безлимит на Standard, ограниченный на Premium
        total_gb_premium = int(data_limit_gb) if data_limit_gb > 0 else 0

        # --- Inbound 1 (Standard: безлимит, без expiry/totalGB в клиенте) ---
        client_std = {
            "id": client_uuid,
            "email": client_email,
            "flow": "xtls-rprx-vision",
            "subId": sub_id,
        }

        # --- Inbound 2 (Premium: лимит, expiry, limitIp) ---
        client_wl = {
            "id": client_uuid,
            "email": f"{client_email}-wl",
            "enable": True,
            "flow": "xtls-rprx-vision",
            "limitIp": device_count,
            "totalGB": total_gb_premium,
            "expiryTime": expiry_ms,
            "subId": sub_id,
        }

        # Добавляем клиентов через безопасный /addClient (НЕ ломает inbound)
        # Если клиент уже существует (Duplicate email) — считаем успехом, не обновляем
        ok1 = await self._add_client(INBOUND_STANDARD, client_std)
        ok2 = await self._add_client(INBOUND_PREMIUM, client_wl)

        # Если addClient не удался из-за дубликата email — клиент уже существует
        if not ok1:
            existing1 = await self._find_client_in_inbound(INBOUND_STANDARD, client_email)
            ok1 = existing1 is not None
            if existing1:
                logger.info(f"Клиент {client_email} уже есть в Standard inbound, пропускаем")

        if not ok2:
            existing2 = await self._find_client_in_inbound(INBOUND_PREMIUM, f"{client_email}-wl")
            ok2 = existing2 is not None
            if existing2:
                logger.info(f"Клиент {client_email}-wl уже есть в Premium inbound, пропускаем")

        if not (ok1 and ok2):
            raise Exception(f"Не удалось создать клиента: standard={ok1}, premium={ok2}")

        logger.info(
            f"Создан пользователь {client_email} "
            f"(UUID: {client_uuid[:8]}..., Тариф: {tier}, "
            f"expiry={expire_date.isoformat()}, ГБ={data_limit_gb}, Устройств: {device_count})"
        )

        # Возвращаем структуру, совместимую с Marzban API
        return {
            "username": client_email,
            "id": client_uuid,
            "status": "active",
            "expire": int(expire_date.timestamp()),
            "data_limit": int(data_limit_gb * 1024**3) if data_limit_gb > 0 else 0,
            "used_traffic": 0,
            "inbounds": {
                "vless": ["vless-reality-standard", "vless-reality-whitelist"],
            },
            "subscription_url": "",
            "links": [],
            "subId": sub_id,
            "subId_wl": sub_id,
        }

    async def get_user(self, client_email: str) -> Optional[Dict[str, Any]]:
        """
        Получить данные пользователя по email.
        Ищет в обоих inbound'ах, объединяет данные.
        """
        await self._ensure_login()

        result_data: Dict[str, Any] = {
            "username": client_email,
            "status": "active",
            "expire": 0,
            "data_limit": 0,
            "used_traffic": 0,
            "inbounds": {"vless": []},
            "subscription_url": "",
            "links": [],
            "id": None,
            "subId": None,
            "subId_wl": None,
        }

        # Inbound 1 (Standard)
        try:
            ib1 = await self._get_inbound(INBOUND_STANDARD)
            settings1 = json.loads(ib1["settings"])
            client_std = self._find_client_by_email(settings1["clients"], client_email)
            if client_std:
                result_data["id"] = client_std.get("id")
                result_data["subId"] = client_std.get("subId")
                result_data["inbounds"]["vless"].append("vless-reality-standard")
        except Exception:
            pass

        # Inbound 2 (Premium)
        try:
            ib2 = await self._get_inbound(INBOUND_PREMIUM)
            settings2 = json.loads(ib2["settings"])
            client_wl = self._find_client_by_email(settings2["clients"], f"{client_email}-wl")
            if client_wl:
                result_data["subId_wl"] = client_wl.get("subId")
                exp_ms = client_wl.get("expiryTime", 0)
                result_data["expire"] = exp_ms // 1000 if exp_ms else 0
                total_gb = client_wl.get("totalGB", 0)
                result_data["data_limit"] = total_gb * 1024**3 if total_gb else 0
                result_data["inbounds"]["vless"].append("vless-reality-whitelist")
                result_data["limitIp"] = client_wl.get("limitIp", 0)
                result_data["enable"] = client_wl.get("enable", True)
        except Exception:
            pass

        # Получаем used_traffic из clientStats (сумма обоих inbound'ов)
        if result_data["id"]:
            try:
                traffic_std = await self._get_client_traffic(INBOUND_STANDARD, client_email)
                traffic_wl = await self._get_client_traffic(INBOUND_PREMIUM, f"{client_email}-wl")
                result_data["used_traffic"] = (traffic_std or 0) + (traffic_wl or 0)
            except Exception:
                pass

        if not result_data["id"]:
            return None

        return result_data

    async def _find_client_in_inbound(self, inbound_id: int, email: str) -> Optional[Dict]:
        """Найти клиента по email в указанном inbound."""
        await self._ensure_login()
        ib = await self._get_inbound(inbound_id)
        settings = json.loads(ib["settings"])
        return self._find_client_by_email(settings.get("clients", []), email)

    async def _get_client_traffic(self, inbound_id: int, email: str) -> int:
        """Получить использованный трафик клиента (up + down) из clientStats."""
        try:
            ib = await self._get_inbound(inbound_id)
            for stat in ib.get("clientStats", []):
                if stat.get("email") == email:
                    return (stat.get("up", 0) or 0) + (stat.get("down", 0) or 0)
        except Exception:
            pass
        return 0

    async def update_user_expiry(
        self,
        client_email: str,
        extra_days: int,
        tier: str = "standard",
        data_limit_gb: float = 0,
        inbounds: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Продлить подписку пользователя.
        Обновляет expiry на Premium inbound'е + добавляет ГБ при продлении.
        """
        await self._ensure_login()

        ib2 = await self._get_inbound(INBOUND_PREMIUM)
        settings2 = json.loads(ib2["settings"])
        client_wl = self._find_client_by_email(settings2["clients"], f"{client_email}-wl")

        if not client_wl:
            raise ValueError(f"Пользователь {client_email} не найден в Premium inbound")

        # Обновляем expiry
        current_expiry_ms = client_wl.get("expiryTime", 0) or 0
        current_time_ms = int(datetime.utcnow().timestamp() * 1000)

        if current_expiry_ms > current_time_ms:
            new_expiry_ms = current_expiry_ms + (extra_days * 24 * 60 * 60 * 1000)
        else:
            new_expiry_ms = current_time_ms + (extra_days * 24 * 60 * 60 * 1000)

        client_wl["expiryTime"] = new_expiry_ms
        client_wl["enable"] = True

        # Добавляем ГБ к текущему лимиту (кумулятивно: использованный + новый)
        if data_limit_gb > 0:
            current_total_gb = client_wl.get("totalGB", 0) or 0
            if current_total_gb > 0:
                used_traffic = await self._get_client_traffic(INBOUND_PREMIUM, f"{client_email}-wl")
                used_gb = (used_traffic or 0) / (1024**3) if used_traffic else 0
                client_wl["totalGB"] = int(used_gb + data_limit_gb)
            else:
                client_wl["totalGB"] = int(data_limit_gb)

        client_wl["updated_at"] = int(datetime.utcnow().timestamp() * 1000)

        ib2["settings"] = json.dumps(settings2)
        ok = await self._update_inbound_safe(INBOUND_PREMIUM, ib2)

        if not ok:
            raise Exception(f"Не удалось продлить подписку {client_email}")

        logger.info(f"Продлена подписка {client_email} на {extra_days} дней (ГБ: {data_limit_gb})")
        return await self.get_user(client_email)

    async def extend_user_expiry_light(self, client_email: str, extra_days: int) -> Dict[str, Any]:
        """Лёгкое продление: обновляет ТОЛЬКО expiry, не трогает трафик."""
        await self._ensure_login()

        ib2 = await self._get_inbound(INBOUND_PREMIUM)
        settings2 = json.loads(ib2["settings"])
        client_wl = self._find_client_by_email(settings2["clients"], f"{client_email}-wl")

        if not client_wl:
            raise ValueError(f"Пользователь {client_email} не найден")

        current_expiry_ms = client_wl.get("expiryTime", 0) or 0
        current_time_ms = int(datetime.utcnow().timestamp() * 1000)

        if current_expiry_ms > current_time_ms:
            new_expiry_ms = current_expiry_ms + (extra_days * 24 * 60 * 60 * 1000)
        else:
            new_expiry_ms = current_time_ms + (extra_days * 24 * 60 * 60 * 1000)

        client_wl["expiryTime"] = new_expiry_ms
        client_wl["updated_at"] = int(datetime.utcnow().timestamp() * 1000)

        ib2["settings"] = json.dumps(settings2)
        await self._update_inbound_safe(INBOUND_PREMIUM, ib2)

        logger.info(f"Лёгкое продление {client_email}: +{extra_days} дней")
        return await self.get_user(client_email)

    async def update_user_ip_limit(self, client_email: str, device_count: int) -> Dict[str, Any]:
        """Обновить лимит устройств на Premium inbound."""
        await self._ensure_login()

        ib2 = await self._get_inbound(INBOUND_PREMIUM)
        settings2 = json.loads(ib2["settings"])
        client_wl = self._find_client_by_email(settings2["clients"], f"{client_email}-wl")

        if not client_wl:
            raise ValueError(f"Пользователь {client_email} не найден")

        client_wl["limitIp"] = device_count
        client_wl["updated_at"] = int(datetime.utcnow().timestamp() * 1000)

        ib2["settings"] = json.dumps(settings2)
        await self._update_inbound_safe(INBOUND_PREMIUM, ib2)

        logger.info(f"Обновлен limitIp для {client_email}: {device_count}")
        return await self.get_user(client_email)

    async def update_user_data_limit(self, client_email: str, data_limit_gb: float) -> Dict[str, Any]:
        """Обновить лимит трафика на Premium inbound (абсолютное значение)."""
        await self._ensure_login()

        ib2 = await self._get_inbound(INBOUND_PREMIUM)
        settings2 = json.loads(ib2["settings"])
        client_wl = self._find_client_by_email(settings2["clients"], f"{client_email}-wl")

        if not client_wl:
            raise ValueError(f"Пользователь {client_email} не найден")

        client_wl["totalGB"] = int(data_limit_gb) if data_limit_gb > 0 else 0
        client_wl["updated_at"] = int(datetime.utcnow().timestamp() * 1000)

        ib2["settings"] = json.dumps(settings2)
        await self._update_inbound_safe(INBOUND_PREMIUM, ib2)

        logger.info(f"Обновлен лимит трафика {client_email}: {data_limit_gb} ГБ")
        return await self.get_user(client_email)

    async def add_traffic(self, client_email: str, extra_gb: float) -> Dict[str, Any]:
        """
        Докупка трафика: прибавляет ГБ к текущему лимиту.
        new_total = used_gb + extra_gb.
        """
        await self._ensure_login()

        ib2 = await self._get_inbound(INBOUND_PREMIUM)
        settings2 = json.loads(ib2["settings"])
        client_wl = self._find_client_by_email(settings2["clients"], f"{client_email}-wl")

        if not client_wl:
            raise ValueError(f"Пользователь {client_email} не найден")

        used_traffic = await self._get_client_traffic(INBOUND_PREMIUM, f"{client_email}-wl")
        used_gb = (used_traffic or 0) / (1024**3) if used_traffic else 0
        client_wl["totalGB"] = int(used_gb + extra_gb)
        client_wl["updated_at"] = int(datetime.utcnow().timestamp() * 1000)

        ib2["settings"] = json.dumps(settings2)
        await self._update_inbound_safe(INBOUND_PREMIUM, ib2)

        logger.info(f"Докупка трафика {client_email}: +{extra_gb} ГБ (итого: {client_wl['totalGB']} ГБ)")
        return await self.get_user(client_email)

    async def update_user_full(
        self,
        client_email: str,
        extra_days: int = 0,
        tier: str = "standard",
        device_count: int = 0,
        data_limit_gb: float = 0,
        inbounds: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Обновить пользователя: срок + тариф + устройства + трафик."""
        await self._ensure_login()

        ib2 = await self._get_inbound(INBOUND_PREMIUM)
        settings2 = json.loads(ib2["settings"])
        client_wl = self._find_client_by_email(settings2["clients"], f"{client_email}-wl")

        if not client_wl:
            raise ValueError(f"Пользователь {client_email} не найден")

        # Обновляем expiry
        if extra_days > 0:
            current_expiry_ms = client_wl.get("expiryTime", 0) or 0
            current_time_ms = int(datetime.utcnow().timestamp() * 1000)
            if current_expiry_ms > current_time_ms:
                new_expiry_ms = current_expiry_ms + (extra_days * 24 * 60 * 60 * 1000)
            else:
                new_expiry_ms = current_time_ms + (extra_days * 24 * 60 * 60 * 1000)
            client_wl["expiryTime"] = new_expiry_ms

        # Обновляем устройства
        if device_count > 0:
            client_wl["limitIp"] = device_count

        # Обновляем лимит трафика (кумулятивно)
        if data_limit_gb > 0:
            used_traffic = await self._get_client_traffic(INBOUND_PREMIUM, f"{client_email}-wl")
            used_gb = (used_traffic or 0) / (1024**3) if used_traffic else 0
            client_wl["totalGB"] = int(used_gb + data_limit_gb)

        client_wl["enable"] = True
        client_wl["updated_at"] = int(datetime.utcnow().timestamp() * 1000)

        ib2["settings"] = json.dumps(settings2)
        await self._update_inbound_safe(INBOUND_PREMIUM, ib2)

        logger.info(
            f"Полное обновление {client_email}: +{extra_days}д, "
            f"ГБ={data_limit_gb}, устр={device_count}"
        )
        return await self.get_user(client_email)

    async def update_user_inbounds(
        self,
        client_email: str,
        active_inbounds: List[str],
    ) -> Dict[str, Any]:
        """Обновить inbound-ы пользователя (включить/выключить конфиг)."""
        await self._ensure_login()

        has_standard = "vless-reality-standard" in active_inbounds
        has_premium = "vless-reality-whitelist" in active_inbounds

        # Находим UUID пользователя
        client_uuid = None
        ib1 = await self._get_inbound(INBOUND_STANDARD)
        settings1 = json.loads(ib1["settings"])
        client_std = self._find_client_by_email(settings1["clients"], client_email)
        if client_std:
            client_uuid = client_std.get("id")
        else:
            ib2 = await self._get_inbound(INBOUND_PREMIUM)
            settings2 = json.loads(ib2["settings"])
            client_wl = self._find_client_by_email(settings2["clients"], f"{client_email}-wl")
            if client_wl:
                client_uuid = client_wl.get("id")

        if not client_uuid:
            raise ValueError(f"Пользователь {client_email} не найден")

        # Управляем Standard inbound
        if not has_standard and client_std:
            # Удаляем из Standard
            settings1["clients"] = [c for c in settings1["clients"] if c.get("id") != client_uuid]
            ib1["settings"] = json.dumps(settings1)
            await self._update_inbound_safe(INBOUND_STANDARD, ib1)
        elif has_standard and not client_std:
            # Добавляем обратно в Standard
            client_new_std = {
                "id": client_uuid,
                "email": client_email,
                "flow": "xtls-rprx-vision",
                "subId": client_wl.get("subId") if client_wl else uuid_mod.uuid4().hex[:16],
                "created_at": int(datetime.utcnow().timestamp() * 1000),
            }
            settings1["clients"].append(client_new_std)
            ib1["settings"] = json.dumps(settings1)
            await self._update_inbound_safe(INBOUND_STANDARD, ib1)

        # Управляем Premium inbound
        ib2 = await self._get_inbound(INBOUND_PREMIUM)
        settings2 = json.loads(ib2["settings"])
        client_wl = self._find_client_by_uuid(settings2["clients"], client_uuid)

        if not has_premium and client_wl:
            # Удаляем из Premium
            settings2["clients"] = [c for c in settings2["clients"] if c.get("id") != client_uuid]
            ib2["settings"] = json.dumps(settings2)
            await self._update_inbound_safe(INBOUND_PREMIUM, ib2)
        elif has_premium and not client_wl:
            # Добавляем в Premium
            client_new_wl = {
                "id": client_uuid,
                "email": f"{client_email}-wl",
                "enable": True,
                "flow": "xtls-rprx-vision",
                "limitIp": 0,
                "totalGB": 0,
                "expiryTime": 0,
                "subId": client_std.get("subId") if client_std else uuid_mod.uuid4().hex[:16],
                "created_at": int(datetime.utcnow().timestamp() * 1000),
                "updated_at": 0,
            }
            settings2["clients"].append(client_new_wl)
            ib2["settings"] = json.dumps(settings2)
            await self._update_inbound_safe(INBOUND_PREMIUM, ib2)

        active = []
        if has_standard:
            active.append("vless-reality-standard")
        if has_premium:
            active.append("vless-reality-whitelist")
        logger.info(f"Обновлены inbound-ы {client_email}: {active}")
        return await self.get_user(client_email)

    async def delete_user(self, client_email: str) -> None:
        """Удалить пользователя из обоих inbound'ов."""
        await self._ensure_login()

        # Находим UUID
        client_uuid = None
        ib1 = await self._get_inbound(INBOUND_STANDARD)
        settings1 = json.loads(ib1["settings"])
        client_std = self._find_client_by_email(settings1["clients"], client_email)
        if client_std:
            client_uuid = client_std.get("id")
            settings1["clients"] = [c for c in settings1["clients"] if c.get("id") != client_uuid]
            ib1["settings"] = json.dumps(settings1)
            await self._update_inbound_safe(INBOUND_STANDARD, ib1)

        # Premium inbound
        ib2 = await self._get_inbound(INBOUND_PREMIUM)
        settings2 = json.loads(ib2["settings"])
        if client_uuid:
            settings2["clients"] = [c for c in settings2["clients"] if c.get("id") != client_uuid]
        else:
            settings2["clients"] = [c for c in settings2["clients"] if c.get("email") != f"{client_email}-wl"]
        ib2["settings"] = json.dumps(settings2)
        await self._update_inbound_safe(INBOUND_PREMIUM, ib2)

        logger.info(f"Удален пользователь {client_email}")

    async def revoke_user_subscription(self, client_email: str) -> Dict[str, Any]:
        """Отозвать подписку: отключить клиента и сгенерировать новый subId."""
        await self._ensure_login()

        new_sub_id = uuid_mod.uuid4().hex[:16]

        # Standard: обновляем subId
        ib1 = await self._get_inbound(INBOUND_STANDARD)
        settings1 = json.loads(ib1["settings"])
        client_std = self._find_client_by_email(settings1["clients"], client_email)
        if client_std:
            client_std["subId"] = new_sub_id
            ib1["settings"] = json.dumps(settings1)
            await self._update_inbound_safe(INBOUND_STANDARD, ib1)

        # Premium: обновляем subId
        ib2 = await self._get_inbound(INBOUND_PREMIUM)
        settings2 = json.loads(ib2["settings"])
        client_wl = self._find_client_by_email(settings2["clients"], f"{client_email}-wl")
        if client_wl:
            client_wl["subId"] = new_sub_id
            ib2["settings"] = json.dumps(settings2)
            await self._update_inbound_safe(INBOUND_PREMIUM, ib2)

        logger.info(f"Отозвана подписка {client_email} (новые subId)")
        return await self.get_user(client_email)

    async def reset_user_traffic(self, client_email: str) -> Dict[str, Any]:
        """Сбросить трафик клиента (сброс счётчиков up/down)."""
        # В 3x-ui v2 нет прямого API для сброса трафика отдельного клиента.
        # Сброс делается через перезапуск Xray или через панель.
        # Для совместимости — просто логируем.
        logger.warning(f"Сброс трафика {client_email}: не поддерживается напрямую в 3x-ui API")
        return await self.get_user(client_email)

    async def get_user_subscription(self, client_email: str) -> str:
        """Получить ссылку на подписку (nemo-sub URL с VLESS + routing)."""
        user = await self.get_user(client_email)
        if not user or not user.get("subId"):
            return ""
        # nemo-sub endpoint: /sub/{subId} — возвращает оба профиля (Standard + Premium) + routing
        return f"https://sub.nemovpn.online/sub/{user['subId']}"

    async def get_user_happ_routing_url(self, client_email: str, profile: str = "standard") -> str:
        """Получить ссылку на Happ routing (для добавления правил маршрутизации)."""
        user = await self.get_user(client_email)
        if not user or not user.get("subId"):
            return ""
        return f"https://sub.nemovpn.online/happ/{profile}"

    async def get_user_vless_link(self, client_email: str) -> str:
        """Получить прямую VLESS-ссылку Standard (для совместимости и QR)."""
        user = await self.get_user(client_email)
        if not user or not user.get("id"):
            return ""
        return (
            f"vless://{user['id']}@{settings.XUI_HOST}:{settings.XUI_PORT_STANDARD}"
            f"?encryption=none&flow=xtls-rprx-vision&security=reality"
            f"&sni={settings.XUI_SNI_STANDARD}&fp=chrome"
            f"&pbk={settings.XUI_PBK_STANDARD}&sid={settings.XUI_SID_STANDARD}"
            f"&type=tcp#NEMO_Standard"
        )

    async def close(self) -> None:
        """Закрыть HTTP-клиент."""
        await self._client.aclose()


# Глобальный экземпляр (заменяет marzban_service)
xui_service = XUIService()

# Обратная совместимость: marzban_service = xui_service
marzban_service = xui_service
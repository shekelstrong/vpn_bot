"""
Сервис для работы с 3x-ui API v3.1.0.
Замена marzban_api.py — работает напрямую с 3x-ui на nemo-entry.

Ключевые отличия от Marzban и от v2.x:
- Bearer token авторизация через заголовок Authorization
- Клиенты хранятся в отдельной таблице clients (через /panel/api/clients/*)
- client_inbounds связывает клиента с inbound'ами
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
import logging as logger
# from loguru import logger  # disabled for system python compat
from config import settings


# Inbound IDs на DE сервере (3x-ui v3.1.0)
INBOUND_STANDARD = 1  # port 443 (VLESS Reality DE)
INBOUND_PREMIUM = 2   # port 9999 (VLESS Reality Chain)


class XUIService:
    """Асинхронный клиент для 3x-ui API v3.1.0."""

    def __init__(self):
        # webBasePath уже включён в URL
        self.base_url = "https://panel.nemovpn.online/LpAp7d5rTkYOZaLipZ/panel/api"
        self._token = "nemo_api_token_2026_v310"
        self._client = httpx.AsyncClient(timeout=30.0, verify=False)

    def _get_headers(self) -> Dict[str, str]:
        """Получить заголовки с Bearer token."""
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _request(
        self,
        method: str,
        endpoint: str,
        json_data: Optional[Dict[str, Any]] = None,
        retry: int = 3,
    ) -> Dict[str, Any]:
        """Выполнить запрос к 3x-ui API с ретраями."""
        url = f"{self.base_url}/{endpoint.strip('/')}"
        headers = self._get_headers()

        for attempt in range(retry):
            try:
                response = await self._client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=json_data,
                    follow_redirects=True,
                )
                if response.status_code == 401:
                    logger.error("3x-ui вернул 401 — проверьте токен")
                    raise Exception("Ошибка авторизации 3x-ui: неверный токен")
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
        """Добавить клиента через /clients/add с привязкой к inbound."""
        # В v3.1.0 clients/add принимает clients + client_inbounds
        payload: Dict[str, Any] = {
            "clients": [client_data],
            "clientInbounds": [{"inboundId": inbound_id}],
        }
        result = await self._request("POST", "clients/add", json_data=payload)
        success = result.get("success", False)
        if not success:
            logger.error(f"Ошибка clients/add для inbound {inbound_id}: {result.get('msg')}")
        return success

    async def _del_client(self, email: str) -> bool:
        """Удалить клиента через /clients/del/{email}."""
        result = await self._request("POST", f"clients/del/{email}")
        success = result.get("success", False)
        if not success:
            logger.warning(f"Ошибка clients/del/{email}: {result.get('msg')}")
        return success

    async def _update_inbound_safe(self, inbound_id: int, inbound_obj: Dict[str, Any]) -> bool:
        """
        Безопасное обновление inbound — ПРОВЕРЯЕТ критические поля перед отправкой.

        ⚠️  3x-ui /update/{id} ОПАСЕН: если отправить неполный объект,
        он ПЕРЕЗАПИШЕТ inbound дефолтами (port=0, enable=false, settings=пусто).
        Этот метод проверяет что port > 0, enable=True, settings непустой.
        """
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
        if not settings_raw or len(str(settings_raw)) < 10:
            logger.error(f"БЛОКИРОВКА: попытка обновить inbound {inbound_id} с пустым settings!")
            return False
        if not remark:
            logger.error(f"БЛОКИРОВКА: попытка обновить inbound {inbound_id} с пустым remark!")
            return False

        result = await self._request("PUT", f"inbounds/update/{inbound_id}", json_data=inbound_obj)
        success = result.get("success", False)
        if not success:
            logger.error(f"Ошибка обновления inbound {inbound_id}: {result.get('msg')}")
        return success

    async def _get_client(self, email: str) -> Optional[Dict[str, Any]]:
        """Получить клиента по email через /clients/get/{email}."""
        try:
            result = await self._request("GET", f"clients/get/{email}")
            if result.get("success"):
                return result.get("obj")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise
        return None

    async def _get_client_list(self) -> List[Dict[str, Any]]:
        """Получить список всех клиентов через /clients/list."""
        result = await self._request("GET", "clients/list")
        if result.get("success"):
            return result.get("obj", [])
        return []

    async def _get_client_by_uuid(self, client_uuid: str) -> Optional[Dict[str, Any]]:
        """Найти клиента по UUID через /clients/list."""
        clients = await self._get_client_list()
        for client in clients:
            if client.get("id") == client_uuid:
                return client
        return None

    async def _get_client_traffic(self, email: str) -> int:
        """Получить использованный трафик клиента (up + down)."""
        client = await self._get_client(email)
        if not client:
            return 0
        up = client.get("up", 0) or 0
        down = client.get("down", 0) or 0
        return up + down

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
        Создать нового пользователя в 3x-ui v3.1.0 (в обоих inbound'ах).

        Одна подписка = два конфига (Standard + БС).
        UUID одинаковый для обоих inbound'ов.

        Возвращает dict с данными созданного клиента.
        """
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

        # Добавляем клиентов через /clients/add (с clientInbounds)
        # Если клиент уже существует (Duplicate email) — считаем успехом, не обновляем
        ok1 = await self._add_client(INBOUND_STANDARD, client_std)
        ok2 = await self._add_client(INBOUND_PREMIUM, client_wl)

        # Если addClient не удался из-за дубликата email — клиент уже существует
        if not ok1:
            existing1 = await self._get_client(client_email)
            ok1 = existing1 is not None
            if existing1:
                logger.info(f"Клиент {client_email} уже есть в Standard inbound, пропускаем")

        if not ok2:
            existing2 = await self._get_client(f"{client_email}-wl")
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
        Ищет через /clients/get/{email}, объединяет данные обоих inbound'ов.
        """
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
            client_std = await self._get_client(client_email)
            if client_std:
                result_data["id"] = client_std.get("id")
                result_data["subId"] = client_std.get("subId")
                result_data["inbounds"]["vless"].append("vless-reality-standard")
        except Exception:
            pass

        # Inbound 2 (Premium)
        try:
            client_wl = await self._get_client(f"{client_email}-wl")
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

        # Получаем used_traffic из client_traffics (сумма обоих inbound'ов)
        if result_data["id"]:
            try:
                traffic_std = await self._get_client_traffic(client_email)
                traffic_wl = await self._get_client_traffic(f"{client_email}-wl")
                result_data["used_traffic"] = (traffic_std or 0) + (traffic_wl or 0)
            except Exception:
                pass

        if not result_data["id"]:
            return None

        return result_data

    async def _find_client_in_inbound(self, inbound_id: int, email: str) -> Optional[Dict]:
        """Найти клиента по email в указанном inbound."""
        client = await self._get_client(email)
        if client:
            # Проверяем связь через client_inbounds (если доступно в объекте)
            client_inbounds = client.get("clientInbounds", [])
            for ci in client_inbounds:
                if ci.get("inboundId") == inbound_id:
                    return client
        return None

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
        Обновляет expiry на Premium клиенте + добавляет ГБ при продлении.
        """
        client_wl = await self._get_client(f"{client_email}-wl")
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
                used_traffic = await self._get_client_traffic(f"{client_email}-wl")
                used_gb = (used_traffic or 0) / (1024**3) if used_traffic else 0
                client_wl["totalGB"] = int(used_gb + data_limit_gb)
            else:
                client_wl["totalGB"] = int(data_limit_gb)

        # Обновляем через clients/add (upsert по uuid/email)
        ok = await self._add_client(INBOUND_PREMIUM, client_wl)
        if not ok:
            raise Exception(f"Не удалось продлить подписку {client_email}")

        logger.info(f"Продлена подписка {client_email} на {extra_days} дней (ГБ: {data_limit_gb})")
        return await self.get_user(client_email)

    async def extend_user_expiry_light(self, client_email: str, extra_days: int) -> Dict[str, Any]:
        """Лёгкое продление: обновляет ТОЛЬКО expiry, не трогает трафик."""
        client_wl = await self._get_client(f"{client_email}-wl")
        if not client_wl:
            raise ValueError(f"Пользователь {client_email} не найден")

        current_expiry_ms = client_wl.get("expiryTime", 0) or 0
        current_time_ms = int(datetime.utcnow().timestamp() * 1000)

        if current_expiry_ms > current_time_ms:
            new_expiry_ms = current_expiry_ms + (extra_days * 24 * 60 * 60 * 1000)
        else:
            new_expiry_ms = current_time_ms + (extra_days * 24 * 60 * 60 * 1000)

        client_wl["expiryTime"] = new_expiry_ms

        ok = await self._add_client(INBOUND_PREMIUM, client_wl)
        if not ok:
            raise Exception(f"Не удалось продлить подписку {client_email}")

        logger.info(f"Лёгкое продление {client_email}: +{extra_days} дней")
        return await self.get_user(client_email)

    async def update_user_ip_limit(self, client_email: str, device_count: int) -> Dict[str, Any]:
        """Обновить лимит устройств на Premium inbound."""
        client_wl = await self._get_client(f"{client_email}-wl")
        if not client_wl:
            raise ValueError(f"Пользователь {client_email} не найден")

        client_wl["limitIp"] = device_count

        ok = await self._add_client(INBOUND_PREMIUM, client_wl)
        if not ok:
            raise Exception(f"Не удалось обновить limitIp {client_email}")

        logger.info(f"Обновлен limitIp для {client_email}: {device_count}")
        return await self.get_user(client_email)

    async def update_user_data_limit(self, client_email: str, data_limit_gb: float) -> Dict[str, Any]:
        """Обновить лимит трафика на Premium inbound (абсолютное значение)."""
        client_wl = await self._get_client(f"{client_email}-wl")
        if not client_wl:
            raise ValueError(f"Пользователь {client_email} не найден")

        client_wl["totalGB"] = int(data_limit_gb) if data_limit_gb > 0 else 0

        ok = await self._add_client(INBOUND_PREMIUM, client_wl)
        if not ok:
            raise Exception(f"Не удалось обновить лимит трафика {client_email}")

        logger.info(f"Обновлен лимит трафика {client_email}: {data_limit_gb} ГБ")
        return await self.get_user(client_email)

    async def add_traffic(self, client_email: str, extra_gb: float) -> Dict[str, Any]:
        """
        Докупка трафика: прибавляет ГБ к текущему лимиту.
        new_total = used_gb + extra_gb.
        """
        client_wl = await self._get_client(f"{client_email}-wl")
        if not client_wl:
            raise ValueError(f"Пользователь {client_email} не найден")

        used_traffic = await self._get_client_traffic(f"{client_email}-wl")
        used_gb = (used_traffic or 0) / (1024**3) if used_traffic else 0
        client_wl["totalGB"] = int(used_gb + extra_gb)

        ok = await self._add_client(INBOUND_PREMIUM, client_wl)
        if not ok:
            raise Exception(f"Не удалось добавить трафик {client_email}")

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
        client_wl = await self._get_client(f"{client_email}-wl")
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
            used_traffic = await self._get_client_traffic(f"{client_email}-wl")
            used_gb = (used_traffic or 0) / (1024**3) if used_traffic else 0
            client_wl["totalGB"] = int(used_gb + data_limit_gb)

        client_wl["enable"] = True

        ok = await self._add_client(INBOUND_PREMIUM, client_wl)
        if not ok:
            raise Exception(f"Не удалось обновить пользователя {client_email}")

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
        has_standard = "vless-reality-standard" in active_inbounds
        has_premium = "vless-reality-whitelist" in active_inbounds

        # Находим UUID пользователя
        client_uuid = None
        client_std = await self._get_client(client_email)
        if client_std:
            client_uuid = client_std.get("id")
        else:
            client_wl = await self._get_client(f"{client_email}-wl")
            if client_wl:
                client_uuid = client_wl.get("id")

        if not client_uuid:
            raise ValueError(f"Пользователь {client_email} не найден")

        # Управляем Standard inbound
        if not has_standard and client_std:
            # Удаляем из Standard
            await self._del_client(client_email)
        elif has_standard and not client_std:
            # Добавляем обратно в Standard
            sub_id = client_wl.get("subId") if client_wl else uuid_mod.uuid4().hex[:16]
            client_new_std = {
                "id": client_uuid,
                "email": client_email,
                "flow": "xtls-rprx-vision",
                "subId": sub_id,
            }
            await self._add_client(INBOUND_STANDARD, client_new_std)

        # Управляем Premium inbound
        client_wl = await self._get_client(f"{client_email}-wl")
        if not has_premium and client_wl:
            # Удаляем из Premium
            await self._del_client(f"{client_email}-wl")
        elif has_premium and not client_wl:
            # Добавляем в Premium
            sub_id = client_std.get("subId") if client_std else uuid_mod.uuid4().hex[:16]
            client_new_wl = {
                "id": client_uuid,
                "email": f"{client_email}-wl",
                "enable": True,
                "flow": "xtls-rprx-vision",
                "limitIp": 0,
                "totalGB": 0,
                "expiryTime": 0,
                "subId": sub_id,
            }
            await self._add_client(INBOUND_PREMIUM, client_new_wl)

        active = []
        if has_standard:
            active.append("vless-reality-standard")
        if has_premium:
            active.append("vless-reality-whitelist")
        logger.info(f"Обновлены inbound-ы {client_email}: {active}")
        return await self.get_user(client_email)

    async def delete_user(self, client_email: str) -> None:
        """Удалить пользователя из обоих inbound'ов."""
        await self._del_client(client_email)
        await self._del_client(f"{client_email}-wl")
        logger.info(f"Удален пользователь {client_email}")

    async def revoke_user_subscription(self, client_email: str) -> Dict[str, Any]:
        """Отозвать подписку: отключить клиента и сгенерировать новый subId."""
        new_sub_id = uuid_mod.uuid4().hex[:16]

        # Standard: обновляем subId
        client_std = await self._get_client(client_email)
        if client_std:
            client_std["subId"] = new_sub_id
            await self._add_client(INBOUND_STANDARD, client_std)

        # Premium: обновляем subId
        client_wl = await self._get_client(f"{client_email}-wl")
        if client_wl:
            client_wl["subId"] = new_sub_id
            await self._add_client(INBOUND_PREMIUM, client_wl)

        logger.info(f"Отозвана подписка {client_email} (новые subId)")
        return await self.get_user(client_email)

    async def reset_user_traffic(self, client_email: str) -> Dict[str, Any]:
        """Сбросить трафик клиента (сброс счётчиков up/down)."""
        # В 3x-ui v3.1.0 нет прямого API для сброса трафика отдельного клиента.
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

    async def get_user(self, client_email: str) -> Optional[Dict[str, Any]]:
        """
        Получить данные пользователя по email.
        Ищет в обоих inbound'ах, объединяет данные.
        """
        await self.login()

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

"""
Сервис для работы с Marzban API.

ИЗМЕНЕНИЯ:
1. create_user — поддерживает список inbounds (для одновременной покупки двух тарифов)
2. update_user_inbounds — новый метод для обновления списка активных inbound-ов
3. generate_vless_link — оставлен для совместимости
4. get_user_subscription / get_user_vless_link — без изменений
"""

import asyncio
import httpx
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from loguru import logger
from config import settings


class MarzbanService:
    def __init__(self):
        base = settings.marzban_api_url.rstrip('/')
        if not base.endswith('/api'):
            self.base_url = f"{base}/api"
        else:
            self.base_url = base

        self._token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None
        self._client = httpx.AsyncClient(timeout=30.0, verify=False)
        
        self.vless_config = {
            "port": settings.VLESS_PORT,
            "sni": settings.VLESS_SNI,
            "public_key": settings.VLESS_PUBLIC_KEY,
            "short_id": settings.VLESS_SHORT_ID,
            "fingerprint": settings.VLESS_FINGERPRINT,
        }

    async def _get_headers(self) -> Dict[str, str]:
        token = await self.get_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def get_token(self) -> str:
        if self._token and self._token_expires_at:
            if datetime.utcnow() < self._token_expires_at:
                return self._token

        url = f"{self.base_url}/admin/token"
        data = {
            "username": settings.MARZBAN_ADMIN_USERNAME,
            "password": settings.MARZBAN_ADMIN_PASSWORD,
        }
        
        try:
            response = await self._client.post(url, data=data)
            response.raise_for_status()
            result = response.json()
            self._token = result["access_token"]
            self._token_expires_at = datetime.utcnow() + timedelta(hours=23, minutes=59)
            return self._token
        except httpx.HTTPError as e:
            logger.error(f"Ошибка получения токена Marzban: {e}")
            raise Exception(f"Не удалось получить токен Marzban: {e}")

    async def _request(
        self,
        method: str,
        endpoint: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        retry: int = 3
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/{endpoint.strip('/')}"
        headers = await self._get_headers()

        for attempt in range(retry):
            try:
                response = await self._client.request(
                    method=method, url=url, headers=headers,
                    json=json, params=params,
                )
                if response.status_code == 401:
                    self._token = None
                    headers = await self._get_headers()
                    continue
                response.raise_for_status()
                if response.status_code == 204:
                    return {}
                return response.json()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    raise
                logger.warning(f"HTTP ошибка (попытка {attempt + 1}/{retry}): {e}")
                if attempt == retry - 1:
                    raise
                await asyncio.sleep(1 * (attempt + 1))
            except httpx.RequestError as e:
                logger.warning(f"Ошибка запроса (попытка {attempt + 1}/{retry}): {e}")
                if attempt == retry - 1:
                    raise
                await asyncio.sleep(1 * (attempt + 1))
        raise Exception("Исчерпано количество попыток запроса")

    async def create_user(
        self,
        tg_id: int,
        username: Optional[str] = None,
        expire_days: int = 30,
        expire_hours: Optional[int] = None,
        data_limit_gb: float = 0.0,
        tier: str = "standard",
        device_count: int = 1,
        inbounds: Optional[List[str]] = None  # НОВОЕ: кастомный список inbound-ов
    ) -> Dict[str, Any]:
        """Создать нового пользователя в Marzban."""
        marzban_username = f"user_{tg_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        
        if expire_hours:
            expire_date = datetime.utcnow() + timedelta(hours=expire_hours)
        else:
            expire_date = datetime.utcnow() + timedelta(days=expire_days)

        # Если передан кастомный список inbounds — используем его
        if inbounds:
            proxy_flow = "xtls-rprx-vision" if "vless-reality-whitelist" in inbounds else ""
            proxies = {"vless": {"flow": proxy_flow}}
            inbound_list = {"vless": inbounds}
        elif tier == "premium":
            proxies = {"vless": {"flow": "xtls-rprx-vision"}}
            inbound_list = {"vless": ["vless-reality-whitelist"]}
        else:
            proxies = {"vless": {"flow": ""}}
            inbound_list = {"vless": ["vless-reality-standard"]}

        data_limit_bytes = int(data_limit_gb * 1024 ** 3) if data_limit_gb > 0 else 0
        
        user_data = {
            "username": marzban_username,
            "proxies": proxies,
            "inbounds": inbound_list,
            "expire": int(expire_date.timestamp()),
            "data_limit": data_limit_bytes if data_limit_bytes > 0 else None,
            "status": "active",
            "ip_limit": device_count
        }

        try:
            result = await self._request("POST", "/user", json=user_data)
            logger.info(f"Создан пользователь {marzban_username} (Тариф: {tier}, Inbounds: {inbound_list}, Устройств: {device_count})")
            return result
        except Exception as e:
            logger.error(f"Ошибка создания пользователя {marzban_username}: {e}")
            raise

    async def get_user(self, marzban_username: str) -> Optional[Dict[str, Any]]:
        try:
            result = await self._request("GET", f"/user/{marzban_username}")
            return result
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise
        except Exception as e:
            logger.error(f"Ошибка получения пользователя {marzban_username}: {e}")
            raise

    async def reset_user_traffic(self, marzban_username: str) -> Dict[str, Any]:
        try:
            result = await self._request("POST", f"/user/{marzban_username}/reset")
            return result
        except Exception as e:
            logger.error(f"Ошибка сброса трафика {marzban_username}: {e}")
            raise

    async def update_user_expiry(
        self,
        marzban_username: str,
        extra_days: int,
        tier: str = "standard",
        data_limit_gb: float = 0,
        inbounds: Optional[List[str]] = None  # НОВОЕ
    ) -> Dict[str, Any]:
        """Продлить подписку пользователя."""
        user = await self.get_user(marzban_username)
        if not user:
            raise ValueError(f"Пользователь {marzban_username} не найден")
            
        current_expire = user.get("expire") or 0
        current_time = int(datetime.utcnow().timestamp())
        
        if current_expire > current_time:
            new_expire = current_expire + (extra_days * 24 * 60 * 60)
        else:
            new_expire = current_time + (extra_days * 24 * 60 * 60)

        # Inbounds: кастомные или по тарифу
        if inbounds:
            proxy_flow = "xtls-rprx-vision" if "vless-reality-whitelist" in inbounds else ""
            proxies = {"vless": {"flow": proxy_flow}}
            inbound_list = {"vless": inbounds}
        elif tier == "premium":
            proxies = {"vless": {"flow": "xtls-rprx-vision"}}
            inbound_list = {"vless": ["vless-reality-whitelist"]}
        else:
            proxies = {"vless": {"flow": ""}}
            inbound_list = {"vless": ["vless-reality-standard"]}
        
        current_used = user.get("used_traffic", 0) or 0
        if current_used is None: current_used = 0

        update_data = {
            "expire": new_expire,
            "status": "active",
            "proxies": proxies,
            "inbounds": inbound_list
        }

        if data_limit_gb > 0:
            # Добавляем ГБ поверх использованного трафика
            new_data_limit = int(current_used + data_limit_gb * 1024 ** 3)
            update_data["data_limit"] = new_data_limit
            try:
                await self.reset_user_traffic(marzban_username)
            except:
                pass
        # Если data_limit_gb == 0 — НЕ трогаем data_limit и НЕ сбрасываем трафик

        try:
            result = await self._request("PUT", f"/user/{marzban_username}", json=update_data)
            logger.info(f"Продлена подписка {marzban_username} на {extra_days} дней (Тариф: {tier})")
            return result
        except Exception as e:
            logger.error(f"Ошибка продления подписки {marzban_username}: {e}")
            raise

    async def extend_user_expiry_light(self, marzban_username: str, extra_days: int) -> Dict[str, Any]:
        """Лёгкое продление: обновляет ТОЛЬКО expire."""
        user = await self.get_user(marzban_username)
        if not user:
            raise ValueError(f"Пользователь {marzban_username} не найден")
        current_expire = user.get("expire") or 0
        current_time = int(datetime.utcnow().timestamp())
        if current_expire > current_time:
            new_expire = current_expire + (extra_days * 24 * 60 * 60)
        else:
            new_expire = current_time + (extra_days * 24 * 60 * 60)
        update_data = {"expire": new_expire}
        try:
            result = await self._request("PUT", f"/user/{marzban_username}", json=update_data)
            logger.info(f"Лёгкое продление {marzban_username}: +{extra_days} дней")
            return result
        except Exception as e:
            logger.error(f"Ошибка лёгкого продления {marzban_username}: {e}")
            raise

    async def update_user_ip_limit(self, marzban_username: str, device_count: int) -> Dict[str, Any]:
        update_data = {"ip_limit": device_count}
        try:
            result = await self._request("PUT", f"/user/{marzban_username}", json=update_data)
            logger.info(f"Синхронизирован ip_limit для {marzban_username}: {device_count}")
            return result
        except Exception as e:
            logger.error(f"Ошибка обновления ip_limit {marzban_username}: {e}")
            raise

    async def update_user_data_limit(self, marzban_username: str, data_limit_gb: float) -> Dict[str, Any]:
        data_limit_bytes = int(data_limit_gb * 1024 ** 3) if data_limit_gb > 0 else None
        update_data = {"data_limit": data_limit_bytes}
        try:
            result = await self._request("PUT", f"/user/{marzban_username}", json=update_data)
            logger.info(f"Обновлен лимит трафика {marzban_username}: {data_limit_gb} GB")
            return result
        except Exception as e:
            logger.error(f"Ошибка обновления лимита {marzban_username}: {e}")
            raise

    async def update_user_full(
        self,
        marzban_username: str,
        extra_days: int = 0,
        tier: str = "standard",
        device_count: int = 0,
        data_limit_gb: float = 0,
        inbounds: Optional[List[str]] = None  # НОВОЕ
    ) -> Dict[str, Any]:
        """Обновить пользователя: срок + тариф + устройства + трафик."""
        user = await self.get_user(marzban_username)
        if not user:
            raise ValueError(f"Пользователь {marzban_username} не найден")

        current_expire = user.get("expire") or 0
        current_time = int(datetime.utcnow().timestamp())
        if extra_days > 0:
            if current_expire > current_time:
                new_expire = current_expire + (extra_days * 24 * 60 * 60)
            else:
                new_expire = current_time + (extra_days * 24 * 60 * 60)
        else:
            new_expire = current_expire

        # Inbounds — сохраняем существующие + добавляем новый tier
        current_inbounds = user.get("inbounds", {}).get("vless", [])

        if inbounds:
            # Явно переданные inbounds (админ/特殊 случаи)
            proxy_flow = "xtls-rprx-vision" if "vless-reality-whitelist" in inbounds else ""
            proxies = {"vless": {"flow": proxy_flow}}
            inbound_list = {"vless": inbounds}
        elif tier == "premium":
            proxies = {"vless": {"flow": "xtls-rprx-vision"}}
            # VIP всегда включает оба inbound-а
            inbound_list = {"vless": ["vless-reality-whitelist", "vless-reality-standard"]}
        else:
            # Standard — ДОБАВИТЬ к существующим, не удалять premium
            merged = set(current_inbounds)
            merged.add("vless-reality-standard")
            has_whitelist = "vless-reality-whitelist" in merged
            proxy_flow = "xtls-rprx-vision" if has_whitelist else ""
            proxies = {"vless": {"flow": proxy_flow}}
            inbound_list = {"vless": list(merged)}

        current_data_limit = user.get("data_limit") or 0
        current_used = user.get("used_traffic") or 0

        # Защита от None — Marzban может вернуть None
        if current_data_limit is None: current_data_limit = 0
        if current_used is None: current_used = 0

        if data_limit_gb > 0:
            new_data_limit_bytes = int(current_used + data_limit_gb * 1024 ** 3)
        else:
            new_data_limit_bytes = current_data_limit if current_data_limit > 0 else None

        update_data = {
            "expire": new_expire,
            "status": "active",
            "proxies": proxies,
            "inbounds": inbound_list,
        }
        if device_count > 0:
            update_data["ip_limit"] = device_count
        if new_data_limit_bytes is not None:
            update_data["data_limit"] = new_data_limit_bytes

        try:
            result = await self._request("PUT", f"/user/{marzban_username}", json=update_data)
            logger.info(f"Полное обновление {marzban_username}: +{extra_days}д, inbounds={inbound_list}, {device_count} устр.")
            return result
        except Exception as e:
            logger.error(f"Ошибка полного обновления {marzban_username}: {e}")
            raise

    async def update_user_inbounds(
        self,
        marzban_username: str,
        active_inbounds: List[str]
    ) -> Dict[str, Any]:
        """НОВОЕ: Обновить только inbound-ы пользователя.
        Используется scheduler'ом при истечении одного из тарифов."""
        proxy_flow = "xtls-rprx-vision" if "vless-reality-whitelist" in active_inbounds else ""
        update_data = {
            "inbounds": {"vless": active_inbounds},
            "proxies": {"vless": {"flow": proxy_flow}},
            "status": "active",
        }
        try:
            result = await self._request("PUT", f"/user/{marzban_username}", json=update_data)
            logger.info(f"Обновлены inbound-ы {marzban_username}: {active_inbounds}")
            return result
        except Exception as e:
            logger.error(f"Ошибка обновления inbound-ов {marzban_username}: {e}")
            raise

    async def delete_user(self, marzban_username: str) -> None:
        try:
            await self._request("DELETE", f"/user/{marzban_username}")
            logger.info(f"Удален пользователь {marzban_username}")
        except Exception as e:
            logger.error(f"Ошибка удаления {marzban_username}: {e}")
            raise

    async def revoke_user_subscription(self, marzban_username: str) -> Dict[str, Any]:
        try:
            result = await self._request("POST", f"/user/{marzban_username}/revoke-subscription")
            logger.info(f"Отозвана подписка {marzban_username}")
            return result
        except Exception as e:
            logger.error(f"Ошибка отзыва подписки {marzban_username}: {e}")
            raise

    def generate_vless_link(self, marzban_username: str, subscription_url: str) -> str:
        config = self.vless_config
        return (
            f"vless://{marzban_username}@{settings.MARZBAN_URL.replace('https://', '')}:{config['port']}"
            f"?encryption=none&security=reality&sni={config['sni']}"
            f"&fp={config['fingerprint']}&pbk={config['public_key']}"
            f"&sid={config['short_id']}&type=tcp&headerType=none"
            f"#{marzban_username}"
        )

    async def get_user_subscription(self, marzban_username: str) -> str:
        user = await self.get_user(marzban_username)
        if not user:
            return ""
        sub_url = user.get("subscription_url", "")
        if sub_url and sub_url.startswith("/"):
            base_url = settings.MARZBAN_URL.rstrip("/")
            return f"{base_url}{sub_url}"
        return sub_url

    async def get_user_vless_link(self, marzban_username: str) -> str:
        user = await self.get_user(marzban_username)
        if not user:
            return ""
        links = user.get("links", [])
        return links[0] if links else ""

    async def close(self):
        await self._client.aclose()


marzban_service = MarzbanService()

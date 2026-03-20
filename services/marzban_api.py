import asyncio
import httpx
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from loguru import logger
from config import settings

class MarzbanService:
    """
    Асинхронный сервис для взаимодействия с Marzban API.
    """

    def __init__(self):
        self.base_url = settings.marzban_api_url
        self._token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None
        
        # ИСПРАВЛЕНИЕ: verify=False позволяет локально игнорировать строгие проверки SSL сертификатов на macOS
        self._client = httpx.AsyncClient(timeout=30.0, verify=False)
        
        # VLESS Reality настройки
        self.vless_config = {
            "port": settings.VLESS_PORT,
            "sni": settings.VLESS_SNI,
            "public_key": settings.VLESS_PUBLIC_KEY,
            "short_id": settings.VLESS_SHORT_ID,
            "fingerprint": settings.VLESS_FINGERPRINT,
        }

    async def _get_headers(self) -> Dict[str, str]:
        """Получить заголовки с токеном авторизации."""
        token = await self.get_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def get_token(self) -> str:
        """Получить токен доступа к API."""
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
            logger.info("Получен новый токен Marzban API")
            return self._token
        except httpx.HTTPError as e:
            logger.error(f"Ошибка получения токена Marzban: {e}")
            if hasattr(e, 'response') and e.response:
                logger.error(f"Ответ сервера: {e.response.text}")
            raise Exception(f"Не удалось получить токен Marzban: {e}")

    async def _request(
        self,
        method: str,
        endpoint: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        retry: int = 3
    ) -> Dict[str, Any]:
        """Выполнить HTTP запрос к API с механизмом повторных попыток."""
        url = f"{self.base_url}/{endpoint.strip('/')}"
        headers = await self._get_headers()

        for attempt in range(retry):
            try:
                response = await self._client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=json,
                    params=params,
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
                # ИСПРАВЛЕНИЕ: Не делаем ретраи для 404 ошибки (пользователя нет)
                if e.response.status_code == 404:
                    raise

                logger.warning(f"HTTP ошибка (попытка {attempt + 1}/{retry}): {e}")
                if attempt == retry - 1:
                    logger.error(f"Ответ сервера: {e.response.text if hasattr(e, 'response') and e.response else 'N/A'}")
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
        data_limit_gb: float = 0.0
    ) -> Dict[str, Any]:
        """Создать нового пользователя в Marzban."""
        marzban_username = f"user_{tg_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        if expire_hours:
            expire_date = datetime.utcnow() + timedelta(hours=expire_hours)
        else:
            expire_date = datetime.utcnow() + timedelta(days=expire_days)
        
        proxies = {
            "vless": {
                "flow": ""
            }
        }
        inbounds = {
            "vless": ["vless-reality"]
        }
        
        data_limit_bytes = int(data_limit_gb * 1024 * 1024 * 1024) if data_limit_gb > 0 else 0
        
        user_data = {
            "username": marzban_username,
            "proxies": proxies,
            "inbounds": inbounds,
            "expire": int(expire_date.timestamp()),
            "data_limit": data_limit_bytes if data_limit_bytes > 0 else None,
            "status": "active",
        }
        
        try:
            result = await self._request("POST", "/user", json=user_data)
            logger.info(f"Создан пользователь {marzban_username} для TG {tg_id}")
            return result
        except Exception as e:
            logger.error(f"Ошибка создания пользователя {marzban_username}: {e}")
            raise

    async def get_user(self, marzban_username: str) -> Optional[Dict[str, Any]]:
        """Получить информацию о пользователе."""
        try:
            result = await self._request("GET", f"/user/{marzban_username}")
            return result
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            logger.error(f"Ошибка получения пользователя {marzban_username}: {e}")
            raise
        except Exception as e:
            logger.error(f"Ошибка получения пользователя {marzban_username}: {e}")
            raise

    async def reset_user_traffic(self, marzban_username: str) -> Dict[str, Any]:
        """Сбросить трафик пользователя."""
        try:
            result = await self._request("POST", f"/user/{marzban_username}/reset")
            logger.info(f"Сброшен трафик пользователя {marzban_username}")
            return result
        except Exception as e:
            logger.error(f"Ошибка сброса трафика {marzban_username}: {e}")
            raise

    async def update_user_expiry(
        self,
        marzban_username: str,
        extra_days: int
    ) -> Dict[str, Any]:
        """Продлить подписку пользователя и снять ограничения триала."""
        user = await self.get_user(marzban_username)
        
        if not user:
            raise ValueError(f"Пользователь {marzban_username} не найден в Marzban для продления")
            
        current_expire = user.get("expire") or 0
        current_time = int(datetime.utcnow().timestamp())
        
        # Если подписка еще активна, плюсуем к ней. Если уже истекла - отсчитываем от сейчас!
        if current_expire > current_time:
            new_expire = current_expire + (extra_days * 24 * 60 * 60)
        else:
            new_expire = current_time + (extra_days * 24 * 60 * 60)
            
        update_data = {
            "expire": new_expire,
            "data_limit": 0, # Снимаем триальный лимит по трафику (устанавливаем безлимит)
            "status": "active" # Принудительно активируем аккаунт, если он был отключен
        }
        
        try:
            result = await self._request("PUT", f"/user/{marzban_username}", json=update_data)
            
            # Сбрасываем счетчик скачанного триального трафика
            try:
                await self.reset_user_traffic(marzban_username)
            except Exception:
                pass
                
            logger.info(f"Продлена подписка {marzban_username} на {extra_days} дней (установлен безлимит)")
            return result
        except Exception as e:
            logger.error(f"Ошибка продления подписки {marzban_username}: {e}")
            raise

    async def update_user_data_limit(
        self,
        marzban_username: str,
        data_limit_gb: float
    ) -> Dict[str, Any]:
        """Обновить лимит трафика пользователя."""
        data_limit_bytes = int(data_limit_gb * 1024 * 1024 * 1024) if data_limit_gb > 0 else None
        update_data = {
            "data_limit": data_limit_bytes,
        }
        try:
            result = await self._request("PUT", f"/user/{marzban_username}", json=update_data)
            logger.info(f"Обновлен лимит трафика {marzban_username}: {data_limit_gb} GB")
            return result
        except Exception as e:
            logger.error(f"Ошибка обновления лимита трафика {marzban_username}: {e}")
            raise

    async def delete_user(self, marzban_username: str) -> None:
        """Удалить пользователя."""
        try:
            await self._request("DELETE", f"/user/{marzban_username}")
            logger.info(f"Удален пользователь {marzban_username}")
        except Exception as e:
            logger.error(f"Ошибка удаления пользователя {marzban_username}: {e}")
            raise

    async def revoke_user_subscription(self, marzban_username: str) -> Dict[str, Any]:
        """Отозвать подписку пользователя (сгенерировать новую)."""
        try:
            result = await self._request("POST", f"/user/{marzban_username}/revoke-subscription")
            logger.info(f"Отозвана подписка {marzban_username}")
            return result
        except Exception as e:
            logger.error(f"Ошибка отзыва подписки {marzban_username}: {e}")
            raise

    def generate_vless_link(
        self,
        marzban_username: str,
        subscription_url: str
    ) -> str:
        """Сгенерировать VLESS ссылку для пользователя."""
        config = self.vless_config
        uuid = marzban_username
        vless_link = (
            f"vless://{uuid}@{settings.MARZBAN_URL.replace('https://', '')}:{config['port']}"
            f"?encryption=none&security=reality&sni={config['sni']}"
            f"&fp={config['fingerprint']}&pbk={config['public_key']}"
            f"&sid={config['short_id']}&type=tcp&headerType=none"
            f"#{marzban_username}"
        )
        return vless_link

    async def get_user_subscription(self, marzban_username: str) -> str:
        """Получить URL подписки пользователя."""
        user = await self.get_user(marzban_username)
        if not user:
            return ""
        return user.get("subscription_url", "")

    async def close(self):
        """Закрыть HTTP клиент."""
        await self._client.aclose()


# Глобальный экземпляр сервиса
marzban_service = MarzbanService()
"""
Сервис для работы с CryptoBot (@CryptoPay).
Асинхронный клиент для создания и проверки платежей.
"""

import httpx
import hashlib
import hmac
import json
import asyncio
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from loguru import logger

from config import settings


class CryptoBotService:
    """
    Асинхронный сервис для взаимодействия с CryptoBot API.
   
    Документация: https://help.cryptobot.app/
   
    Методы:
        create_invoice: Создать счет на оплату.
        get_invoice: Получить информацию о счете.
        get_balance: Получить баланс бота.
        check_invoice_status: Проверить статус счета.
    """
   
    def __init__(self):
        self.base_url = "https://pay.crypt.bot/api"
        self.token = settings.CRYPTO_BOT_TOKEN
       
        # Берем прокси из окружения, если он есть, для обхода блокировок
        proxy = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
        
        # Увеличен таймаут и отключена строгая проверка сертификатов
        self._client = httpx.AsyncClient(
            timeout=60.0, 
            verify=False,
            proxy=proxy
        )
       
        if self.token:
            safe_token = f"{self.token[:4]}...{self.token[-4:]}" if len(self.token) > 8 else "***"
            logger.info(f"CryptoBot токен: {safe_token} (длина: {len(self.token)})")
            logger.info(f"CryptoBot URL: {self.base_url}")
            if proxy:
                logger.info(f"CryptoBot использует прокси: {proxy}")
        else:
            logger.error("❌ CRYPTO_BOT_TOKEN не задан в настройках!")
   
    async def _get_headers(self) -> Dict[str, str]:
        """Получить заголовки с токеном авторизации."""
        return {
            "Crypto-Pay-API-Token": self.token,
            "Content-Type": "application/json",
        }
   
    async def _request(
        self,
        method: str,
        endpoint: str,
        json_data: Optional[Dict[str, Any]] = None,
        retry: int = 3
    ) -> Dict[str, Any]:
        """
        Выполнить HTTP запрос к API с системой повторных попыток.
        """
        if not self.token or self.token == "your_crypto_bot_token_here":
            logger.error("❌ CRYPTO_BOT_TOKEN не задан или равен placeholder!")
            raise Exception("CRYPTO_BOT_TOKEN не настроен.")
       
        url = f"{self.base_url}/{endpoint}"
        headers = await self._get_headers()
       
        safe_json = json_data.copy() if json_data else {}
        safe_json.pop('payload', None)
       
        logger.debug(f"CryptoBot запрос: {method} {url}")
        logger.debug(f"JSON данные: {safe_json}")
       
        for attempt in range(retry):
            try:
                response = await self._client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=json_data,
                )
               
                response.raise_for_status()
                result = response.json()
               
                if not result.get("ok"):
                    error_msg = result.get('error', 'Unknown error')
                    logger.error(f"CryptoBot API error: {error_msg}")
                    raise Exception(f"CryptoBot API error: {error_msg}")
               
                return result
               
            except httpx.HTTPError as e:
                logger.warning(f"Попытка {attempt + 1}/{retry} не удалась. HTTPError: {type(e).__name__} - {e}")
                if attempt == retry - 1:
                    logger.error(f"❌ Исчерпаны попытки запроса к CryptoBot ({method} {endpoint})")
                    if hasattr(e, 'response') and e.response:
                        try:
                            logger.error(f"Текст ответа: {e.response.text}")
                        except:
                            pass
                    raise
                await asyncio.sleep(2 * (attempt + 1))  # Прогрессивная задержка
                
            except Exception as e:
                logger.warning(f"Попытка {attempt + 1}/{retry} не удалась. Ошибка: {e}")
                if attempt == retry - 1:
                    raise
                await asyncio.sleep(2 * (attempt + 1))
   
    async def create_invoice(
        self,
        amount_usdt: float,
        order_id: int,
        description: Optional[str] = None,
        paid_btn_name: Optional[str] = None,
        paid_btn_url: Optional[str] = None,
    ) -> Optional[str]:
        """
        Создать счет на оплату.
        """
        headers = {
            "Crypto-Pay-API-Token": self.token,
            "Content-Type": "application/json"
        }
       
        payload = {
            "asset": "USDT",
            "amount": str(amount_usdt),
            "description": description or f"Order #{order_id}",
            "hidden_message": "Спасибо за оплату!",
            "payload": str(order_id),
            "allow_comments": False,
            "allow_anonymous": True,
            "expires_in": 3600
        }
       
        logger.info(f"📤 CryptoBot Request: amount={amount_usdt}, order={order_id}")
       
        try:
            # Здесь тоже используем встроенный клиент, чтобы применялся таймаут и прокси
            response = await self._client.post(
                f"{self.base_url}/createInvoice",
                json=payload,
                headers=headers
            )
            result = response.json()
           
            if result.get("ok"):
                link = result["result"]["pay_url"]
                logger.info(f"✅ CryptoBot Invoice Created: {link}")
                return link
            else:
                logger.error(f"❌ CryptoBot API Error: {result}")
                return None
        except Exception as e:
            logger.error(f"❌ CryptoBot Connection Error при создании счета: {e}")
            return None
   
    async def get_invoice(self, invoice_id: int) -> Dict[str, Any]:
        """
        Получить информацию о счете.
        """
        data = {"invoice_id": invoice_id}
        try:
            result = await self._request("POST", "getInvoice", json_data=data)
            return result.get("result", {})
        except Exception as e:
            logger.error(f"Ошибка получения счета {invoice_id}: {e}")
            raise
   
    async def get_balance(self) -> Dict[str, Any]:
        """
        Получить баланс бота.
        """
        try:
            result = await self._request("POST", "getBalance")
            return result.get("result", {})
        except Exception as e:
            logger.error(f"Ошибка получения баланса: {e}")
            raise
   
    async def check_invoice_status(self, invoice_id: int) -> str:
        """
        Проверить статус счета.
        """
        try:
            invoice = await self.get_invoice(invoice_id)
            return invoice.get("status", "unknown")
        except Exception as e:
            logger.error(f"Не удалось проверить статус счета {invoice_id}: {e}")
            return "unknown"
   
    async def close(self):
        """Закрыть HTTP клиент."""
        await self._client.aclose()
   
    async def get_webhook_info(self) -> Optional[Dict[str, Any]]:
        """
        Получить информацию о текущем вебхуке.
        """
        try:
            result = await self._request("POST", "getWebhookInfo")
            webhook_url = result.get("result", {}).get("url")
            logger.info(f"Текущий URL вебхука: {webhook_url}")
            return result
        except Exception as e:
            logger.warning(f"Не удалось получить информацию о вебхуке (возможно, проблема со связью): {e}")
            return None
   
    async def set_webhook(self, webhook_url: str) -> Optional[Dict[str, Any]]:
        """
        Установить URL вебхука для получения уведомлений.
        """
        data = {
            "url": webhook_url
        }
        logger.info(f"Установка вебхука на URL: {webhook_url}")
        try:
            result = await self._request("POST", "setWebhook", json_data=data)
            logger.info(f"✅ Вебхук успешно установлен на {webhook_url}")
            return result
        except Exception as e:
            logger.error(f"❌ Ошибка установки вебхука: {e}")
            return None


def check_webhook_signature(body_text: str, signature: str, token: str) -> bool:
    """
    Проверяет подпись вебхука CryptoBot.
    """
    if not token or not signature:
        logger.warning("CRYPTO_BOT_TOKEN или signature отсутствуют")
        return False
   
    try:
        secret = hashlib.sha256(token.encode()).digest()
        hmac_obj = hmac.new(secret, body_text.encode(), hashlib.sha256)
        calculated_signature = hmac_obj.hexdigest()
       
        is_valid = calculated_signature == signature
        if not is_valid:
            logger.warning("Неверная подпись вебхука CryptoBot")
       
        return is_valid
    except Exception as e:
        logger.error(f"Ошибка проверки подписи: {e}")
        return False


# Глобальный экземпляр сервиса
crypto_bot_service = CryptoBotService()
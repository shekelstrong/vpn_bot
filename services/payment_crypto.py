"""
Сервис для работы с CryptoBot (@CryptoPay).
Асинхронный клиент для создания и проверки платежей.
"""

import httpx
import hashlib
import hmac
import json
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
        self._client = httpx.AsyncClient(timeout=30.0)
        
        if self.token:
            safe_token = f"{self.token[:4]}...{self.token[-4:]}" if len(self.token) > 8 else "***"
            logger.info(f"CryptoBot токен: {safe_token} (длина: {len(self.token)})")
            logger.info(f"CryptoBot URL: {self.base_url}")
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
    ) -> Dict[str, Any]:
        """
        Выполнить HTTP запрос к API.
        
        Args:
            method: HTTP метод.
            endpoint: Эндпоинт API.
            json_data: JSON данные для отправки.
            
        Returns:
            Dict: Ответ от API.
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
        
        try:
            response = await self._client.request(
                method=method,
                url=url,
                headers=headers,
                json=json_data,
            )
            
            logger.info(f"CryptoBot статус ответа: {response.status_code}")
            response.raise_for_status()
            result = response.json()
            
            logger.debug(f"CryptoBot полный ответ: {result}")
            
            if not result.get("ok"):
                error_msg = result.get('error', 'Unknown error')
                logger.error(f"CryptoBot API error: {error_msg}")
                raise Exception(f"CryptoBot API error: {error_msg}")
            
            return result
            
        except httpx.HTTPError as e:
            logger.error(f"CryptoBot HTTPError: {type(e).__name__}")
            logger.error(f"Ошибка CryptoBot API: {e}")
            logger.error(f"URL запроса: {url}")
            logger.error(f"Метод: {method}")
            logger.error(f"JSON данные: {safe_json}")
            if hasattr(e, 'response'):
                logger.error(f"Статус ответа: {e.response.status_code}")
                try:
                    logger.error(f"Текст ответа: {e.response.text}")
                except:
                    logger.error("Не удалось получить текст ответа")
            import traceback
            logger.error(f"Full traceback:\n{traceback.format_exc()}")
            raise
    
    async def create_invoice(
        self,
        amount_usdt: float,
        order_id: int,
        description: Optional[str] = None,
        paid_btn_name: Optional[str] = None,
        paid_btn_url: Optional[str] = None,
    ) -> Optional[str]:
        """
        Создать счет на оплату (по аналогии с рабочим проектом).
        
        Args:
            amount_usdt: Сумма в USDT.
            order_id: ID заказа для payload.
            description: Описание платежа.
            paid_btn_name: Название кнопки после оплаты.
            paid_btn_url: URL кнопки после оплаты.
            
        Returns:
            str: Ссылка на оплату или None при ошибке.
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
            async with httpx.AsyncClient() as session:
                async with session.post(
                    f"{self.base_url}/createInvoice",
                    json=payload,
                    headers=headers
                ) as resp:
                    result = await resp.json()
                    
                    logger.debug(f"CryptoBot response: {result}")
                    
                    if result.get("ok"):
                        link = result["result"]["pay_url"]
                        logger.info(f"✅ CryptoBot Invoice Created: {link}")
                        return link
                    else:
                        logger.error(f"❌ CryptoBot API Error: {result}")
                        return None
        except Exception as e:
            logger.error(f"❌ CryptoBot Connection Error: {e}")
            import traceback
            logger.error(f"Traceback:\n{traceback.format_exc()}")
            return None
    
    async def get_invoice(self, invoice_id: int) -> Dict[str, Any]:
        """
        Получить информацию о счете.
        
        Args:
            invoice_id: ID счета.
            
        Returns:
            Dict: Информация о счете.
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
        
        Returns:
            Dict: Баланс по разным валютам.
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
        
        Args:
            invoice_id: ID счета.
            
        Returns:
            str: Статус счета (paid, waiting, etc.)
        """
        invoice = await self.get_invoice(invoice_id)
        return invoice.get("status", "unknown")
    
    async def close(self):
        """Закрыть HTTP клиент."""
        await self._client.close()


def check_webhook_signature(body_text: str, signature: str, token: str) -> bool:
    """
    Проверяет подпись вебхука CryptoBot.
    
    Формула: header['crypto-pay-api-signature'] == hmac_sha256(secret, body)
    где secret = sha256(api_token)
    
    Args:
        body_text: Тело запроса в виде строки
        signature: Значение из заголовка 'crypto-pay-api-signature'
        token: API токен CryptoBot
        
    Returns:
        bool: True если подпись валидна, иначе False
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

"""
Сервис для работы с CryptoBot (@CryptoPay).
Асинхронный клиент для создания и проверки платежей.
"""

import httpx
import hashlib
import hmac
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
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
        self.base_url = "https://pay.cryptobot.app/api"
        self.token = settings.CRYPTO_BOT_TOKEN
        self._client = httpx.AsyncClient(timeout=30.0)
        
        # Логируем токен для диагностики (показываем только первые и последние 4 символа)
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
        json: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Выполнить HTTP запрос к API.
        
        Args:
            method: HTTP метод.
            endpoint: Эндпоинт API.
            json: JSON данные для отправки.
            
        Returns:
            Dict: Ответ от API.
        """
        url = f"{self.base_url}/{endpoint}"
        headers = await self._get_headers()
        
        # Детальное логирование перед запросом
        safe_json = json.copy() if json else {}
        safe_json.pop('custom_payload', None)  # Скрываем чувствительные данные
        
        logger.debug(f"CryptoBot запрос: {method} {url}")
        logger.debug(f"Headers: {headers}")
        logger.debug(f"JSON данные: {safe_json}")
        
        try:
            response = await self._client.request(
                method=method,
                url=url,
                headers=headers,
                json=json,
            )
            
            # Логируем статус ответа
            logger.info(f"CryptoBot статус ответа: {response.status_code}")
            
            response.raise_for_status()
            result = response.json()
            
            # Детальное логирование ответа
            logger.debug(f"CryptoBot полный ответ: {result}")
            
            if not result.get("ok"):
                error_msg = result.get('error', 'Unknown error')
                logger.error(f"CryptoBot API error: {error_msg}")
                logger.error(f"Полный ответ при ошибке: {result}")
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
                    pass
            raise
    
    async def create_invoice(
        self,
        amount: float,
        currency: str = "RUB",
        description: Optional[str] = None,
        custom_payload: Optional[str] = None,
        paid_btn_name: Optional[str] = None,
        paid_btn_url: Optional[str] = None,
        allow_comments: bool = True,
        ttl: int = 3600  # Время жизни счета в секундах
    ) -> Dict[str, Any]:
        """
        Создать счет на оплату.
        
        Args:
            amount: Сумма к оплате.
            currency: Валюта (RUB, USDT, TON, и т.д.).
            description: Описание платежа.
            custom_payload: Полезная нагрузка (до 4000 символов).
            paid_btn_name: Название кнопки после оплаты.
            paid_btn_url: URL кнопки после оплаты.
            allow_comments: Разрешить комментарии.
            ttl: Время жизни счета в секундах.
            
        Returns:
            Dict: Информация о созданном счете включая invoice_url.
        """
        # Детальное логирование перед созданием счета
        logger.info(f"CryptoBot create_invoice вызван: amount={amount}, currency={currency}")
        logger.info(f"Описание: {description}")
        logger.info(f"Custom payload: {custom_payload}")
        
        data = {
            "amount": str(amount),
            "currency": currency,
            "description": description or "",
            "allow_comments": allow_comments,
            "ttl": ttl,
        }
        
        if custom_payload:
            data["custom_payload"] = custom_payload
        
        if paid_btn_name and paid_btn_url:
            data["paid_btn_name"] = paid_btn_name
            data["paid_btn_url"] = paid_btn_url
        
        logger.debug(f"JSON данные для создания счета: {data}")
        
        try:
            result = await self._request("POST", "createInvoice", json=data)
            invoice = result.get("result", {})
            
            logger.info(
                f"✅ Создан счет CryptoBot: {invoice.get('invoice_id')} "
                f"на сумму {amount} {currency}"
            )
            logger.debug(f"Полный ответ создания счета: {invoice}")
            
            return invoice
            
        except Exception as e:
            logger.error(f"❌ Ошибка создания счета CryptoBot: {e}")
            logger.error(f"Тип ошибки: {type(e).__name__}")
            import traceback
            logger.error(f"Traceback:\n{traceback.format_exc()}")
            raise
    
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
            result = await self._request("POST", "getInvoice", json=data)
            return result.get("result", {})
        except Exception as e:
            logger.error(f"Ошибка получения счета {invoice_id}: {e}")
            raise
    
    async def get_balance(self) -> List[Dict[str, Any]]:
        """
        Получить баланс бота.
        
        Returns:
            List: Список балансов по разным валютам.
        """
        try:
            result = await self._request("POST", "getBalance")
            return result.get("result", [])
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
    
    async def transfer(
        self,
        user_ids: List[int],
        asset: str,
        amount: float,
        spend_id: str,
        comment: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Перевести средства пользователю в CryptoBot.
        
        Args:
            user_ids: Список ID пользователей CryptoBot.
            asset: Актив для перевода (USDT, TON, и т.д.).
            amount: Сумма перевода.
            spend_id: Уникальный ID транзакции (для идемпотентности).
            comment: Комментарий к переводу.
            
        Returns:
            Dict: Информация о переводе.
        """
        data = {
            "user_ids": user_ids,
            "asset": asset,
            "amount": str(amount),
            "spend_id": spend_id,
        }
        
        if comment:
            data["comment"] = comment
        
        try:
            result = await self._request("POST", "transfer", json=data)
            logger.info(f"Перевод {amount} {asset} пользователям {user_ids}")
            return result.get("result", {})
        except Exception as e:
            logger.error(f"Ошибка перевода: {e}")
            raise
    
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

"""
Сервис для работы с Platega.io.
Обработка вебхуков и создание платежей.
"""

import hashlib
import hmac
from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, validator
from loguru import logger

from config import settings


class PlategaPaymentData(BaseModel):
    """
    Модель данных платежа Platega.
    
    Атрибуты:
        order_id: ID заказа в вашей системе.
        amount: Сумма платежа.
        currency: Валюта платежа.
        status: Статус платежа (success, failed, pending).
        custom_id: Пользовательские данные (Telegram ID).
        payment_id: ID платежа в Platega.
        signature: Подпись для верификации.
        created_at: Дата создания платежа.
    """
    order_id: str
    amount: float
    currency: str
    status: str
    custom_id: Optional[str] = None
    payment_id: Optional[str] = None
    signature: str
    created_at: Optional[datetime] = None
    
    @validator('status')
    def validate_status(cls, v):
        """Валидация статуса платежа."""
        allowed_statuses = ['success', 'failed', 'pending', 'expired', 'cancelled']
        if v.lower() not in allowed_statuses:
            raise ValueError(f"Недопустимый статус: {v}")
        return v.lower()


class PlategaService:
    """
    Сервис для работы с Platega.io.
    
    Методы:
        verify_signature: Проверить подпись вебхука.
        parse_webhook: Распарсить данные вебхука.
        create_payment_url: Создать URL для оплаты.
    """
    
    def __init__(self):
        self.secret_key = settings.PLATEGA_SECRET_KEY
        self.base_url = "https://api.platega.io"
    
    def verify_signature(self, payload: Dict[str, Any], signature: str) -> bool:
        """
        Проверить подпись вебхука.
        
        Args:
            payload: Данные вебхука.
            signature: Подпись из заголовка.
            
        Returns:
            bool: True если подпись верна.
        """
        # Сортируем ключи и создаем строку для подписи
        sorted_data = sorted(payload.items())
        data_string = "&".join(f"{k}={v}" for k, v in sorted_data if k != 'signature')
        
        # Создаем HMAC-SHA256 подпись
        expected_signature = hmac.new(
            self.secret_key.encode('utf-8'),
            data_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        # Сравниваем подписи
        is_valid = hmac.compare_digest(expected_signature, signature)
        
        if not is_valid:
            logger.warning(f"Неверная подпись Platega. Ожидалось: {expected_signature}, Получено: {signature}")
        
        return is_valid
    
    def parse_webhook(self, payload: Dict[str, Any], signature: str) -> Optional[PlategaPaymentData]:
        """
        Распарсить и проверить данные вебхука.
        
        Args:
            payload: Данные вебхука.
            signature: Подпись из заголовка.
            
        Returns:
            PlategaPaymentData: Проверенные данные платежа или None.
        """
        # Проверяем подпись
        if not self.verify_signature(payload, signature):
            logger.error("Неверная подпись вебхука Platega")
            return None
        
        try:
            # Создаем модель данных
            payment_data = PlategaPaymentData(**payload)
            logger.info(f"Получен вебхук Platega: заказ {payment_data.order_id}, статус {payment_data.status}")
            return payment_data
            
        except Exception as e:
            logger.error(f"Ошибка парсинга вебхука Platega: {e}")
            return None
    
    def create_payment_url(
        self,
        order_id: str,
        amount: float,
        currency: str = "RUB",
        custom_id: Optional[str] = None,
        description: Optional[str] = None,
        success_url: Optional[str] = None,
        fail_url: Optional[str] = None
    ) -> str:
        """
        Создать URL для оплаты.
        
        Args:
            order_id: ID заказа в вашей системе.
            amount: Сумма платежа.
            currency: Валюта платежа.
            custom_id: Пользовательские данные (Telegram ID).
            description: Описание платежа.
            success_url: URL для перенаправления после успешной оплаты.
            fail_url: URL для перенаправления после неудачной оплаты.
            
        Returns:
            str: URL для оплаты.
        """
        # В реальном сценарии здесь должен быть запрос к API Platega
        # для создания платежа и получения URL
        
        # Формируем параметры
        params = {
            "order_id": order_id,
            "amount": str(amount),
            "currency": currency,
        }
        
        if custom_id:
            params["custom_id"] = custom_id
        
        if description:
            params["description"] = description
        
        if success_url:
            params["success_url"] = success_url
        
        if fail_url:
            params["fail_url"] = fail_url
        
        # Создаем подпись
        sorted_data = sorted(params.items())
        data_string = "&".join(f"{k}={v}" for k, v in sorted_data)
        signature = hmac.new(
            self.secret_key.encode('utf-8'),
            data_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        params["signature"] = signature
        
        # Формируем URL
        # В реальности URL нужно получать из API ответа
        query_string = "&".join(f"{k}={v}" for k, v in params.items())
        payment_url = f"{self.base_url}/pay?{query_string}"
        
        logger.info(f"Создан платеж Platega: {order_id} на сумму {amount} {currency}")
        
        return payment_url
    
    def create_signature(self, data: Dict[str, Any]) -> str:
        """
        Создать подпись для запроса к API Platega.
        
        Args:
            data: Данные запроса.
            
        Returns:
            str: HMAC-SHA256 подпись.
        """
        sorted_data = sorted(data.items())
        data_string = "&".join(f"{k}={v}" for k, v in sorted_data)
        
        signature = hmac.new(
            self.secret_key.encode('utf-8'),
            data_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        return signature


# Глобальный экземпляр сервиса
platega_service = PlategaService()

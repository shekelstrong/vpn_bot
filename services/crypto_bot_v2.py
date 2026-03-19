"""
CryptoBot v2 API сервис для создания счетов.
Реализует автоматическую выдачу подписок и валидацию webhook'ов.
"""

from aiogram import Bot
from aiocryptopay import AioCryptoPay, Networks
from loguru import logger
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from config import settings
from database.models import User, PaymentInvoice
from services.marzban_api import marzban_service
import json


class CryptoBotV2Service:
    """Сервис для работы с CryptoBot API v2."""
    
    def __init__(self):
        """Инициализация сервиса."""
        self.token = settings.CRYPTO_BOT_TOKEN
        self.network = Networks.MAIN_NET
        
        # Логируем токен (маскированный)
        if self.token and self.token != "your_crypto_bot_token_here":
            safe_token = f"{self.token[:4]}...{self.token[-4:]}" if len(self.token) > 8 else "***"
            logger.info(f"CryptoBot v2 токен: {safe_token} (длина: {len(self.token)})")
        else:
            logger.error("❌ CRYPTO_BOT_TOKEN не задан в настройках!")
        
        # Инициализация CryptoPay
        try:
            self.crypto = AioCryptoPay(
                token=self.token,
                network=self.network
            )
            logger.info(f"✅ CryptoBot v2 инициализирован (сеть: {self.network})")
        except Exception as e:
            logger.error(f"❌ Ошибка инициализации CryptoBot: {e}")
            self.crypto = None
    
    async def get_me(self) -> Optional[Dict[str, Any]]:
        """Получить информацию о приложении."""
        if not self.crypto:
            return None
        
        try:
            app = await self.crypto.get_me()
            logger.info(f"Информация о приложении: {app}")
            return app
        except Exception as e:
            logger.error(f"Ошибка получения get_me: {e}")
            return None
    
    async def create_invoice(
        self,
        user_id: int,
        amount_usdt: float,
        days: int,
        description: str = None
    ) -> Optional[Dict[str, Any]]:
        """
        Создать счет на оплату подписки.
        
        Args:
            user_id: ID пользователя
            amount_usdt: Сумма в USDT
            days: Срок подписки в днях
            description: Описание платежа
        
        Returns:
            Dict с информацией о счете или None при ошибке
        """
        if not self.crypto:
            logger.error("CryptoBot не инициализирован")
            return None
        
        # Создаем custom_payload с данными пользователя
        custom_payload_dict = {
            "user_id": user_id,
            "days": days,
            "type": "subscription"
        }
        custom_payload = json.dumps(custom_payload_dict)
        
        full_description = description or f"Nemo VPN подписка на {days} дней"
        
        try:
            logger.info(f"Создание счета CryptoBot v2:")
            logger.info(f"  Пользователь: {user_id}")
            logger.info(f"  Сумма: {amount_usdt} USDT")
            logger.info(f"  Срок: {days} дней")
            logger.info(f"  Custom payload: {custom_payload}")
            
            # Создаем счет
            invoice = await self.crypto.create_invoice(
                asset="USDT",
                amount=amount_usdt,
                description=full_description,
                payload=custom_payload,
                allow_comments=False,
                allow_anonymous=True,
                paid_btn_name="Вернуться в бот",
                paid_btn_url=f"https://t.me/nemo_vpn_bot"  # Замените на имя вашего бота
            )
            
            logger.info(f"✅ Счет создан: {invoice.invoice_id}")
            logger.info(f"  Bot invoice URL: {invoice.bot_invoice_url}")
            logger.info(f"  Mini app URL: {invoice.mini_app_invoice_url}")
            logger.info(f"  Web app URL: {invoice.web_app_invoice_url}")
            
            return {
                "invoice_id": str(invoice.invoice_id),
                "bot_invoice_url": invoice.bot_invoice_url,
                "mini_app_invoice_url": invoice.mini_app_invoice_url,
                "web_app_invoice_url": invoice.web_app_invoice_url,
                "hash": invoice.hash
            }
            
        except Exception as e:
            logger.error(f"❌ Ошибка создания счета: {e}")
            import traceback
            logger.error(f"Traceback:\n{traceback.format_exc()}")
            return None
    
    async def verify_webhook_update(self, update: Dict[str, Any]) -> bool:
        """
        Проверить подпись webhook обновления.
        
        Args:
            update: Обновление от CryptoBot
        
        Returns:
            bool: True если подпись валидна
        """
        if not self.crypto:
            return False
        
        try:
            # Проверяем наличие необходимых полей
            if "update_type" not in update:
                logger.error("Webhook update не содержит update_type")
                return False
            
            if update["update_type"] != "invoice_paid":
                logger.debug(f"Неподдерживаемый update_type: {update['update_type']}")
                return False
            
            if "payload" not in update:
                logger.error("Webhook update не содержит payload")
                return False
            
            payload = update["payload"]
            if not isinstance(payload, dict):
                logger.error(f"Payload не является словарем: {type(payload)}")
                return False
            
            # Проверяем invoice
            if "invoice_id" not in payload:
                logger.error("Webhook update не содержит invoice_id")
                return False
            
            logger.info(f"Webhook update получен: invoice_id={payload.get('invoice_id')}, hash={payload.get('hash')}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка проверки webhook подписи: {e}")
            return False


# Глобальный экземпляр сервиса
crypto_bot_v2_service = CryptoBotV2Service()

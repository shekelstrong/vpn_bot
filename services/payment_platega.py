"""
Сервис для работы с Platega.io.
Обработка вебхуков и создание платежей.
"""

import aiohttp
import logging
import json
from config import settings

logger = logging.getLogger(__name__)

# Ссылки для возврата после оплаты
# После оплаты пользователь возвращается на HTML страницу с сообщением об успехе
# order_id будет добавлен при создании платежа
def get_return_urls():
    """Получить URL для возврата после оплаты."""
    base_url = settings.BASE_URL
    # Добавляем протокол если нет
    if not base_url.startswith("http://") and not base_url.startswith("https://"):
        base_url = f"https://{base_url}"
    
    return {
        "return": f"{base_url}/pay_success",
        "failed": f"{base_url}/pay_failed"
    }

RETURN_URLS = get_return_urls()
RETURN_URL = RETURN_URLS["return"]
FAILED_URL = RETURN_URLS["failed"]


async def create_invoice(amount_rub: int, order_id: str, user_id: int, description: str = ""):
    """
    Создает платеж в Platega.io

    Args:
        amount_rub: Сумма в рублях
        order_id: ID заказа (уникальный, строка формата "tier_BASIC_12345")
        user_id: ID пользователя Telegram
        description: Описание платежа

    Returns:
        str: Ссылка на оплату или None при ошибке
    """

    if not settings.PLATEGA_MERCHANT_ID:
        logger.error("❌ PLATEGA_MERCHANT_ID is missing in config.py!")
        return None

    if not settings.PLATEGA_API_KEY:
        logger.error("❌ PLATEGA_API_KEY is missing in config.py!")
        return None

    # Используем проверенный эндпоинт
    url = "https://app.platega.io/transaction/process"

    headers = {
        "X-MerchantId": settings.PLATEGA_MERCHANT_ID,
        "X-Secret": settings.PLATEGA_API_KEY,
        "Content-Type": "application/json",
        "User-Agent": "Python/3.11 aiohttp/3.10"
    }

    # Формируем payload
    # Важно: order_id передаем и в payload (для вебхука), и в return URL (для возврата)
    return_url_with_order = f"{RETURN_URL}?order_id={order_id}"

    payload_data = {
        "paymentMethod": 2,  # Оплата картой
        "paymentDetails": {
            "amount": int(amount_rub),
            "currency": "RUB"
        },
        "description": description if description else f"Order #{order_id}",
        "return": return_url_with_order,
        "failedUrl": FAILED_URL,
        "payload": str(order_id)  # В payload передаем order_id для идентификации в вебхуке
    }

    logger.info(f"📤 Platega Request: {payload_data}")

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload_data, headers=headers) as resp:
                response_text = await resp.text()
                logger.info(f"📥 Platega Response status: {resp.status}")

                # Попытка 1: Пробуем распарсить JSON (штатный режим)
                try:
                    data = json.loads(response_text)
                except:
                    logger.warning(f"⚠️ Platega ответила не JSON-ом: {response_text}")
                    data = {}

                if resp.status in (200, 201):
                    # Ищем ссылку
                    link = data.get("redirect") or data.get("url") or data.get("payment_url")
                    if link:
                        logger.info(f"✅ Invoice created: {link}")
                        return link
                    else:
                        logger.error(f"❌ Ссылка не найдена в ответе: {data}")
                        return None
                else:
                    logger.error(f"❌ Platega Error ({resp.status}): {response_text}")
                    return None

        except Exception as e:
            logger.error(f"❌ Platega Connection Error: {e}")
            return None


class PlategaService:
    """
    Сервис для работы с Platega.io.
    """

    def __init__(self):
        self.merchant_id = settings.PLATEGA_MERCHANT_ID
        self.api_key = settings.PLATEGA_API_KEY
        self.base_url = settings.PLATEGA_BASE_URL

    def create_payment_url(
        self,
        order_id: str,
        amount: float,
        currency: str = "RUB",
        custom_id: str = None,
        description: str = None,
        success_url: str = None,
        fail_url: str = None
    ) -> str:
        """
        Создать URL для оплаты (совместимость со старым кодом).

        Для нового кода используйте async-функцию create_invoice.
        """
        logger.warning("⚠️ Используйте async-функцию create_invoice вместо create_payment_url")
        return f"https://app.platega.io/pay?order_id={order_id}"


# Глобальный экземпляр сервиса
platega_service = PlategaService()
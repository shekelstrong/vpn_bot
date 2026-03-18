from pydantic_settings import BaseSettings
from pydantic import Field
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

class Settings(BaseSettings):
    """Основные настройки бота."""
    # Telegram Bot
    BOT_TOKEN: str = Field(..., description="Токен Telegram бота")
    ADMIN_IDS: str = Field(..., description="Список ID администраторов через запятую")

    # Marzban API
    MARZBAN_URL: str = Field(default="https://vpn.dealflow.bond", description="URL Marzban панели")
    MARZBAN_ADMIN_USERNAME: str = Field(..., description="Логин администратора Marzban")
    MARZBAN_ADMIN_PASSWORD: str = Field(..., description="Пароль администратора Marzban")

    # Database
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///vpn_bot.db",
        description="URL подключения к базе данных"
    )
    POSTGRES_PASSWORD: str = Field(
        default="", 
        description="Пароль от PostgreSQL (нужен для Docker)"
    )

    # CryptoBot
    CRYPTO_BOT_TOKEN: str = Field(..., description="Токен CryptoBot API")

    # Platega
    PLATEGA_SECRET_KEY: str = Field(..., description="Секретный ключ Platega для вебхуков")

    # Referral system
    REFERRAL_PERCENTAGES: str = Field(default="15,10,5", description="Проценты реферальной системы (уровень 1,2,3)")
    REFERRAL_MIN_WITHDRAW: int = Field(default=1000, description="Минимальная сумма вывода (рублей)")

    # VLESS Reality настройки
    VLESS_PORT: int = Field(default=8444, description="Порт VLESS Reality")
    VLESS_SNI: str = Field(default="dl.google.com", description="SNI для VLESS Reality")
    VLESS_PUBLIC_KEY: str = Field(
        default="WWB0761AFkXyj17WK7shhvGMvMl2NrRpLLfvTnH7TkA",
        description="Публичный ключ VLESS Reality"
    )
    VLESS_SHORT_ID: str = Field(default="fb8e00", description="Short ID для VLESS Reality")
    VLESS_FINGERPRINT: str = Field(default="chrome", description="Fingerprint для VLESS Reality")

    # Trial настройки
    TRIAL_DATA_LIMIT_GB: int = Field(default=1, description="Лимит трафика для триала (GB)")
    TRIAL_EXPIRE_HOURS: int = Field(default=24, description="Время действия триала (часы)")

    # Subscription настройки
    SUBSCRIPTION_PRICE_RUB: int = Field(default=100, description="Цена подписки в рублях")
    SUBSCRIPTION_EXPIRE_DAYS: int = Field(default=30, description="Срок подписки в днях")

    # Notification intervals (в минутах до истечения)
    NOTIFICATION_INTERVALS: str = Field(
        default="10080,7200,4320,1440,720,360,180,120,60",
        description="Интервалы уведомлений в минутах (7д, 5д, 3д, 24ч, 12ч, 6ч, 3ч, 2ч, 1ч)"
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    @property
    def admin_ids_list(self) -> List[int]:
        """Возвращает список ID администраторов."""
        return [int(x.strip()) for x in self.ADMIN_IDS.split(",")]

    @property
    def referral_percentages_list(self) -> List[int]:
        """Возвращает список процентов реферальной системы."""
        return [int(x.strip()) for x in self.REFERRAL_PERCENTAGES.split(",")]

    @property
    def notification_intervals_list(self) -> List[int]:
        """Возвращает список интервалов уведомлений в минутах."""
        return [int(x.strip()) for x in self.NOTIFICATION_INTERVALS.split(",")]

    @property
    def marzban_api_url(self) -> str:
        """Возвращает полный URL API Marzban."""
        return f"{self.MARZBAN_URL}/api"


async def get_db_setting(session: AsyncSession, key: str, default: str = "") -> str:
    """Получить настройку из БД."""
    from database.models import BotSettings
    from sqlalchemy import select
    
    result = await session.execute(select(BotSettings).where(BotSettings.key == key))
    setting = result.scalar_one_or_none()
    return setting.value if setting else default


async def get_db_settings_dict(session: AsyncSession) -> dict:
    """Получить все настройки из БД."""
    from database.models import BotSettings
    from sqlalchemy import select
    
    result = await session.execute(select(BotSettings))
    settings = result.scalars().all()
    return {s.key: s.value for s in settings}


async def update_db_setting(session: AsyncSession, key: str, value: str, description: Optional[str] = None) -> None:
    """Обновить или создать настройку в БД."""
    from database.models import BotSettings
    from sqlalchemy import select
    
    result = await session.execute(select(BotSettings).where(BotSettings.key == key))
    setting = result.scalar_one_or_none()
    
    if setting:
        setting.value = value
        if description:
            setting.description = description
    else:
        setting = BotSettings(key=key, value=value, description=description)
        session.add(setting)
    
    await session.commit()


async def init_default_settings(session: AsyncSession) -> None:
    """Инициализация дефолтных настроек в БД."""
    defaults = {
        "subscription_price": ("100", "Цена подписки в рублях"),
        "subscription_duration": ("30", "Базовый срок подписки в днях"),
        "trial_hours": ("24", "Срок действия триала в часах"),
        "trial_data_limit": ("1", "Лимит трафика для триала в GB"),
        "referral_level1": ("15", "Процент рефералов уровня 1"),
        "referral_level2": ("10", "Процент рефералов уровня 2"),
        "referral_level3": ("5", "Процент рефералов уровня 3"),
        "referral_min_withdraw": ("1000", "Минимальная сумма вывода в рублях"),
        # Скидки для разных сроков подписки (в процентах)
        "discount_3month": ("10", "Скидка на 3 месяца (в процентах)"),
        "discount_6month": ("17", "Скидка на 6 месяцев (в процентах)"),
        "discount_12month": ("25", "Скидка на 12 месяцев (в процентах)"),
    }
    
    for key, (value, desc) in defaults.items():
        result = await session.execute(select(BotSettings).where(BotSettings.key == key))
        if not result.scalar_one_or_none():
            session.add(BotSettings(key=key, value=value, description=desc))
    
    await session.commit()


async def calculate_tariff_price(session: AsyncSession, base_price: float, months: int) -> float:
    """Рассчитать цену с учетом скидки для указанного срока."""
    from database.models import BotSettings
    
    discount_key = f"discount_{months}month" if months >= 3 else None
    if not discount_key:
        return base_price * months
    
    discount_percent = await get_db_setting(session, discount_key, "0")
    discount = float(discount_percent) / 100
    final_price = base_price * months * (1 - discount)
    
    return round(final_price, 2)


from database.models import BotSettings
from sqlalchemy import select

# Глобальный экземпляр настроек
settings = Settings()
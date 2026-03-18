from pydantic_settings import BaseSettings
from pydantic import Field
from typing import List

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
        extra = "ignore" # Добавлено правило игнорировать любые другие переменные из .env, чтобы бот больше не падал из-за них

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

# Глобальный экземпляр настроек
settings = Settings()
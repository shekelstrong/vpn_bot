"""
Конфигурация бота Nemo VPN.

ИЗМЕНЕНИЯ:
1. Добавлен CHANNEL_USERNAME — Telegram канал для бонуса
2. Добавлены ссылки на скачивание Happ для всех платформ
3. Добавлены GB_LIMITS для VIP-тарифов по длительности
4. Убраны упоминания V2Box
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

class Settings(BaseSettings):
    """Основные настройки бота."""
    # Telegram Bot
    BOT_TOKEN: str = Field(..., description="Токен Telegram бота")
    ADMIN_IDS: str = Field(..., description="Список ID администраторов через запятую")

    # Канал Nemo VPN (для проверки подписки и бонуса)
    CHANNEL_USERNAME: str = Field(default="@your_channel", description="Telegram канал")
    CHANNEL_CHAT_ID: str = Field(default="-1000000000000", description="Chat ID канала")

    # 3x-ui API (замена Marzban) — теперь DE сервер
    XUI_API_URL: str = Field(
        default="http://108.165.164.85:4531/LpAp7d5rTkYOZaLipZ",
        description="URL панели 3x-ui DE (с webBasePath)"
    )
    XUI_USERNAME: str = Field(default="nedopekin", description="Логин 3x-ui")
    XUI_PASSWORD: str = Field(default="", description="Пароль 3x-ui")
    XUI_HOST: str = Field(default="108.165.164.85", description="IP 3x-ui DE сервера")
    XUI_PORT_STANDARD: int = Field(default=443, description="Порт Standard inbound DE")
    XUI_PORT_PREMIUM: int = Field(default=9999, description="Порт Premium/Chain inbound DE")
    XUI_SNI_STANDARD: str = Field(default="www.yandex.ru", description="SNI Standard")
    XUI_SNI_PREMIUM: str = Field(default="www.yandex.ru", description="SNI Premium")
    XUI_PBK_STANDARD: str = Field(
        default="O1iyQMVfn3K6Yp1Ctoo5vuvkt4H0qaSxHAVglCXud2M",
        description="Публичный ключ Reality Standard"
    )
    XUI_PBK_PREMIUM: str = Field(
        default="O1iyQMVfn3K6Yp1Ctoo5vuvkt4H0qaSxHAVglCXud2M",
        description="Публичный ключ Reality Premium"
    )
    XUI_SID_STANDARD: str = Field(default="5a3b7f1d", description="Short ID Standard")
    XUI_SID_PREMIUM: str = Field(default="5a3b7f1d", description="Short ID Premium")
    SUB_PATH: str = Field(default="e83f38f3d13ccd6a", description="Путь subscription service")

    # Marzban API (устаревшее, для совместимости)
    MARZBAN_URL: str = Field(default="https://your-marzban-url.com", description="URL Marzban панели (deprecated)")
    MARZBAN_ADMIN_USERNAME: str = Field(default="deprecated", description="Логин администратора Marzban (deprecated)")
    MARZBAN_ADMIN_PASSWORD: str = Field(default="deprecated", description="Пароль администратора Marzban (deprecated)")

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
    USDT_TO_RUB_RATE: float = Field(default=90.0, description="Курс USDT к RUB")

    # Platega
    PLATEGA_MERCHANT_ID: str = Field(..., description="Merchant ID Platega")
    PLATEGA_API_KEY: str = Field(..., description="API ключ Platega")
    PLATEGA_SECRET_KEY: str = Field(..., description="Секретный ключ Platega для вебхуков")
    PLATEGA_BASE_URL: str = Field(default="https://app.platega.io", description="Базовый URL Platega API")
    WEB_PORT: int = Field(default=8080, description="Порт для вебхук-сервера")
    BASE_URL: str = Field(default="localhost", description="Базовый URL для вебхуков")

    # Referral system
    REFERRAL_PERCENTAGES: str = Field(default="15,10,5", description="Проценты реферальной системы (уровень 1,2,3)")
    REFERRAL_MIN_WITHDRAW: int = Field(default=1000, description="Минимальная сумма вывода (рублей)")

    # VLESS Reality настройки (Стандарт)
    VLESS_PORT: int = Field(default=8444, description="Порт VLESS Reality")
    VLESS_SNI: str = Field(default="your-sni.com", description="SNI для VLESS Reality")
    VLESS_PUBLIC_KEY: str = Field(
        default="your-public-key",
        description="Публичный ключ VLESS Reality"
    )
    VLESS_SHORT_ID: str = Field(default="fb8e00", description="Short ID для VLESS Reality")
    VLESS_FINGERPRINT: str = Field(default="chrome", description="Fingerprint для VLESS Reality")

    # Trial настройки
    TRIAL_DATA_LIMIT_GB: int = Field(default=1, description="Лимит трафика для триала (GB)")
    TRIAL_EXPIRE_HOURS: int = Field(default=24, description="Время действия триала (часы)")

    # Subscription настройки (единая подписка = оба конфига)
    SUBSCRIPTION_PRICE_RUB: int = Field(default=500, description="Цена подписки в рублях (1 мес)")

    # Бонус за подписку на канал
    CHANNEL_BONUS_DAYS: int = Field(default=3, description="Бонус дней за подписку на канал")

    # Notification intervals
    NOTIFICATION_INTERVALS: str = Field(
        default="10080,7200,4320,1440,720,360,180,120,60",
        description="Интервалы уведомлений в минутах"
    )

    # Ссылки на Happ
    HAPPL_IOS_URL: str = Field(
        default="https://apps.apple.com/us/app/happ-proxy-utility/id6504287215",
        description="Ссылка на Happ в App Store"
    )
    HAPPL_ANDROID_URL: str = Field(
        default="https://play.google.com/store/apps/details?id=com.happproxy",
        description="Ссылка на Happ в Google Play"
    )
    HAPPL_WINDOWS_URL: str = Field(
        default="https://github.com/Happ-proxy/happ-desktop/releases/latest/download/setup-Happ.x64.exe",
        description="Ссылка на Happ для Windows"
    )
    HAPPL_LINUX_URL: str = Field(
        default="https://github.com/Happ-proxy/happ-desktop/releases/latest",
        description="Ссылка на Happ для Linux"
    )

    # GB лимиты по длительности подписки (для БС инбаунда)
    VIP_GB_LIMITS: str = Field(
        default="10,100,350,800,2048",
        description="Лимиты GB: 3д, 1мес, 3мес, 6мес, 12мес"
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    @property
    def admin_ids_list(self) -> List[int]:
        return [int(x.strip()) for x in self.ADMIN_IDS.split(",")]

    @property
    def referral_percentages_list(self) -> List[int]:
        return [int(x.strip()) for x in self.REFERRAL_PERCENTAGES.split(",")]

    @property
    def notification_intervals_list(self) -> List[int]:
        return [int(x.strip()) for x in self.NOTIFICATION_INTERVALS.split(",")]

    @property
    def marzban_api_url(self) -> str:
        return f"{self.MARZBAN_URL}/api"

    @property
    def vip_gb_limits_list(self) -> List[int]:
        return [int(x.strip()) for x in self.VIP_GB_LIMITS.split(",")]

    def get_vip_gb_limit(self, days: int) -> int:
        """Получить GB лимит по количеству дней подписки."""
        gb_map = {3: 10, 30: 100, 90: 350, 180: 800, 365: 2048}
        return gb_map.get(days, days * 3)


async def get_db_setting(session: AsyncSession, key: str, default: str = "") -> str:
    from database.models import BotSettings
    result = await session.execute(select(BotSettings).filter(BotSettings.key == key))
    setting = result.scalar_one_or_none()
    return setting.value if setting else default

async def get_db_settings_dict(session: AsyncSession) -> dict:
    from database.models import BotSettings
    result = await session.execute(select(BotSettings))
    settings = result.scalars().all()
    return {s.key: s.value for s in settings}

async def update_db_setting(session: AsyncSession, key: str, value: str, description: Optional[str] = None) -> None:
    from database.models import BotSettings
    result = await session.execute(select(BotSettings).filter(BotSettings.key == key))
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = value
        setting.description = description
        await session.commit()
    else:
        session.add(BotSettings(key=key, value=value, description=description))
        await session.commit()

async def init_default_settings(session: AsyncSession) -> None:
    from database.models import BotSettings
    defaults = {
        "subscription_price": ("500", "Цена подписки в рублях (1 мес, оба конфига)"),
        "subscription_duration": ("30", "Базовый срок подписки в днях"),
        "trial_hours": ("24", "Срок действия триала в часах"),
        "trial_data_limit": ("1", "Лимит трафика для триала в GB"),
        "referral_level1": ("15", "Процент рефералов уровня 1"),
        "referral_level2": ("10", "Процент рефералов уровня 2"),
        "referral_level3": ("5", "Процент рефералов уровня 3"),
        "referral_min_withdraw": ("1000", "Минимальная сумма вывода в рублях"),
        "discount_3month": ("0", "Скидка на 3 месяца (в процентах)"),
        "discount_6month": ("0", "Скидка на 6 месяцев (в процентах)"),
        "discount_12month": ("0", "Скидка на 12 месяцев (в процентах)"),
        "channel_bonus_days": ("3", "Бонус дней за подписку на канал"),
    }
    for key, (value, desc) in defaults.items():
        result = await session.execute(select(BotSettings).where(BotSettings.key == key))
        if not result.scalar_one_or_none():
            session.add(BotSettings(key=key, value=value, description=desc))
    await session.commit()

async def calculate_tariff_price(session: AsyncSession, base_price: float, months: int) -> float:
    from database.models import BotSettings
    discount_key = f"discount_{months}month" if months >= 3 else None
    if not discount_key:
        return base_price * months
    discount_percent = await get_db_setting(session, discount_key, "0")
    discount = float(discount_percent) / 100
    final_price = base_price * months * (1 - discount)
    return round(final_price, 2)

settings = Settings()

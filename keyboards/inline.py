"""
Модуль inline-клавиатур для бота Nemo VPN.

ИЗМЕНЕНИЯ:
1. Все упоминания V2Box убраны, заменены на Happ
2. Кнопка «Как настроить V2Box» → «Как настроить Happ 📱»
3. Ссылки на скачивание Happ для всех платформ (iOS, Android, Windows, macOS, Linux)
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import Optional, List


def get_main_menu_keyboard(show_trial: bool = True) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Мой профиль 👤", callback_data="profile", style="primary")
    builder.button(text="Реферальная программа 👥", callback_data="referral", style="primary")
    builder.button(text="Подписка 📦", callback_data="subscription", style="primary")
    builder.button(text="Купить подписку 🛒", callback_data="buy", style="primary")
    builder.button(text="🎁 Подарить VPN", callback_data="gift_start", style="primary")
    builder.button(text="Помощь 🆘", callback_data="help", style="danger")
    if show_trial:
        builder.button(text="Пробная подписка 🎁", callback_data="trial", style="success")
        builder.adjust(2, 2, 1, 1, 1)
    else:
        builder.adjust(2, 2, 1, 1)
    return builder.as_markup()


def get_profile_keyboard(
    has_subscription: bool = False,
    show_link: bool = False
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if show_link and has_subscription:
        builder.button(text="Получить ссылку 🔗", callback_data="get_vless_link", style="primary")
    builder.button(text="Реферальная программа 👥", callback_data="referral", style="primary")
    if has_subscription:
        builder.button(text="Продлить подписку 💳", callback_data="buy_extend", style="primary")
    builder.button(text="🔄 Перегенерировать ключ", callback_data="confirm_regenerate", style="primary")
    builder.button(text="Назад ↩️", callback_data="back_to_main", style="danger")
    builder.adjust(1, 1)
    return builder.as_markup()


def get_buy_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="CryptoBot (USDT) 💰", callback_data="pay_crypto", style="primary")
    builder.button(text="Банковская карта 🏦", callback_data="pay_card", style="primary")
    builder.button(text="Оплатить с реферального баланса 💰", callback_data="referral", style="primary")
    builder.button(text="Назад ↩️", callback_data="back_to_main", style="danger")
    builder.adjust(1, 1)
    return builder.as_markup()


def get_payment_keyboard(invoice_url: str, invoice_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Оплатить 💳", url=invoice_url, style="primary")
    builder.button(text="Проверить оплату ✅", callback_data=f"check_payment:{invoice_id}", style="success")
    builder.button(text="Отмена ❌", callback_data="cancel_payment", style="danger")
    builder.adjust(1, 1)
    return builder.as_markup()


def get_trial_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Активировать триал 🚀", callback_data="activate_trial", style="success")
    builder.button(text="Реферальная программа 👥", callback_data="referral", style="primary")
    builder.button(text="Назад ↩️", callback_data="back_to_main", style="danger")
    builder.adjust(1, 1)
    return builder.as_markup()


def get_help_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Как настроить Happ 📱", callback_data="help_happ", style="primary")
    builder.button(text="🔍 DPI-чекер", callback_data="dpi_check", style="primary")
    builder.button(text="Частые вопросы ❓", callback_data="help_faq", style="primary")
    builder.button(text="Реферальная программа 👥", callback_data="referral", style="primary")
    builder.button(text="Техподдержка 💬", callback_data="help_support", style="primary")
    builder.button(text="Политика конфиденциальности 📜", url="https://telegra.ph/Politika-konfidencialnosti-04-01-26")
    builder.button(text="Пользовательское соглашение 📝", url="https://telegra.ph/Polzovatelskoe-soglashenie-04-01-19")
    builder.button(text="Назад ↩️", callback_data="back_to_main", style="danger")
    builder.adjust(1, 1, 1, 1, 1, 1, 1)
    return builder.as_markup()


def get_happ_instruction_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура с ссылками на скачивание Happ для всех платформ."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📱 iOS (App Store)", url="https://apps.apple.com/us/app/happ-proxy-utility/id6504287215", style="primary")
    builder.button(text="🤖 Android (Google Play)", url="https://play.google.com/store/apps/details?id=com.happproxy", style="primary")
    builder.button(text="🖥 Windows", url="https://github.com/Happ-proxy/happ-desktop/releases/latest/download/setup-Happ.x64.exe", style="primary")
    builder.button(text="🍎 macOS", url="https://apps.apple.com/us/app/happ-proxy-utility/id6504287215", style="primary")
    builder.button(text="🐧 Linux", url="https://github.com/Happ-proxy/happ-desktop/releases/latest", style="primary")
    builder.button(text="Назад ↩️", callback_data="help", style="danger")
    builder.adjust(1)
    return builder.as_markup()


def get_referral_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Пригласить друга 👥", callback_data="referral_invite", style="primary")
    builder.button(text="Мои рефералы 📊", callback_data="referral_stats", style="primary")
    builder.button(text="Вывод баланса 💸", callback_data="start_withdraw", style="success")
    builder.button(text="Назад ↩️", callback_data="back_to_main", style="danger")
    builder.adjust(2, 2)
    return builder.as_markup()


def get_admin_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Статистика 📊", callback_data="admin_stats", style="primary")
    builder.button(text="Пользователи 👥", callback_data="admin_users", style="primary")
    builder.button(text="Рассылка 📢", callback_data="admin_broadcast", style="primary")
    builder.button(text="Настройки ⚙️", callback_data="settings", style="primary")
    builder.button(text="Закрыть панель 🔒", callback_data="admin_close", style="danger")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def get_admin_user_search_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Найти по Telegram ID 🔍", callback_data="admin_find_by_id", style="primary")
    builder.button(text="Найти по VK ID 🔗", callback_data="admin_find_by_vk_id", style="primary")
    builder.button(text="Найти по VK ссылке 🔗", callback_data="admin_find_by_vk_link", style="primary")
    builder.button(text="Найти по username 👤", callback_data="admin_find_by_username", style="primary")
    builder.button(text="Назад ↩️", callback_data="admin_panel", style="danger")
    builder.adjust(1, 1)
    return builder.as_markup()


def get_yes_no_keyboard(
    yes_callback: str,
    no_callback: str,
    question: str = "Вы уверены?"
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да", callback_data=yes_callback, style="success")
    builder.button(text="❌ Нет", callback_data=no_callback, style="danger")
    builder.adjust(2)
    return builder.as_markup()


def get_back_keyboard(callback_data: str = "back_to_main") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Назад ↩️", callback_data=callback_data, style="danger")
    return builder.as_markup()

# =====================================================================
# ТРАФИК — пакеты и клавиатуры
# =====================================================================

TRAFFIC_PACKAGES = [
    {"gb": 50, "price": 200},
    {"gb": 100, "price": 400},
    {"gb": 300, "price": 1000},
    {"gb": 500, "price": 2000},
]


def get_traffic_payment_keyboard(gb: int, price: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="₿ Крипто", callback_data=f"tpay_crypto_{gb}_{price}")
    builder.button(text="💳 Карта / СБП", callback_data=f"tpay_card_{gb}_{price}")
    builder.button(text="Назад ↩️", callback_data="traffic_buy")
    builder.adjust(2)
    return builder.as_markup()


# =====================================================================
# ТАРИФЫ, ТРАФИК, ПОДАРКИ, АДМИНКА
# =====================================================================

def get_tier_selection_keyboard(has_subscription: bool = False, tier: str = "premium") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    # Единая подписка — оба конфига
    builder.button(text="🛡 NEMO VPN (Стандарт + Обход БС)", callback_data="tier_premium", style="primary")
    if has_subscription:
        builder.button(text="📦 Докупить трафик", callback_data="traffic_buy", style="primary")
    builder.button(text="Назад ↩️", callback_data="back_to_main", style="danger")
    if has_subscription:
        builder.adjust(1, 1, 1)
    else:
        builder.adjust(1, 1)
    return builder.as_markup()


def get_subscription_duration_keyboard(
    tier: str,
    price_1m: float,
    price_3m: float,
    price_6m: float,
    price_12m: float,
    price_test: float
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    # Единая подписка — оба конфига (Стандарт безлимит + БС с лимитом)
    builder.button(text=f"🥉 3 дня — {int(price_test)}₽ (10 ГБ)", callback_data="duration_test3d", style="primary")
    builder.button(text=f"1 месяц — {int(price_1m)}₽ (100 ГБ)", callback_data="duration_1month", style="primary")
    builder.button(text=f"3 месяца — {int(price_3m)}₽ (350 ГБ)", callback_data="duration_3month", style="primary")
    builder.button(text=f"6 месяцев — {int(price_6m)}₽ (800 ГБ)", callback_data="duration_6month", style="primary")
    builder.button(text=f"12 месяцев — {int(price_12m)}₽ (2 ТБ)", callback_data="duration_12month", style="primary")
    builder.button(text="Назад ↩️", callback_data="buy", style="danger")
    builder.adjust(1, 1, 1, 1, 1, 1)
    return builder.as_markup()


def get_traffic_buy_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="50 ГБ — 200₽", callback_data="traffic_50", style="primary")
    builder.button(text="100 ГБ — 400₽", callback_data="traffic_100", style="primary")
    builder.button(text="300 ГБ — 1000₽", callback_data="traffic_300", style="primary")
    builder.button(text="500 ГБ — 2000₽", callback_data="traffic_500", style="primary")
    builder.button(text="Назад ↩️", callback_data="buy", style="danger")
    builder.adjust(1, 1, 1, 1, 1)
    return builder.as_markup()


def get_gift_tier_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🛡 NEMO VPN — от 700₽/мес (оба конфига)", callback_data="gift_premium", style="primary")
    builder.button(text="Назад ↩️", callback_data="back_to_main", style="danger")
    builder.adjust(1, 1)
    return builder.as_markup()


def get_gift_duration_keyboard(tier: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    # Единая подписка — оба конфига
    builder.button(text="1 месяц — 700₽ (100 ГБ)", callback_data="gift_dur_premium_1", style="primary")
    builder.button(text="3 месяца — 1800₽ (350 ГБ)", callback_data="gift_dur_premium_3", style="primary")
    builder.button(text="6 месяцев — 3000₽ (800 ГБ)", callback_data="gift_dur_premium_6", style="primary")
    builder.button(text="12 месяцев — 5500₽ (2 ТБ)", callback_data="gift_dur_premium_12", style="primary")
    builder.button(text="Назад ↩️", callback_data="gift_start", style="danger")
    builder.adjust(1, 1, 1, 1, 1)
    return builder.as_markup()


def get_gift_payment_keyboard(tier: str, days: int, price: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="₿ Крипто", callback_data=f"gpay_crypto_{tier}_{days}_{price}")
    builder.button(text="💳 Карта / СБП", callback_data=f"gpay_card_{tier}_{days}_{price}")
    builder.button(text="Назад ↩️", callback_data="gift_start")
    builder.adjust(2)
    return builder.as_markup()


def get_admin_settings_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💵 Цена подписки", callback_data="set_price_standard", style="primary")
    builder.button(text="⏳ Настроить скидки", callback_data="set_discounts", style="primary")
    builder.button(text="🔙 Назад", callback_data="admin_panel", style="danger")
    builder.adjust(1, 1, 1)
    return builder.as_markup()

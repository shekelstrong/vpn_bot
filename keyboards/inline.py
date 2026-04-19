"""
Модуль inline-клавиатур для бота Nemo VPN.
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
    builder.button(text="Помощь 🆘", callback_data="help", style="danger")
    if show_trial:
        builder.button(text="Пробная подписка 🎁", callback_data="trial", style="success")
        builder.adjust(2, 2, 1, 1)
    else:
        builder.adjust(2, 2, 1)
    return builder.as_markup()


def get_profile_keyboard(has_subscription: bool = False, show_link: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if show_link and has_subscription:
        builder.button(text="Получить ссылку 🔗", callback_data="get_vless_link", style="primary")
    builder.button(text="Реферальная программа 👥", callback_data="referral", style="primary")
    if has_subscription:
        builder.button(text="Продлить подписку 💳", callback_data="buy_extend", style="primary")
    builder.button(text="Докупить трафик 📶", callback_data="traffic_buy", style="primary")
    builder.button(text="Подарить подписку 🎁", callback_data="gift_start", style="primary")
    builder.button(text="Назад ↩️", callback_data="back_to_main", style="danger")
    builder.adjust(1, 1)
    return builder.as_markup()


def get_buy_keyboard(referral_balance: float = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="CryptoBot (USDT) 💰", callback_data="pay_crypto", style="primary")
    builder.button(text="Банковская карта 🏦", callback_data="pay_card", style="primary")
    if referral_balance > 0:
        builder.button(text=f"💳 Из реферального баланса ({referral_balance:.0f}₽)", callback_data="pay_referral", style="success")
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
    builder.button(text="Как настроить V2Box 📱", callback_data="help_v2box", style="primary")
    builder.button(text="Частые вопросы ❓", callback_data="help_faq", style="primary")
    builder.button(text="Реферальная программа 👥", callback_data="referral", style="primary")
    builder.button(text="Техподдержка 💬", callback_data="help_support", style="primary")
    builder.button(text="Политика конфиденциальности 📜", url="https://telegra.ph/Politika-konfidencialnosti-08-15-17")
    builder.button(text="Пользовательское соглашение 📝", url="https://telegra.ph/Polzovatelskoe-soglashenie-08-15-10")
    builder.button(text="Назад ↩️", callback_data="back_to_main", style="danger")
    builder.adjust(1)
    return builder.as_markup()


def get_v2box_instruction_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Скачать для iOS 🍎", url="https://apps.apple.com/us/app/v2box-v2ray-client/id6446814690", style="primary")
    builder.button(text="Скачать для Android 📱", url="https://play.google.com/store/apps/details?id=dev.hexasoftware.v2box", style="primary")
    builder.button(text="Назад ↩️", callback_data="help", style="danger")
    builder.adjust(1, 1, 1)
    return builder.as_markup()


def get_referral_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Пригласить друга 👥", callback_data="referral_invite", style="primary")
    builder.button(text="Мои рефералы 📊", callback_data="referral_stats", style="primary")
    builder.button(text="💳 Использовать баланс", callback_data="referral_buy", style="success")
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
    builder.button(text="Найти по ID 🔍", callback_data="admin_find_by_id", style="primary")
    builder.button(text="Найти по username 👤", callback_data="admin_find_by_username", style="primary")
    builder.button(text="Назад ↩️", callback_data="admin_panel", style="danger")
    builder.adjust(1, 1)
    return builder.as_markup()


def get_yes_no_keyboard(yes_callback: str, no_callback: str, question: str = "Вы уверены?") -> InlineKeyboardMarkup:
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
# КЛАВИАТУРЫ ТАРИФОВ
# =====================================================================

def get_tier_selection_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🛡 Обычный VPN", callback_data="tier_standard", style="primary")
    builder.button(text="🚀 Обход белых списков (VIP)", callback_data="tier_premium", style="primary")
    builder.button(text="Назад ↩️", callback_data="back_to_main", style="danger")
    builder.adjust(1, 1, 1)
    return builder.as_markup()


def get_subscription_duration_keyboard(
    tier: str, price_1m: float, price_3m: float, price_6m: float, price_12m: float, price_test: float
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=f"🥉 3 дня - {int(price_test)}₽", callback_data="duration_test3d", style="primary")
    builder.button(text=f"1 месяц - {int(price_1m)}₽", callback_data="duration_1month", style="primary")
    builder.button(text=f"3 месяца - {int(price_3m)}₽", callback_data="duration_3month", style="primary")
    builder.button(text=f"6 месяцев - {int(price_6m)}₽", callback_data="duration_6month", style="primary")
    builder.button(text=f"12 месяцев - {int(price_12m)}₽", callback_data="duration_12month", style="primary")
    builder.button(text="Назад ↩️", callback_data="buy", style="danger")
    builder.adjust(1, 1, 1, 1, 1, 1)
    return builder.as_markup()


def get_admin_settings_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💵 Цена Обычного ВПН", callback_data="set_price_standard", style="primary")
    builder.button(text="💎 Цена Обхода списков", callback_data="set_price_premium", style="primary")
    builder.button(text="⏳ Настроить скидки", callback_data="set_discounts", style="primary")
    builder.button(text="🔙 Назад", callback_data="admin_panel", style="danger")
    builder.adjust(1, 1, 1, 1)
    return builder.as_markup()


# =====================================================================
# НОВЫЕ: ДОКУПКА ТРАФИКА, ПОДАРКИ, РЕФЕРАЛЬНАЯ ПОКУПКА
# =====================================================================

TRAFFIC_PACKAGES = [
    (50, 50),
    (100, 90),
    (300, 250),
    (500, 400),
]


def get_traffic_buy_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора пакета ГБ для докупки."""
    builder = InlineKeyboardBuilder()
    for gb, price in TRAFFIC_PACKAGES:
        builder.button(text=f"+{gb} ГБ — {price}₽", callback_data=f"traffic_{gb}", style="primary")
    builder.button(text="Назад ↩️", callback_data="back_to_main", style="danger")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def get_gift_tier_keyboard() -> InlineKeyboardMarkup:
    """Выбор тарифа для подарка."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🛡 Обычный VPN", callback_data="gift_tier_standard", style="primary")
    builder.button(text="🚀 VIP Обход белых списков", callback_data="gift_tier_premium", style="primary")
    builder.button(text="Назад ↩️", callback_data="back_to_main", style="danger")
    builder.adjust(1, 1, 1)
    return builder.as_markup()


def get_gift_duration_keyboard(tier: str) -> InlineKeyboardMarkup:
    """Выбор срока подарочной подписки."""
    builder = InlineKeyboardBuilder()
    for months, label in [(1, "1 месяц"), (3, "3 месяца"), (6, "6 месяцев"), (12, "12 месяцев")]:
        builder.button(text=f"🎁 {label}", callback_data=f"gift_dur_{tier}_{months}", style="primary")
    builder.button(text="Назад ↩️", callback_data="gift_start", style="danger")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def get_gift_payment_keyboard(tier: str, months: int, price: int, referral_balance: float = 0) -> InlineKeyboardMarkup:
    """Клавиатура оплаты подарка."""
    builder = InlineKeyboardBuilder()
    builder.button(text="CryptoBot (USDT) 💰", callback_data="gift_pay_crypto", style="primary")
    builder.button(text="Банковская карта 🏦", callback_data="gift_pay_card", style="primary")
    if referral_balance >= price:
        builder.button(text=f"💳 Из реферального баланса ({referral_balance:.0f}₽)", callback_data="gift_pay_referral", style="success")
    builder.button(text="Назад ↩️", callback_data="gift_start", style="danger")
    builder.adjust(1, 1)
    return builder.as_markup()


def get_traffic_payment_keyboard(gb: int, price: int, referral_balance: float = 0) -> InlineKeyboardMarkup:
    """Клавиатура оплаты докупки трафика."""
    builder = InlineKeyboardBuilder()
    builder.button(text="CryptoBot (USDT) 💰", callback_data="traffic_pay_crypto", style="primary")
    builder.button(text="Банковская карта 🏦", callback_data="traffic_pay_card", style="primary")
    if referral_balance >= price:
        builder.button(text=f"💳 Из реферального баланса ({referral_balance:.0f}₽)", callback_data="traffic_pay_referral", style="success")
    builder.button(text="Назад ↩️", callback_data="traffic_buy", style="danger")
    builder.adjust(1, 1)
    return builder.as_markup()

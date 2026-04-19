"""
Модуль inline-клавиатур для бота Nemo VPN.
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import Optional, List


def get_main_menu_keyboard(show_trial: bool = True) -> InlineKeyboardMarkup:
    """
    Главное меню бота.
    """
    builder = InlineKeyboardBuilder()

    # Row 1: Синие кнопки
    builder.button(text="Мой профиль 👤", callback_data="profile", style="primary")
    builder.button(text="Реферальная программа 👥", callback_data="referral", style="primary")
    
    # Row 2: Синие кнопки
    builder.button(text="Подписка 📦", callback_data="subscription", style="primary")
    builder.button(text="Купить подписку 🛒", callback_data="buy", style="primary")
    
    # Row 3: Подарок
    builder.button(text="🎁 Подарить VPN", callback_data="gift_start", style="primary")
    
    # Row 4: Красная кнопка
    builder.button(text="Помощь 🆘", callback_data="help", style="danger")
    
    # Row 5: Зелёная кнопка (только если нет активной подписки)
    if show_trial:
        builder.button(text="Пробная подписка 🎁", callback_data="trial", style="success")
        builder.adjust(2, 2, 1, 1, 1)  # 5 рядов
    else:
        builder.adjust(2, 2, 1, 1)  # 4 ряда

    return builder.as_markup()


def get_profile_keyboard(
    has_subscription: bool = False,
    show_link: bool = False
) -> InlineKeyboardMarkup:
    """
    Клавиатура профиля пользователя.
    """
    builder = InlineKeyboardBuilder()
    
    if show_link and has_subscription:
        builder.button(text="Получить ссылку 🔗", callback_data="get_vless_link", style="primary")
    
    builder.button(text="Реферальная программа 👥", callback_data="referral", style="primary")
    
    if has_subscription:
        builder.button(text="Продлить подписку 💳", callback_data="buy_extend", style="primary")
    
    builder.button(text="Назад ↩️", callback_data="back_to_main", style="danger")
    
    builder.adjust(1, 1)
    return builder.as_markup()


def get_buy_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура выбора способа оплаты.
    """
    builder = InlineKeyboardBuilder()
    
    builder.button(text="CryptoBot (USDT) 💰", callback_data="pay_crypto", style="primary")
    builder.button(text="Банковская карта 🏦", callback_data="pay_card", style="primary")
    builder.button(text="Оплатить с реферального баланса 💰", callback_data="referral", style="primary")
    builder.button(text="Назад ↩️", callback_data="back_to_main", style="danger")
    
    builder.adjust(1, 1)
    return builder.as_markup()


def get_payment_keyboard(invoice_url: str, invoice_id: str) -> InlineKeyboardMarkup:
    """
    Клавиатура для оплаты счета.
    """
    builder = InlineKeyboardBuilder()
    
    builder.button(text="Оплатить 💳", url=invoice_url, style="primary")
    builder.button(text="Проверить оплату ✅", callback_data=f"check_payment:{invoice_id}", style="success")
    builder.button(text="Отмена ❌", callback_data="cancel_payment", style="danger")
    
    builder.adjust(1, 1)
    return builder.as_markup()


def get_trial_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура для активации триала.
    """
    builder = InlineKeyboardBuilder()
    
    builder.button(text="Активировать триал 🚀", callback_data="activate_trial", style="success")
    builder.button(text="Реферальная программа 👥", callback_data="referral", style="primary")
    builder.button(text="Назад ↩️", callback_data="back_to_main", style="danger")
    
    builder.adjust(1, 1)
    return builder.as_markup()


def get_help_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура раздела помощи.
    """
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
    """
    Клавиатура с инструкцией по настройке V2Box.
    """
    builder = InlineKeyboardBuilder()
    
    builder.button(text="Скачать для iOS 🍎", url="https://apps.apple.com/us/app/v2box-v2ray-client/id6446814690", style="primary")
    builder.button(text="Скачать для Android 📱", url="https://play.google.com/store/apps/details?id=dev.hexasoftware.v2box", style="primary")
    builder.button(text="Назад ↩️", callback_data="help", style="danger")
    
    builder.adjust(1, 1, 1)
    return builder.as_markup()


def get_referral_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура реферальной системы.
    """
    builder = InlineKeyboardBuilder()
    
    builder.button(text="Пригласить друга 👥", callback_data="referral_invite", style="primary")
    builder.button(text="Мои рефералы 📊", callback_data="referral_stats", style="primary")
    builder.button(text="Вывод баланса 💸", callback_data="start_withdraw", style="success")
    builder.button(text="Назад ↩️", callback_data="back_to_main", style="danger")
    
    builder.adjust(2, 2)
    return builder.as_markup()


def get_admin_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура админ-панели.
    """
    builder = InlineKeyboardBuilder()
    
    builder.button(text="Статистика 📊", callback_data="admin_stats", style="primary")
    builder.button(text="Пользователи 👥", callback_data="admin_users", style="primary")
    builder.button(text="Рассылка 📢", callback_data="admin_broadcast", style="primary")
    builder.button(text="Настройки ⚙️", callback_data="settings", style="primary")
    builder.button(text="Закрыть панель 🔒", callback_data="admin_close", style="danger")
    
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def get_admin_user_search_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура для поиска пользователя админом.
    """
    builder = InlineKeyboardBuilder()
    
    builder.button(text="Найти по ID 🔍", callback_data="admin_find_by_id", style="primary")
    builder.button(text="Найти по username 👤", callback_data="admin_find_by_username", style="primary")
    builder.button(text="Назад ↩️", callback_data="admin_panel", style="danger")
    
    builder.adjust(1, 1)
    return builder.as_markup()


def get_yes_no_keyboard(
    yes_callback: str,
    no_callback: str,
    question: str = "Вы уверены?"
) -> InlineKeyboardMarkup:
    """
    Универсальная клавиатура с кнопками Да/Нет.
    """
    builder = InlineKeyboardBuilder()
    
    builder.button(text="✅ Да", callback_data=yes_callback, style="success")
    builder.button(text="❌ Нет", callback_data=no_callback, style="danger")
    
    builder.adjust(2)
    return builder.as_markup()


def get_back_keyboard(callback_data: str = "back_to_main") -> InlineKeyboardMarkup:
    """
    Простая клавиатура с кнопкой Назад.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="Назад ↩️", callback_data=callback_data, style="danger")
    return builder.as_markup()

# =====================================================================
# ТРАФИК — пакеты и клавиатуры
# =====================================================================

TRAFFIC_PACKAGES = [
    {"gb": 50, "price": 100},
    {"gb": 100, "price": 200},
    {"gb": 300, "price": 600},
    {"gb": 500, "price": 1000},
]


def get_traffic_payment_keyboard(gb: int, price: int) -> InlineKeyboardMarkup:
    """Клавиатура выбора способа оплаты для докупки трафика."""
    builder = InlineKeyboardBuilder()
    builder.button(text="₿ Крипто", callback_data=f"tpay_crypto_{gb}_{price}")
    builder.button(text="💳 Карта / СБП", callback_data=f"tpay_card_{gb}_{price}")
    builder.button(text="Назад ↩️", callback_data="traffic_buy")
    builder.adjust(2)
    return builder.as_markup()


# =====================================================================
# НОВЫЕ И ИЗМЕНЕННЫЕ КЛАВИАТУРЫ ДЛЯ ТАРИФОВ, ТРАФИКА, ПОДАРКОВ И АДМИНКИ
# =====================================================================

def get_tier_selection_keyboard(has_subscription: bool = False) -> InlineKeyboardMarkup:
    """
    Клавиатура выбора тарифа (Обычный или VIP).
    has_subscription: если True, показывает кнопку "Докупить трафик".
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="🛡 Обычный VPN", callback_data="tier_standard", style="primary")
    builder.button(text="🚀 Обход белых списков (VIP)", callback_data="tier_premium", style="primary")
    
    if has_subscription:
        builder.button(text="📦 Докупить трафик", callback_data="traffic_buy", style="primary")
    
    builder.button(text="Назад ↩️", callback_data="back_to_main", style="danger")
    
    if has_subscription:
        builder.adjust(1, 1, 1, 1)
    else:
        builder.adjust(1, 1, 1)
    return builder.as_markup()


def get_subscription_duration_keyboard(
    tier: str,
    price_1m: float,
    price_3m: float,
    price_6m: float,
    price_12m: float,
    price_test: float
) -> InlineKeyboardMarkup:
    """Клавиатура выбора срока подписки с учетом тарифа и ГБ лимитов."""
    builder = InlineKeyboardBuilder()
    
    test_gb = 3 if tier == "premium" else 3
    gb_1m, gb_3m, gb_6m, gb_12m = 100, 350, 800, 2048
    
    builder.button(text=f"🥉 3 дня — {int(price_test)}₽ ({test_gb} ГБ)", callback_data="duration_test3d", style="primary")
    builder.button(text=f"1 месяц — {int(price_1m)}₽ ({gb_1m} ГБ)", callback_data="duration_1month", style="primary")
    builder.button(text=f"3 месяца — {int(price_3m)}₽ ({gb_3m} ГБ)", callback_data="duration_3month", style="primary")
    builder.button(text=f"6 месяцев — {int(price_6m)}₽ ({gb_6m} ГБ)", callback_data="duration_6month", style="primary")
    builder.button(text=f"12 месяцев — {int(price_12m)}₽ ({gb_12m} ГБ = 2 ТБ)", callback_data="duration_12month", style="primary")
    
    builder.button(text="Назад ↩️", callback_data="buy", style="danger") 
    
    builder.adjust(1, 1, 1, 1, 1, 1)
        
    return builder.as_markup()


def get_traffic_buy_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура выбора пакета дополнительного трафика.
    """
    builder = InlineKeyboardBuilder()
    
    builder.button(text="50 ГБ — 100₽", callback_data="traffic_50", style="primary")
    builder.button(text="100 ГБ — 200₽", callback_data="traffic_100", style="primary")
    builder.button(text="300 ГБ — 600₽", callback_data="traffic_300", style="primary")
    builder.button(text="500 ГБ — 1000₽", callback_data="traffic_500", style="primary")
    builder.button(text="Назад ↩️", callback_data="buy", style="danger")
    
    builder.adjust(1, 1, 1, 1, 1)
    return builder.as_markup()


def get_gift_tier_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура выбора тарифа для подарка.
    """
    builder = InlineKeyboardBuilder()
    
    builder.button(text="🛡 Обычный VPN — 150₽/мес", callback_data="gift_standard", style="primary")
    builder.button(text="🚀 VIP (Обход белых списков) — от 400₽/мес", callback_data="gift_premium", style="primary")
    builder.button(text="Назад ↩️", callback_data="back_to_main", style="danger")
    
    builder.adjust(1, 1, 1)
    return builder.as_markup()


def get_gift_duration_keyboard(tier: str) -> InlineKeyboardMarkup:
    """Клавиатура выбора срока подарочной подписки с GB лимитами."""
    builder = InlineKeyboardBuilder()
    
    if tier == "premium":
        builder.button(text="1 месяц — 400₽ (100 ГБ)", callback_data="gift_dur_30", style="primary")
        builder.button(text="3 месяца — 1050₽ (350 ГБ)", callback_data="gift_dur_90", style="primary")
        builder.button(text="6 месяцев — 1900₽ (800 ГБ)", callback_data="gift_dur_180", style="primary")
        builder.button(text="12 месяцев — 3500₽ (2 ТБ)", callback_data="gift_dur_365", style="primary")
    else:
        builder.button(text="1 месяц — 150₽ (100 ГБ)", callback_data="gift_dur_30", style="primary")
        builder.button(text="3 месяца — 400₽ (350 ГБ)", callback_data="gift_dur_90", style="primary")
        builder.button(text="6 месяцев — 700₽ (800 ГБ)", callback_data="gift_dur_180", style="primary")
        builder.button(text="12 месяцев — 1200₽ (2 ТБ)", callback_data="gift_dur_365", style="primary")
    
    builder.button(text="Назад ↩️", callback_data="gift_start", style="danger")
    
    builder.adjust(1, 1, 1, 1, 1)
    return builder.as_markup()


def get_gift_payment_keyboard(tier: str, days: int, price: int) -> InlineKeyboardMarkup:
    """Клавиатура выбора способа оплаты для подарка."""
    builder = InlineKeyboardBuilder()
    builder.button(text="₿ Крипто", callback_data=f"gpay_crypto_{tier}_{days}_{price}")
    builder.button(text="💳 Карта / СБП", callback_data=f"gpay_card_{tier}_{days}_{price}")
    builder.button(text="Назад ↩️", callback_data="gift_start")
    builder.adjust(2)
    return builder.as_markup()


def get_admin_settings_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура настроек админки для управления ценами.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="💵 Цена Обычного ВПН", callback_data="set_price_standard", style="primary")
    builder.button(text="💎 Цена Обхода списков", callback_data="set_price_premium", style="primary")
    builder.button(text="⏳ Настроить скидки", callback_data="set_discounts", style="primary")
    builder.button(text="🔙 Назад", callback_data="admin_panel", style="danger")
    builder.adjust(1, 1, 1, 1)
    return builder.as_markup()

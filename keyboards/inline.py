"""
Модуль inline-клавиатур для бота Nemo VPN.
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import Optional, List


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """
    Главное меню бота.
    
    Кнопки:
        - Мой профиль 👤
        - Купить подписку 📦
        - Подписка 📦
        - Реферальная программа 👥
        - Помощь 🆘
    """
    builder = InlineKeyboardBuilder()
    
    builder.button(text="Мой профиль 👤", callback_data="profile", style="primary")
    builder.button(text="Купить подписку 📦", callback_data="buy", style="primary")
    builder.button(text="Подписка 📦", callback_data="sub", style="success")
    builder.button(text="Реферальная программа 👥", callback_data="referral", style="primary")
    builder.button(text="Помощь 🆘", callback_data="help", style="primary")
    
    builder.adjust(2, 2, 1)  # 2 кнопки в ряду, потом1
    return builder.as_markup()


def get_profile_keyboard(
    has_subscription: bool = False,
    show_link: bool = False
) -> InlineKeyboardMarkup:
    """
    Клавиатура профиля пользователя.
    
    Args:
        has_subscription: Есть ли активная подписка.
        show_link: Показать кнопку получения ссылки.
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
    
    Кнопки:
        - CryptoBot (USDT/TON) 💰
        - Банковская карта 🏦
        - Реферальная программа 👥
        - Назад ↩️
    """
    builder = InlineKeyboardBuilder()
    
    builder.button(text="CryptoBot (USDT/TON) 💰", callback_data="pay_crypto", style="primary")
    builder.button(text="Банковская карта 🏦", callback_data="pay_card", style="primary")
    builder.button(text="Оплатить с реферального баланса 💰", callback_data="referral", style="primary")
    builder.button(text="Назад ↩️", callback_data="back_to_main", style="danger")
    
    builder.adjust(1, 1)
    return builder.as_markup()


def get_payment_keyboard(invoice_url: str, invoice_id: str) -> InlineKeyboardMarkup:
    """
    Клавиатура для оплаты счета.
    
    Args:
        invoice_url: URL для оплаты.
        invoice_id: ID счета для проверки.
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
    Клавиатура раздела помощи с юридическими документами.
    """
    builder = InlineKeyboardBuilder()
    
    builder.button(text="Как настроить Hiddify 📱", callback_data="help_hiddify", style="primary")
    builder.button(text="Частые вопросы ❓", callback_data="help_faq", style="primary")
    builder.button(text="Реферальная программа 👥", callback_data="referral", style="primary")
    builder.button(text="Техподдержка 💬", callback_data="help_support", style="primary")
    builder.button(text="Политика конфиденциальности 📜", url="https://telegra.ph/Politika-konfidencialnosti-08-15-17")
    builder.button(text="Пользовательское соглашение 📝", url="https://telegra.ph/Polzovatelskoe-soglashenie-08-15-10")
    builder.button(text="Назад ↩️", callback_data="back_to_main", style="danger")
    
    # adjust(1) выстроит все кнопки строго друг под другом (в 1 столбец)
    builder.adjust(1)
    return builder.as_markup()


def get_hiddify_instruction_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура с инструкцией по настройке Hiddify.
    """
    builder = InlineKeyboardBuilder()
    
    builder.button(text="Скачать для Android 📱", url="https://play.google.com/store/apps/details?id=app.hiddify.com", style="primary")
    builder.button(text="Скачать для iOS 🍎", url="https://apps.apple.com/us/app/hiddify-proxy-vpn/id6596777532", style="primary")
    builder.button(text="Скачать для Windows 💻", url="https://github.com/hiddify/hiddify-next/releases", style="primary")
    builder.button(text="Назад ↩️", callback_data="help", style="danger")
    
    builder.adjust(1, 1)
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
    
    Args:
        yes_callback: Callback для кнопки Да.
        no_callback: Callback для кнопки Нет.
        question: Текст вопроса.
    """
    builder = InlineKeyboardBuilder()
    
    builder.button(text="✅ Да", callback_data=yes_callback, style="success")
    builder.button(text="❌ Нет", callback_data=no_callback, style="danger")
    
    builder.adjust(2)
    return builder.as_markup()


def get_subscription_duration_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура выбора срока подписки.
    """
    builder = InlineKeyboardBuilder()
    
    builder.button(text="1 месяц - 100₽", callback_data="duration_1month", style="primary")
    builder.button(text="3 месяца - 270₽", callback_data="duration_3month", style="primary")
    builder.button(text="6 месяцев - 500₽", callback_data="duration_6month", style="primary")
    builder.button(text="12 месяцев - 900₽", callback_data="duration_12month", style="primary")
    builder.button(text="Назад ↩️", callback_data="back_to_main", style="danger")
    
    builder.adjust(1, 1)
    return builder.as_markup()


def get_back_keyboard(callback_data: str = "back_to_main") -> InlineKeyboardMarkup:
    """
    Простая клавиатура с кнопкой Назад.
    
    Args:
        callback_data: Callback для кнопки (по умолчанию "back_to_main").
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="Назад ↩️", callback_data=callback_data, style="danger")
    return builder.as_markup()
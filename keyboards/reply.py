"""
Модуль reply-клавиатур для бота Nemo VPN.
"""

from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder


def get_main_reply_keyboard(show_trial: bool = True) -> ReplyKeyboardMarkup:
    """
    Главное меню с reply-кнопками.
    
    Кнопки:
        - Мой профиль 👤
        - Реферальная программа 👥
        - Подписка 📦
        - Пробная подписка (только если show_trial=True)
        - Купить подписку 📦
        - Помощь 🆘
    
    Args:
        show_trial: Показывать ли кнопку пробной подписки
    """
    builder = ReplyKeyboardBuilder()
    
    builder.button(text="Мой профиль 👤")
    builder.button(text="Реферальная программа 👥")
    builder.button(text="Подписка 📦")
    
    if show_trial:
        builder.button(text="Пробная подписка 🎁")
    
    builder.button(text="Купить подписку 🛒")
    builder.button(text="Помощь 🆘")
    
    builder.adjust(2, 2, 2)
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=False)


def get_admin_reply_keyboard() -> ReplyKeyboardMarkup:
    """
    Админ-панель с reply-кнопками.
    """
    builder = ReplyKeyboardBuilder()
    
    builder.button(text="📊 Статистика")
    builder.button(text="👥 Пользователи")
    builder.button(text="📢 Рассылка")
    builder.button(text="⚙️ Настройки")
    builder.button(text="🔒 Закрыть панель")
    
    builder.adjust(2, 2, 1)
    return builder.as_markup(resize_keyboard=True)


def get_cancel_reply_keyboard() -> ReplyKeyboardMarkup:
    """
    Клавиатура с кнопкой отмены.
    """
    builder = ReplyKeyboardBuilder()
    builder.button(text="❌ Отмена")
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def get_yes_no_reply_keyboard() -> ReplyKeyboardMarkup:
    """
    Клавиатура с кнопками Да/Нет.
    """
    builder = ReplyKeyboardBuilder()
    builder.button(text="✅ Да")
    builder.button(text="❌ Нет")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)

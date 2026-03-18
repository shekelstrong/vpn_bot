"""
Настройки бота.
Управление тарифами реферальной системой, триалом и пользователями.
"""

from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from database.models import User, BotSettings
from keyboards.inline import (
    get_back_keyboard,
    get_main_menu_keyboard,
)
from config import settings, get_db_setting, update_db_setting


router = Router(name="settings_router")


def is_admin(user_id: int) -> bool:
    """Проверить, является ли пользователь администратором."""
    return user_id in settings.admin_ids_list


def get_settings_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура настроек."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Тарифы подписки", callback_data="settings_tariffs")],
        [InlineKeyboardButton(text="👥 Реферальная система", callback_data="settings_referral")],
        [InlineKeyboardButton(text="🎁 Бесплатный триал", callback_data="settings_trial")],
        [InlineKeyboardButton(text="🎨 Скидки на тарифы", callback_data="settings_discounts")],
        [InlineKeyboardButton(text="🔧 Управление пользователями", callback_data="settings_users")],
        [InlineKeyboardButton(text="Назад ↩️", callback_data="admin_panel")]
    ])
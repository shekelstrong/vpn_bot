"""
Настройки бота.
Управление тарифами реферальной системой, триалом и пользователями.
"""

from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
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


class SettingsStates(StatesGroup):
    """Состояния для FSM настроек."""
    waiting_for_price = State()


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


@router.callback_query(F.data == "settings")
async def show_settings(callback: CallbackQuery):
    """Показать меню настроек."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет прав", show_alert=True)
        return
    
    await callback.message.edit_text(
        text="⚙️ <b>Настройки бота</b>\n\nВыберите раздел для редактирования:",
        reply_markup=get_settings_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "settings_tariffs")
async def show_tariff_settings(callback: CallbackQuery, session: AsyncSession):
    """Показать настройки тарифов."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет прав", show_alert=True)
        return
    
    subscription_price = await get_db_setting(session, "subscription_price", "100")
    
    text = (
        "💰 <b>Настройки тарифов</b>\n\n"
        f"Текущая цена подписки (1 месяц): <b>{subscription_price}₽</b>\n\n"
        "Цены на 3, 6 и 12 месяцев рассчитываются автоматически\n"
        "с учетом настроенных скидок."
    )
    
    await callback.message.edit_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Изменить цену подписки", callback_data="edit_subscription_price")],
            [InlineKeyboardButton(text="↩️ Назад", callback_data="settings")]
        ])
    )
    await callback.answer()


@router.callback_query(F.data == "edit_subscription_price")
async def edit_subscription_price(callback: CallbackQuery, state: FSMContext):
    """Начало редактирования цены подписки."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет прав", show_alert=True)
        return
    
    await callback.message.edit_text(
        text="💰 <b>Изменение цены подписки</b>\n\n"
        "Введите новую цену подписки (в рублях):\n\n"
        "⚠️ После изменения цены автоматически обновятся\n"
        "все тарифы (1, 3, 6, 12 месяцев).",
        reply_markup=get_back_keyboard("settings_tariffs")
    )
    await state.set_state(SettingsStates.waiting_for_price)
    await callback.answer()


@router.message(SettingsStates.waiting_for_price, F.text)
async def process_price_change(message: types.Message, state: FSMContext, session: AsyncSession):
    """Обработка новой цены."""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет прав")
        await state.clear()
        return
    
    try:
        new_price = float(message.text)
        if new_price <= 0:
            await message.answer("❌ Цена должна быть положительным числом!")
            return
        
        await update_db_setting(session, "subscription_price", str(new_price), "Цена подписки в рублях")
        
        await message.answer(
            text=f"✅ <b>Цена подписки изменена!</b>\n\n"
            f"Новая цена: {new_price}₽\n\n"
            "Цены на все тарифы автоматически обновлены.\n"
            "Изменения вступят в силу сразу.",
            reply_markup=get_settings_keyboard()
        )
        logger.info(f"Админ {message.from_user.id} изменил цену подписки на {new_price}₽")
        
    except ValueError:
        await message.answer("❌ Неверный формат! Введите число.")
    
    await state.clear()


@router.callback_query(F.data == "settings_referral")
async def show_referral_settings(callback: CallbackQuery):
    """Показать настройки реферальной системы."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет прав", show_alert=True)
        return
    
    await callback.message.edit_text(
        text="👥 <b>Настройки реферальной системы</b>\n\n"
        "Функция в разработке...",
        reply_markup=get_back_keyboard("settings")
    )
    await callback.answer()


@router.callback_query(F.data == "settings_trial")
async def show_trial_settings(callback: CallbackQuery):
    """Показать настройки триала."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет прав", show_alert=True)
        return
    
    await callback.message.edit_text(
        text="🎁 <b>Настройки бесплатного триала</b>\n\n"
        "Функция в разработке...",
        reply_markup=get_back_keyboard("settings")
    )
    await callback.answer()


@router.callback_query(F.data == "settings_discounts")
async def show_discount_settings(callback: CallbackQuery):
    """Показать настройки скидок."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет прав", show_alert=True)
        return
    
    await callback.message.edit_text(
        text="🎨 <b>Настройки скидок</b>\n\n"
        "Функция в разработке...",
        reply_markup=get_back_keyboard("settings")
    )
    await callback.answer()


@router.callback_query(F.data == "settings_users")
async def show_user_management(callback: CallbackQuery):
    """Показать управление пользователями."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет прав", show_alert=True)
        return
    
    await callback.message.edit_text(
        text="🔧 <b>Управление пользователями</b>\n\n"
        "Функция в разработке...",
        reply_markup=get_back_keyboard("settings")
    )
    await callback.answer()
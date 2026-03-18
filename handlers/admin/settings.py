"""
Настройки бота в админ-панели.
Управление тарифами, реферальной системой, триалом и пользователями.
"""

from aiogram import Router, F, types
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from database.models import User, BotSettings
from config import settings, get_db_setting, update_db_setting
from utils.states import AdminSettings

router = Router()


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


def get_tariffs_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура настройки тарифов."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Цена подписки", callback_data="tariff_price")],
        [InlineKeyboardButton(text="Срок подписки", callback_data="tariff_duration")],
        [InlineKeyboardButton(text="Назад ↩️", callback_data="settings")]
    ])


def get_referral_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура настройки рефералов."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Процент уровня 1", callback_data="referral_level1")],
        [InlineKeyboardButton(text="Процент уровня 2", callback_data="referral_level2")],
        [InlineKeyboardButton(text="Процент уровня 3", callback_data="referral_level3")],
        [InlineKeyboardButton(text="Мин. сумма вывода", callback_data="referral_min_withdraw")],
        [InlineKeyboardButton(text="Назад ↩️", callback_data="settings")]
    ])


def get_trial_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура настройки триала."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Срок действия (часы)", callback_data="trial_hours")],
        [InlineKeyboardButton(text="Лимит трафика (GB)", callback_data="trial_data_limit")],
        [InlineKeyboardButton(text="Назад ↩️", callback_data="settings")]
    ])


def get_users_management_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура управления пользователями."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Найти пользователя", callback_data="admin_find_by_id")],
        [InlineKeyboardButton(text="Назад ↩️", callback_data="admin_panel")]
    ])


def get_discounts_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура настройки скидок."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="3 месяца", callback_data="discount_3month")],
        [InlineKeyboardButton(text="6 месяцев", callback_data="discount_6month")],
        [InlineKeyboardButton(text="12 месяцев", callback_data="discount_12month")],
        [InlineKeyboardButton(text="Назад ↩️", callback_data="settings")]
    ])


@router.callback_query(F.data == "admin_settings")
async def admin_settings(callback: CallbackQuery):
    """Настройки бота."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    await callback.message.edit_text(
        text="⚙️ <b>Настройки</b>\n\nВыберите раздел:",
        reply_markup=get_settings_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "settings")
async def settings_menu(callback: CallbackQuery):
    """Меню настроек."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    await callback.message.edit_text(
        text="⚙️ <b>Настройки</b>\n\nВыберите раздел:",
        reply_markup=get_settings_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "settings_tariffs")
async def settings_tariffs(callback: CallbackQuery, session: AsyncSession):
    """Настройки тарифов."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    price = await get_db_setting(session, "subscription_price", "100")
    duration = await get_db_setting(session, "subscription_duration", "30")
    
    text = (
        f"💰 <b>Тарифы подписки</b>\n\n"
        f"<b>Цена подписки:</b> {price}₽\n"
        f"<b>Срок подписки:</b> {duration} дней\n\n"
        f"Выберите параметр для изменения:"
    )
    
    await callback.message.edit_text(text, reply_markup=get_tariffs_keyboard(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "settings_referral")
async def settings_referral(callback: CallbackQuery, session: AsyncSession):
    """Настройки реферальной системы."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    level1 = await get_db_setting(session, "referral_level1", "15")
    level2 = await get_db_setting(session, "referral_level2", "10")
    level3 = await get_db_setting(session, "referral_level3", "5")
    min_withdraw = await get_db_setting(session, "referral_min_withdraw", "1000")
    
    text = (
        f"👥 <b>Реферальная система</b>\n\n"
        f"<b>Уровень 1:</b> {level1}%\n"
        f"<b>Уровень 2:</b> {level2}%\n"
        f"<b>Уровень 3:</b> {level3}%\n"
        f"<b>Мин. сумма вывода:</b> {min_withdraw}₽\n\n"
        f"Выберите параметр для изменения:"
    )
    
    await callback.message.edit_text(text, reply_markup=get_referral_keyboard(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "settings_trial")
async def settings_trial(callback: types.CallbackQuery, session: AsyncSession):
    """Настройки триала."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    hours = await get_db_setting(session, "trial_hours", "24")
    data_limit = await get_db_setting(session, "trial_data_limit", "1")
    
    text = (
        f"🎁 <b>Бесплатный триал</b>\n\n"
        f"<b>Срок действия:</b> {hours} часов\n"
        f"<b>Лимит трафика:</b> {data_limit} GB\n\n"
        f"Выберите параметр для изменения:"
    )
    
    await callback.message.edit_text(text, reply_markup=get_trial_keyboard(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "settings_discounts")
async def settings_discounts(callback: types.CallbackQuery, session: AsyncSession):
    """Настройки скидок."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    discount_3month = await get_db_setting(session, "discount_3month", "10")
    discount_6month = await get_db_setting(session, "discount_6month", "17")
    discount_12month = await get_db_setting(session, "discount_12month", "25")
    
    text = (
        f"🎨 <b>Скидки на тарифы</b>\n\n"
        f"<b>На 3 месяца:</b> {discount_3month}%\n"
        f"<b>На 6 месяцев:</b> {discount_6month}%\n"
        f"<b>На 12 месяцев:</b> {discount_12month}%\n\n"
        f"Выберите параметр для изменения:"
    )
    
    await callback.message.edit_text(text, reply_markup=get_discounts_keyboard(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "settings_users")
async def settings_users(callback: types.CallbackQuery):
    """Управление пользователями."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    text = (
        f"🔧 <b>Управление пользователями</b>\n\n"
        f"Найдите пользователя по Telegram ID для:\n"
        f"• Продления подписки\n"
        f"• Сброса триала\n"
        f"• Изменения баланса"
    )
    
    await callback.message.edit_text(text, reply_markup=get_users_management_keyboard(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "settings_users")
async def settings_users(callback: CallbackQuery):
    """Управление пользователями."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    text = (
        f"🔧 <b>Управление пользователями</b>\n\n"
        f"Найдите пользователя по Telegram ID для:\n"
        f"• Продления подписки\n"
        f"• Сброса триала\n"
        f"• Изменения баланса"
    )
    
    await callback.message.edit_text(text, reply_markup=get_users_management_keyboard(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "tariff_price")
@router.callback_query(F.data == "tariff_duration")
async def edit_tariff(callback: types.CallbackQuery, state: FSMContext):
    """Редактирование тарифа."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    action = callback.data.split("_")[1]
    await state.set_state(AdminSettings.waiting_for_tariff_value)
    await state.update_data(tariff_type=action)
    
    if action == "price":
        text = "💰 Введите новую цену подписки (в рублях):"
    else:
        text = "📅 Введите новый срок подписки (в днях):"
    
    await callback.message.answer(text)
    await callback.answer()


@router.callback_query(F.data == "referral_level1")
@router.callback_query(F.data == "referral_level2")
@router.callback_query(F.data == "referral_level3")
@router.callback_query(F.data == "referral_min_withdraw")
async def edit_referral(callback: types.CallbackQuery, state: FSMContext):
    """Редактирование реферальной системы."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    action = callback.data.split("_")[1]
    await state.set_state(AdminSettings.waiting_for_referral_value)
    await state.update_data(referral_type=action)
    
    if action == "min_withdraw":
        text = "💸 Введите новую минимальную сумму вывода (в рублях):"
    else:
        level_num = action.replace("level", "")
        text = f"📊 Введите новый процент для уровня {level_num} (0-100):"
    
    await callback.message.answer(text)
    await callback.answer()


@router.callback_query(F.data == "trial_hours")
@router.callback_query(F.data == "trial_data_limit")
async def edit_trial(callback: types.CallbackQuery, state: FSMContext):
    """Редактирование триала."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    action = callback.data.split("_")[1]
    await state.set_state(AdminSettings.waiting_for_trial_value)
    await state.update_data(trial_type=action)
    
    text = "⏰ Введите новый срок действия триала (в часах):" if action == "hours" else "📦 Введите новый лимит трафика для триала (в GB):"
    
    await callback.message.answer(text)
    await callback.answer()


@router.callback_query(F.data == "discount_3month")
@router.callback_query(F.data == "discount_6month")
@router.callback_query(F.data == "discount_12month")
async def edit_discount(callback: types.CallbackQuery, state: FSMContext):
    """Редактирование скидок."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    action = callback.data.split("_")[1]
    await state.set_state(AdminSettings.waiting_for_discount_value)
    await state.update_data(discount_type=action)
    
    months_map = {
        "3month": "3 месяца",
        "6month": "6 месяцев",
        "12month": "12 месяцев"
    }
    text = f"🎨 Введите новую скидку на {months_map.get(action, action)} (в процентах, 0-100):"
    
    await callback.message.answer(text)
    await callback.answer()


@router.callback_query(F.data == "referral_level1")
@router.callback_query(F.data == "referral_level2")
@router.callback_query(F.data == "referral_level3")
@router.callback_query(F.data == "referral_min_withdraw")
async def edit_referral(callback: CallbackQuery, state: FSMContext):
    """Редактирование реферальной системы."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    action = callback.data.split("_")[1]
    await state.set_state(AdminSettings.waiting_for_referral_value)
    await state.update_data(referral_type=action)
    
    if action == "min_withdraw":
        text = "💸 Введите новую минимальную сумму вывода (в рублях):"
    else:
        level_num = action.replace("level", "")
        text = f"📊 Введите новый процент для уровня {level_num} (0-100):"
    
    await callback.message.answer(text)
    await callback.answer()


@router.callback_query(F.data == "trial_hours")
@router.callback_query(F.data == "trial_data_limit")
async def edit_trial(callback: CallbackQuery, state: FSMContext):
    """Редактирование триала."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    action = callback.data.split("_")[1]
    await state.set_state(AdminSettings.waiting_for_trial_value)
    await state.update_data(trial_type=action)
    
    text = "⏰ Введите новый срок действия триала (в часах):" if action == "hours" else "📦 Введите новый лимит трафика для триала (в GB):"
    
    await callback.message.answer(text)
    await callback.answer()


@router.message(AdminSettings.waiting_for_tariff_value)
async def process_tariff_value(message: types.Message, state: FSMContext, session: AsyncSession):
    """Обработка нового значения тарифа."""
    if not is_admin(message.from_user.id):
        return
    
    try:
        value = int(message.text.strip())
        
        if value <= 0:
            await message.answer("❌ Значение должно быть положительным числом.")
            return
        
        data = await state.get_data()
        tariff_type = data.get("tariff_type")
        
        if tariff_type == "price":
            key = "subscription_price"
            desc = "Цена подписки в рублях"
            await update_db_setting(session, key, str(value), desc)
            await message.answer(
                f"✅ Цена подписки изменена на {value}₽\n\n"
                f"🔄 Цены всех тарифов автоматически пересчитаны с учетом скидок."
            )
        else:
            key = "subscription_duration"
            desc = "Базовый срок подписки в днях"
            await update_db_setting(session, key, str(value), desc)
            await message.answer(f"✅ Срок подписки изменен на {value} дней")
        
        await state.clear()
        
    except ValueError:
        await message.answer("❌ Пожалуйста, введите корректное число.")


@router.message(AdminSettings.waiting_for_discount_value)
async def process_discount_value(message: types.Message, state: FSMContext, session: AsyncSession):
    """Обработка нового значения скидки."""
    if not is_admin(message.from_user.id):
        return
    
    try:
        value = int(message.text.strip())
        
        if value < 0 or value > 100:
            await message.answer("❌ Скидка должна быть от 0 до 100%.")
            return
        
        data = await state.get_data()
        discount_type = data.get("discount_type")
        
        months_map = {
            "3month": "3 месяца",
            "6month": "6 месяцев",
            "12month": "12 месяцев"
        }
        key = f"discount_{discount_type}"
        desc = f"Скидка на {months_map.get(discount_type, discount_type)} (в процентах)"
        
        await update_db_setting(session, key, str(value), desc)
        await message.answer(f"✅ Скидка на {months_map.get(discount_type, discount_type)} изменена на {value}%")
        await state.clear()
        
    except ValueError:
        await message.answer("❌ Пожалуйста, введите корректное число.")


@router.message(AdminSettings.waiting_for_referral_value)
async def process_referral_value(message: types.Message, state: FSMContext, session: AsyncSession):
    """Обработка нового значения реферальной системы."""
    if not is_admin(message.from_user.id):
        return
    
    try:
        value = int(message.text.strip())
        data = await state.get_data()
        referral_type = data.get("referral_type")
        
        if value < 0 or value > 100:
            await message.answer("❌ Процент должен быть от 0 до 100.")
            return
        
        if referral_type == "min_withdraw":
            key = "referral_min_withdraw"
            desc = "Минимальная сумма вывода в рублях"
            await update_db_setting(session, key, str(value), desc)
            await message.answer(f"✅ Минимальная сумма вывода изменена на {value}₽")
        else:
            key = f"referral_{referral_type}"
            level_num = referral_type.replace("level", "")
            desc = f"Процент рефералов уровня {level_num}"
            await update_db_setting(session, key, str(value), desc)
            await message.answer(f"✅ Процент уровня {level_num} изменен на {value}%")
        
        await state.clear()
        
    except ValueError:
        await message.answer("❌ Пожалуйста, введите корректное число.")


@router.message(AdminSettings.waiting_for_trial_value)
async def process_trial_value(message: types.Message, state: FSMContext, session: AsyncSession):
    """Обработка нового значения триала."""
    if not is_admin(message.from_user.id):
        return
    
    try:
        value = int(message.text.strip())
        data = await state.get_data()
        trial_type = data.get("trial_type")
        
        if value <= 0:
            await message.answer("❌ Значение должно быть положительным числом.")
            return
        
        if trial_type == "hours":
            key = "trial_hours"
            desc = "Срок действия триала в часах"
            await update_db_setting(session, key, str(value), desc)
            await message.answer(f"✅ Срок действия триала изменен на {value} часов")
        else:
            key = "trial_data_limit"
            desc = "Лимит трафика для триала в GB"
            await update_db_setting(session, key, str(value), desc)
            await message.answer(f"✅ Лимит трафика триала изменен на {value} GB")
        
        await state.clear()
        
    except ValueError:
        await message.answer("❌ Пожалуйста, введите корректное число.")

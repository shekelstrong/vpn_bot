import asyncio
from datetime import datetime, timedelta
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
from services.marzban_api import marzban_service

router = Router(name="settings_router")

class SettingsStates(StatesGroup):
    """Состояния для FSM настроек."""
    waiting_for_price = State()
    waiting_for_premium_price = State()  # Для VIP тарифа
    waiting_for_referral = State()
    waiting_for_trial = State()
    waiting_for_discount = State()

def is_admin(user_id: int) -> bool:
    """Проверить, является ли пользователь администратором."""
    return user_id in settings.admin_ids_list

def get_settings_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура настроек."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Тарифы подписки", callback_data="settings_tariffs")],
        [InlineKeyboardButton(text="👥 Реферальная система", callback_data="settings_referral")],
        [InlineKeyboardButton(text="🎁 Бесплатный триал", callback_data="settings_trial")],
        [InlineKeyboardButton(text="💸 Скидки на тарифы", callback_data="settings_discounts")],
        [InlineKeyboardButton(text="👥 Управление пользователями", callback_data="settings_users")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")]
    ])

@router.callback_query(F.data == "settings")
async def show_settings(callback: CallbackQuery):
    """Показать меню настроек."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ У вас нет прав", show_alert=True)
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
        await callback.answer("❌ У вас нет прав", show_alert=True)
        return

    subscription_price = await get_db_setting(session, "subscription_price", "100")
    premium_price = await get_db_setting(session, "premium_subscription_price", "300")

    text = (
        "📊 <b>Настройки тарифов</b>\n\n"
        f"🛡 Обычный VPN (1 месяц): <b>{subscription_price}₽</b>\n"
        f"🚀 VIP Обход списков (1 месяц): <b>{premium_price}₽</b>\n\n"
        "💡 Цены на 3, 6 и 12 месяцев рассчитываются автоматически\n"
        "с учетом настроенных скидок."
    )

    await callback.message.edit_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Изменить цену Обычного VPN", callback_data="edit_subscription_price")],
            [InlineKeyboardButton(text="✏️ Изменить цену VIP тарифа", callback_data="edit_premium_price")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="settings")]
        ])
    )
    await callback.answer()

@router.callback_query(F.data == "edit_subscription_price")
async def edit_subscription_price(callback: CallbackQuery, state: FSMContext):
    """Начало редактирования цены подписки Обычного VPN."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ У вас нет прав", show_alert=True)
        return

    await callback.message.edit_text(
        text="✏️ <b>Изменение цены Обычного VPN</b>\n\n"
             "Введите новую цену подписки (в рублях):\n\n"
             "⚠️ После изменения цены автоматически обновятся\n"
             "все тарифы (1, 3, 6, 12 месяцев).",
        reply_markup=get_back_keyboard("settings_tariffs")
    )
    await state.set_state(SettingsStates.waiting_for_price)
    await callback.answer()

@router.message(SettingsStates.waiting_for_price, F.text)
async def process_price_change(message: types.Message, state: FSMContext, session: AsyncSession):
    """Обработка новой цены Обычного VPN."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав")
        await state.clear()
        return

    try:
        new_price = float(message.text)
        if new_price <= 0:
            await message.answer("❌ Цена должна быть положительным числом!")
            return

        await update_db_setting(session, "subscription_price", str(new_price), "Цена подписки в рублях")

        await message.answer(
            text=f"✅ <b>Цена Обычного VPN изменена!</b>\n\n"
                 f"Новая цена: {new_price}₽\n\n"
                 "Цены на все тарифы автоматически обновлены.\n"
                 "Изменения вступят в силу сразу.",
            reply_markup=get_settings_keyboard()
        )
        logger.info(f"Админ {message.from_user.id} изменил цену Обычного VPN на {new_price}₽")
        await state.clear()

    except ValueError:
        await message.answer("❌ Неверный формат! Введите число.")
        await state.clear()

@router.callback_query(F.data == "edit_premium_price")
async def edit_premium_price(callback: CallbackQuery, state: FSMContext):
    """Начало редактирования цены VIP тарифа."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ У вас нет прав", show_alert=True)
        return

    await callback.message.edit_text(
        text="✏️ <b>Изменение цены VIP тарифа (Обход списков)</b>\n\n"
             "Введите новую цену подписки (в рублях):\n\n"
             "⚠️ После изменения цены автоматически обновятся\n"
             "все тарифы (1, 3, 6, 12 месяцев).",
        reply_markup=get_back_keyboard("settings_tariffs")
    )
    await state.set_state(SettingsStates.waiting_for_premium_price)
    await callback.answer()

@router.message(SettingsStates.waiting_for_premium_price, F.text)
async def process_premium_price_change(message: types.Message, state: FSMContext, session: AsyncSession):
    """Обработка новой цены VIP тарифа."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав")
        await state.clear()
        return

    try:
        new_price = float(message.text)
        if new_price <= 0:
            await message.answer("❌ Цена должна быть положительным числом!")
            return

        await update_db_setting(session, "premium_subscription_price", str(new_price), "Цена VIP подписки в рублях")

        await message.answer(
            text=f"✅ <b>Цена VIP тарифа изменена!</b>\n\n"
                 f"Новая цена: {new_price}₽\n\n"
                 "Цены на все тарифы автоматически обновлены.\n"
                 "Изменения вступят в силу сразу.",
            reply_markup=get_settings_keyboard()
        )
        logger.info(f"Админ {message.from_user.id} изменил цену VIP VPN на {new_price}₽")
        await state.clear()

    except ValueError:
        await message.answer("❌ Неверный формат! Введите число.")
        await state.clear()

@router.callback_query(F.data == "settings_referral")
async def show_referral_settings(callback: CallbackQuery, session: AsyncSession):
    """Показать настройки реферальной системы."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ У вас нет прав", show_alert=True)
        return

    level1 = await get_db_setting(session, "referral_level1", "15")
    level2 = await get_db_setting(session, "referral_level2", "10")
    level3 = await get_db_setting(session, "referral_level3", "5")
    min_withdraw = await get_db_setting(session, "referral_min_withdraw", "1000")

    text = (
        "👥 <b>Настройки реферальной системы</b>\n\n"
        f"Уровень 1: <b>{level1}%</b>\n"
        f"Уровень 2: <b>{level2}%</b>\n"
        f"Уровень 3: <b>{level3}%</b>\n"
        f"Мин. вывод: <b>{min_withdraw}₽</b>"
    )

    await callback.message.edit_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Изменить уровни", callback_data="edit_referral_levels")],
            [InlineKeyboardButton(text="✏️ Мин. вывод", callback_data="edit_referral_min_withdraw")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="settings")]
        ])
    )
    await callback.answer()

@router.callback_query(F.data == "settings_trial")
async def show_trial_settings(callback: CallbackQuery, session: AsyncSession):
    """Показать настройки триала."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ У вас нет прав", show_alert=True)
        return

    trial_hours = await get_db_setting(session, "trial_hours", "24")
    trial_data_limit = await get_db_setting(session, "trial_data_limit", "1")

    text = (
        "🎁 <b>Настройки бесплатного триала</b>\n\n"
        f"Срок действия: <b>{trial_hours} часов</b>\n"
        f"Лимит трафика: <b>{trial_data_limit} GB</b>"
    )

    await callback.message.edit_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Изменить срок", callback_data="edit_trial_hours")],
            [InlineKeyboardButton(text="✏️ Изменить лимит", callback_data="edit_trial_limit")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="settings")]
        ])
    )
    await callback.answer()

@router.callback_query(F.data == "settings_discounts")
async def show_discount_settings(callback: CallbackQuery, session: AsyncSession):
    """Показать настройки скидок."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ У вас нет прав", show_alert=True)
        return

    discount_3m = await get_db_setting(session, "discount_3month", "10")
    discount_6m = await get_db_setting(session, "discount_6month", "17")
    discount_12m = await get_db_setting(session, "discount_12month", "25")

    text = (
        "💸 <b>Настройки скидок на тарифы</b>\n\n"
        f"3 месяца: <b>{discount_3m}%</b>\n"
        f"6 месяцев: <b>{discount_6m}%</b>\n"
        f"12 месяцев: <b>{discount_12m}%</b>"
    )

    await callback.message.edit_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ 3 месяца", callback_data="edit_discount_3month")],
            [InlineKeyboardButton(text="✏️ 6 месяцев", callback_data="edit_discount_6month")],
            [InlineKeyboardButton(text="✏️ 12 месяцев", callback_data="edit_discount_12month")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="settings")]
        ])
    )
    await callback.answer()

@router.callback_query(F.data == "settings_users")
async def show_user_management(callback: CallbackQuery):
    """Показать управление пользователями."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ У вас нет прав", show_alert=True)
        return

    await callback.message.edit_text(
        text="👥 <b>Управление пользователями</b>\n\nВыберите действие:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Найти пользователя", callback_data="admin_users")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="settings")]
        ])
    )
    await callback.answer()

@router.callback_query(F.data.startswith("edit_referral"))
async def edit_referral_settings(callback: CallbackQuery, state: FSMContext):
    """Начало редактирования реферальных настроек."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ У вас нет прав", show_alert=True)
        return

    setting_key = callback.data.replace("edit_referral_", "")

    if setting_key == "levels":
        await callback.message.edit_text(
            text="✏️ <b>Редактирование уровней реферальной системы</b>\n\n"
                 "Введите 3 числа через запятую (уровень 1, уровень 2, уровень 3):\n"
                 "Пример: 15, 10, 5",
            reply_markup=get_back_keyboard("settings_referral")
        )
        await state.set_state(SettingsStates.waiting_for_referral)
        await state.update_data(setting_type="levels")

    elif setting_key == "min_withdraw":
        await callback.message.edit_text(
            text="✏️ <b>Минимальная сумма вывода</b>\n\n"
                 "Введите минимальную сумму вывода в рублях:",
            reply_markup=get_back_keyboard("settings_referral")
        )
        await state.set_state(SettingsStates.waiting_for_referral)
        await state.update_data(setting_type="min_withdraw")

    await callback.answer()

@router.callback_query(F.data.startswith("edit_trial"))
async def edit_trial_settings(callback: CallbackQuery, state: FSMContext):
    """Начало редактирования настроек триала."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ У вас нет прав", show_alert=True)
        return

    setting_key = callback.data.replace("edit_trial_", "")

    if setting_key == "hours":
        await callback.message.edit_text(
            text="✏️ <b>Срок действия триала</b>\n\n"
                 "Введите количество часов:",
            reply_markup=get_back_keyboard("settings_trial")
        )
        await state.set_state(SettingsStates.waiting_for_trial)
        await state.update_data(setting_type="hours")

    elif setting_key == "limit":
        await callback.message.edit_text(
            text="✏️ <b>Лимит трафика триала</b>\n\n"
                 "Введите лимит трафика в GB:",
            reply_markup=get_back_keyboard("settings_trial")
        )
        await state.set_state(SettingsStates.waiting_for_trial)
        await state.update_data(setting_type="limit")

    await callback.answer()

@router.callback_query(F.data.startswith("edit_discount"))
async def edit_discount_settings(callback: CallbackQuery, state: FSMContext):
    """Начало редактирования скидок."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ У вас нет прав", show_alert=True)
        return

    discount_key = callback.data.replace("edit_discount_", "")
    discount_names = {
        "3month": "3 месяца",
        "6month": "6 месяцев",
        "12month": "12 месяцев"
    }

    await callback.message.edit_text(
        text=f"✏️ <b>Скидка на {discount_names[discount_key]}</b>\n\n"
             "Введите процент скидки (0-100):",
        reply_markup=get_back_keyboard("settings_discounts")
    )
    await state.set_state(SettingsStates.waiting_for_discount)
    await state.update_data(setting_type=discount_key)
    await callback.answer()

@router.message(SettingsStates.waiting_for_referral, F.text)
async def process_referral_change(message: types.Message, state: FSMContext, session: AsyncSession):
    """Обработка изменения реферальных настроек."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав")
        await state.clear()
        return

    data = await state.get_data()
    setting_type = data.get("setting_type")

    try:
        if setting_type == "levels":
            parts = [int(x.strip()) for x in message.text.split(",")]
            if len(parts) != 3:
                await message.answer("❌ Введите 3 числа через запятую!")
                return

            await update_db_setting(session, "referral_level1", str(parts[0]), "Процент рефералов уровня 1")
            await update_db_setting(session, "referral_level2", str(parts[1]), "Процент рефералов уровня 2")
            await update_db_setting(session, "referral_level3", str(parts[2]), "Процент рефералов уровня 3")

            text = (f"✅ <b>Уровни обновлены!</b>\n\n"
                    f"Уровень 1: {parts[0]}%\n"
                    f"Уровень 2: {parts[1]}%\n"
                    f"Уровень 3: {parts[2]}%")

        elif setting_type == "min_withdraw":
            value = int(message.text)
            if value <= 0:
                await message.answer("❌ Сумма должна быть положительным числом!")
                return

            await update_db_setting(session, "referral_min_withdraw", str(value), "Минимальная сумма вывода в рублях")
            text = f"✅ <b>Минимальная сумма вывода изменена!</b>\n\n{value}₽"

        await message.answer(text=text, reply_markup=get_settings_keyboard())
        logger.info(f"Админ {message.from_user.id} изменил реферальные настройки: {message.text}")
        await state.clear()

    except ValueError:
        await message.answer("❌ Неверный формат!")
        await state.clear()

@router.message(SettingsStates.waiting_for_trial, F.text)
async def process_trial_change(message: types.Message, state: FSMContext, session: AsyncSession):
    """Обработка изменения настроек триала."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав")
        await state.clear()
        return

    data = await state.get_data()
    setting_type = data.get("setting_type")

    try:
        value = int(message.text)
        if value <= 0:
            await message.answer("❌ Значение должно быть положительным числом!")
            return

        if setting_type == "hours":
            await update_db_setting(session, "trial_hours", str(value), "Срок действия триала в часах")
            text = f"✅ <b>Срок триала изменен!</b>\n\n{value} часов"
        elif setting_type == "limit":
            await update_db_setting(session, "trial_data_limit", str(value), "Лимит трафика для триала в GB")
            text = f"✅ <b>Лимит трафика изменен!</b>\n\n{value} GB"

        await message.answer(text=text, reply_markup=get_settings_keyboard())
        logger.info(f"Админ {message.from_user.id} изменил настройки триала: {setting_type}={value}")
        await state.clear()

    except ValueError:
        await message.answer("❌ Неверный формат! Введите целое число.")
        await state.clear()

@router.message(SettingsStates.waiting_for_discount, F.text)
async def process_discount_change(message: types.Message, state: FSMContext, session: AsyncSession):
    """Обработка изменения скидок."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав")
        await state.clear()
        return

    data = await state.get_data()
    setting_type = data.get("setting_type")

    try:
        value = float(message.text)
        if value < 0 or value > 100:
            await message.answer("❌ Скидка должна быть от 0 до 100!")
            return

        await update_db_setting(session, f"discount_{setting_type}", str(value), f"Скидка на {setting_type}")

        await message.answer(
            text=f"✅ <b>Скидка изменена!</b>\n\n{value}%",
            reply_markup=get_settings_keyboard()
        )
        logger.info(f"Админ {message.from_user.id} изменил скидку: {setting_type}={value}")
        await state.clear()

    except ValueError:
        await message.answer("❌ Неверный формат! Введите число.")
        await state.clear()

@router.message(Command("bonus7"))
async def cmd_bonus7(message: types.Message, session: AsyncSession):
    """Секретная команда для выдачи 7 дней всем активным пользователям."""
    if not is_admin(message.from_user.id):
        return

    await message.answer("🎁 <b>Начинаю начисление 7 дней всем активным пользователям...</b>\nЭто может занять некоторое время.", parse_mode="HTML")

    now = datetime.utcnow()

    # Ищем всех, у кого подписка еще не истекла
    result = await session.execute(select(User).where(User.expire_date > now))
    active_users = result.scalars().all()

    if not active_users:
        await message.answer("❌ Активных пользователей не найдено.")
        return

    success_count = 0
    fail_count = 0

    for user in active_users:
        try:
            # 1. Продлеваем подписку в БД
            user.expire_date += timedelta(days=7)

            # 2. Продлеваем подписку в Marzban
            if user.marzban_username:
                try:
                    await marzban_service.update_user_expiry(
                        marzban_username=user.marzban_username,
                        extra_days=7,
                        tier=user.tier
                    )
                except Exception as e:
                    logger.error(f"Ошибка продления Marzban для {user.user_id}: {e}")

            # 3. Отправляем персональное сообщение пользователю
            try:
                tier_name = "VIP" if user.tier == "premium" else "Обычный"
                await message.bot.send_message(
                    chat_id=user.user_id,
                    text=(
                        f"🎁 <b>Подарок от администрации!</b>\n\n"
                        f"В связи с техническими обновлениями мы добавили <b>+7 дней</b> к вашей активной подписке (Тариф: {tier_name}).\n\n"
                        f"⏳ Новая дата окончания:\n<b>{user.expire_date.strftime('%d.%m.%Y %H:%M')}</b>\n\n"
                        "Спасибо, что остаетесь с нами! Приятного серфинга!"
                    ),
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.warning(f"Не удалось отправить уведомление о бонусе пользователю {user.user_id}: {e}")

            success_count += 1

        except Exception as e:
            logger.error(f"Глобальная ошибка при выдаче бонуса пользователю {user.user_id}: {e}")
            fail_count += 1

        # Задержка 50мс, чтобы не улететь в бан от Telegram API за спам
        await asyncio.sleep(0.05)

    await session.commit()

    await message.answer(
        "✅ <b>Начисление бонусов завершено!</b>\n\n"
        f"Успешно продлено и уведомлено: <b>{success_count}</b> пользователей.\n"
        f"Ошибок: <b>{fail_count}</b>.",
        parse_mode="HTML"
    )

@router.message(Command("bonus_std"))
async def cmd_bonus_std(message: types.Message, session: AsyncSession):
    """Секретная команда для выдачи 7 дней только активным пользователям Обычного тарифа."""
    if not is_admin(message.from_user.id):
        return

    await message.answer("🎁 <b>Начинаю начисление 7 дней всем активным пользователям Обычного тарифа...</b>\nЭто может занять некоторое время.", parse_mode="HTML")

    now = datetime.utcnow()

    # Ищем всех, у кого подписка еще не истекла и тариф стандартный
    result = await session.execute(
        select(User).where(User.expire_date > now).where(User.tier == "standard")
    )
    active_users = result.scalars().all()

    if not active_users:
        await message.answer("❌ Активных пользователей Обычного тарифа не найдено.")
        return

    success_count = 0
    fail_count = 0

    for user in active_users:
        try:
            # 1. Продлеваем подписку в БД
            user.expire_date += timedelta(days=7)

            # 2. Продлеваем подписку в Marzban
            if user.marzban_username:
                try:
                    await marzban_service.update_user_expiry(
                        marzban_username=user.marzban_username,
                        extra_days=7,
                        tier=user.tier
                    )
                except Exception as e:
                    logger.error(f"Ошибка продления Marzban для {user.user_id}: {e}")

            # 3. Отправляем персональное сообщение пользователю
            try:
                await message.bot.send_message(
                    chat_id=user.user_id,
                    text=(
                        f"🎁 <b>Подарок от администрации!</b>\n\n"
                        f"В связи с техническими обновлениями мы добавили <b>+7 дней</b> к вашей активной подписке (Тариф: Обычный).\n\n"
                        f"⏳ Новая дата окончания:\n<b>{user.expire_date.strftime('%d.%m.%Y %H:%M')}</b>\n\n"
                        "Спасибо, что остаетесь с нами! Приятного серфинга!"
                    ),
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.warning(f"Не удалось отправить уведомление о бонусе пользователю {user.user_id}: {e}")

            success_count += 1

        except Exception as e:
            logger.error(f"Глобальная ошибка при выдаче бонуса пользователю {user.user_id}: {e}")
            fail_count += 1

        # Задержка 50мс, чтобы не улететь в бан от Telegram API за спам
        await asyncio.sleep(0.05)

    await session.commit()

    await message.answer(
        "✅ <b>Начисление бонусов завершено!</b>\n\n"
        f"Успешно продлено и уведомлено (Обычный тариф): <b>{success_count}</b> пользователей.\n"
        f"Ошибок: <b>{fail_count}</b>.",
        parse_mode="HTML"
    )
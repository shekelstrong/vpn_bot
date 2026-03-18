"""
Обработчик команды /start и главного меню.
"""
from aiogram import Router, F, types
from aiogram.filters import Command
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger
from database.models import User
from keyboards.inline import get_main_menu_keyboard
from config import settings

router = Router()

async def get_user_from_db(session: AsyncSession, user_id: int) -> User:
    """Получить или создать пользователя в БД."""
    result = await session.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        user = User(user_id=user_id)
        session.add(user)
        # ВАЖНО: Сразу коммитим создание пользователя, чтобы он появился в базе данных
        await session.commit()
        logger.info(f"Создан новый пользователь: {user_id}")
        
    return user

@router.message(Command("start"))
async def cmd_start(message: types.Message, session: AsyncSession):
    """
    Обработчик команды /start.
    Проверяет наличие реферера и регистрирует пользователя.
    """
    user_id = message.from_user.id
    username = message.from_user.username
    referrer_id = None

    # Проверяем наличие реферера в параметрах /start
    args = message.text.split()
    if len(args) > 1:
        try:
            referrer_id = int(args[1])
            if referrer_id == user_id:
                referrer_id = None # Нельзя быть своим реферером
        except ValueError:
            pass

    # Получаем или создаем пользователя
    user = await get_user_from_db(session, user_id)
    
    needs_commit = False

    # Обновляем username, если он изменился
    if username and user.username != username:
        user.username = username
        needs_commit = True

    # Привязываем реферера, если это новый пользователь и у него еще нет реферера
    if referrer_id and user.referrer_id is None:
        result = await session.execute(select(User).where(User.user_id == referrer_id))
        referrer = result.scalar_one_or_none()
        
        if referrer:
            user.referrer_id = referrer_id
            needs_commit = True
            logger.info(f"Пользователь {user_id} привязан к рефереру {referrer_id}")

    # Если были изменения, сохраняем их в базу
    if needs_commit:
        await session.commit()

    # Отправляем приветственное сообщение
    welcome_text = (
        f"Привет, <b>{message.from_user.first_name}</b>!\n\n"
        "Добро пожаловать в <b>Nemo VPN</b> — твой надёжный VPN-сервис!\n\n"
        "<b>Что я умею:</b>\n"
        "• Выдавать бесплатный триал на 24 часа\n"
        "• Оформлять подписку за 100р/месяц\n"
        "• Предоставлять доступ к премиум серверам\n"
        "• Работать с протоколом VLESS Reality\n\n"
        "<b>Почему Nemo VPN:</b>\n"
        "• Обход блокировок и цензуры\n"
        "• Высокая скорость соединения\n"
        "• Надёжное шифрование трафика\n"
        "• Поддержка во всех странах\n\n"
        "Выберите действие в меню ниже:"
    )

    await message.answer(
        text=welcome_text,
        reply_markup=get_main_menu_keyboard(),
    )
    logger.info(f"Пользователь {user_id} запустил бота")

@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery):
    """Вернуться в главное меню."""
    await callback.message.edit_text(
        text="Главное меню Nemo VPN\n\nВыберите действие:",
        reply_markup=get_main_menu_keyboard(),
    )
    await callback.answer()

@router.message(F.text.startswith("Мой профиль"))
async def show_profile_menu(message: types.Message):
    """Показать меню профиля."""
    await message.answer(
        text="Профиль пользователя\n\nВыберите действие:",
        reply_markup=get_main_menu_keyboard(),
    )

@router.message(F.text.startswith("Купить подписку"))
async def show_buy_menu(message: types.Message):
    """Показать меню покупки."""
    await message.answer(
        text="Магазин подписок\n\nВыберите тариф:",
        reply_markup=get_main_menu_keyboard(),
    )

@router.message(F.text.startswith("Бесплатный триал"))
async def show_trial_menu(message: types.Message):
    """Показать меню триала."""
    await message.answer(
        text="Бесплатный триал\n\nПопробуйте наш VPN бесплатно в течение 24 часов!",
        reply_markup=get_main_menu_keyboard(),
    )

@router.message(F.text.startswith("Помощь"))
async def show_help_menu(message: types.Message):
    """Показать меню помощи."""
    help_text = (
        "Помощь и поддержка\n\n"
        "Если у вас возникли вопросы или проблемы:\n\n"
        "1. Проверьте раздел «Как настроить Hiddify»\n"
        "2. Прочитайте частые вопросы (FAQ)\n"
        "3. Напишите в техподдержку\n\n"
        "Мы всегда готовы помочь!"
    )
    await message.answer(
        text=help_text,
        reply_markup=get_main_menu_keyboard(),
    )
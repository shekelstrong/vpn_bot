"""
Обработчик команды /start и главного меню.
"""

from aiogram import Router, F, Bot
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger
import uuid

from database.models import User
from keyboards.inline import get_main_menu_keyboard
from handlers.admin.notifications import notify_admin_new_user, notify_referrer_new_referral

router = Router(name="start_router")


async def generate_marzban_username(user_id: int) -> str:
    """Генерирует уникальное имя пользователя для Marzban."""
    return f"tg_{user_id}_{str(uuid.uuid4())[:6]}"


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession, bot: Bot):
    """
    Обработчик команды /start.
    Проверяет наличие реферера, регистрирует пользователя и отправляет уведомления.
    """
    user_id = message.from_user.id
    username = message.from_user.username
    
    # Пытаемся получить аргумент команды (например, ID рефовода из ссылки /start 12345)
    command_args = message.text.split()[1] if len(message.text.split()) > 1 else None
    referrer_id = None
    
    if command_args and command_args.isdigit():
        ref_id_candidate = int(command_args)
        if ref_id_candidate != user_id:  # Защита от регистрации по своей же ссылке
            referrer_id = ref_id_candidate

    # Проверяем, существует ли пользователь в базе
    result = await session.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        # --- ЛОГИКА СОЗДАНИЯ НОВОГО ПОЛЬЗОВАТЕЛЯ ---
        marzban_username = await generate_marzban_username(user_id)
        
        # Проверяем, действительно ли существует рефовод в базе
        actual_referrer = None
        if referrer_id:
            actual_referrer = await session.scalar(select(User).where(User.user_id == referrer_id))
            if not actual_referrer:
                referrer_id = None # Сбрасываем, если рефовода нет в БД
        
        # Создаем нового пользователя
        user = User(
            user_id=user_id,
            username=username,
            marzban_username=marzban_username,
            referrer_id=referrer_id
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        logger.info(f"Создан новый пользователь: {user_id}")
        
        # --- БЛОК УВЕДОМЛЕНИЙ ПРИ РЕГИСТРАЦИИ ---
        referrers_chain = []
        if actual_referrer:
            # Уведомляем прямого рефовода (Уровень 1)
            await notify_referrer_new_referral(
                bot=bot,
                referrer_id=actual_referrer.user_id,
                new_user_id=user_id,
                level=1,
                new_user_username=username
            )
            referrers_chain.append({
                'level': 1, 
                'id': actual_referrer.user_id, 
                'username': actual_referrer.username
            })
            
            # Ищем рефовода 2-го уровня
            if actual_referrer.referrer_id:
                ref2 = await session.scalar(select(User).where(User.user_id == actual_referrer.referrer_id))
                if ref2:
                    referrers_chain.append({
                        'level': 2, 
                        'id': ref2.user_id, 
                        'username': ref2.username
                    })
                    # Ищем рефовода 3-го уровня
                    if ref2.referrer_id:
                        ref3 = await session.scalar(select(User).where(User.user_id == ref2.referrer_id))
                        if ref3:
                            referrers_chain.append({
                                'level': 3, 
                                'id': ref3.user_id, 
                                'username': ref3.username
                            })
        
        # Уведомляем админов о новом юзере
        await notify_admin_new_user(
            bot=bot,
            user_id=user_id,
            username=username,
            referrers_chain=referrers_chain if referrers_chain else None
        )
    else:
        # --- ЛОГИКА ДЛЯ СУЩЕСТВУЮЩЕГО ПОЛЬЗОВАТЕЛЯ ---
        needs_commit = False
        if username and user.username != username:
            user.username = username
            needs_commit = True
        
        if needs_commit:
            await session.commit()

    # Приветственное сообщение
    welcome_text = (
        f"Привет, <b>{message.from_user.first_name}</b>!\n\n"
        "Добро пожаловать в <b>Nemo VPN</b> — твой надёжный VPN-сервис!\n\n"
        "<b>Что я умею:</b>\n"
        "• Выдавать бесплатный триал на 24 часа\n"
        "• Оформлять подписку за 100р/месяц\n"
        "• Предоставлять доступ к премиум серверам\n"
        "• Работать с протоколом VLESS Reality\n"
        "• Реферальная программа — заработок на приглашении друзей\n\n"
        "<b>Почему Nemo VPN:</b>\n"
        "• Обход блокировок и цензуры\n"
        "• Высокая скорость соединения\n"
        "• Надёжное шифрование трафика\n"
        "• Поддержка во всех странах\n"
        "• Выплаты по реферальной программе до 15%\n\n"
        "Выберите действие в меню ниже:"
    )

    await message.answer(
        text=welcome_text,
        reply_markup=get_main_menu_keyboard(),
        parse_mode="HTML"
    )
    logger.info(f"Пользователь {user_id} запустил бота")


@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    """Вернуться в главное меню."""
    await callback.message.edit_text(
        text="🏠 <b>Главное меню Nemo VPN</b>\n\nВыберите действие:",
        reply_markup=get_main_menu_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(F.text.startswith("Мой профиль"))
async def show_profile_menu(message: Message):
    """Показать меню профиля."""
    await message.answer(
        text="Профиль пользователя\n\nВыберите действие:",
        reply_markup=get_main_menu_keyboard(),
    )


@router.message(F.text.startswith("Купить подписку"))
async def show_buy_menu(message: Message):
    """Показать меню покупки."""
    await message.answer(
        text="Магазин подписок\n\nВыберите тариф:",
        reply_markup=get_main_menu_keyboard(),
    )


@router.message(F.text.startswith("Бесплатный триал"))
async def show_trial_menu(message: Message):
    """Показать меню триала."""
    await message.answer(
        text="Бесплатный триал\n\nПопробуйте наш VPN бесплатно в течение 24 часов!",
        reply_markup=get_main_menu_keyboard(),
    )


@router.message(F.text.startswith("Помощь"))
async def show_help_menu(message: Message):
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
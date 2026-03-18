#!/usr/bin/env python3
"""
Nemo VPN Bot - Telegram бот для управления VPN подписками.
Интеграция с Marzban API для управления пользователями VLESS Reality.

Запуск: python bot.py
"""

import os
import ssl

# === МАГИЧЕСКАЯ ЗАПЛАТКА ДЛЯ MACOS ===
# Жестко отключаем строгую проверку SSL-сертификатов глобально для локального питона
if not os.environ.get('PYTHONHTTPSVERIFY', '') and getattr(ssl, '_create_unverified_context', None):
    ssl._create_default_https_context = ssl._create_unverified_context
# ======================================

import asyncio
import signal
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message, BotCommand, BotCommandScopeDefault, BotCommandScopeAllPrivateChats, MenuButtonCommands
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta
from loguru import logger

from config import settings, init_default_settings
from database.engine import init_db, close_db, get_session_factory
from database.models import User, BotSettings
from services.marzban_api import marzban_service
from utils.scheduler import create_scheduler, get_scheduler

# Импортируем роутеры
from handlers.start import router as start_router
from handlers.profile import router as profile_router
from handlers.trial import router as trial_router
from handlers.buy import router as buy_router
from handlers.help import router as help_router
from handlers.admin import router as admin_router
from handlers.admin.settings import router as admin_settings_router
from handlers.referrals import router as referrals_router


# Настройка логгирования
logger.remove()  # Удаляем стандартный обработчик
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}:{line}</cyan>",
    level="INFO",
)

# Добавляем логгирование в файл
log_path = Path("logs")
log_path.mkdir(exist_ok=True)

logger.add(
    log_path / "bot_{time:YYYY-MM-DD}.log",
    rotation="00:00",
    retention="7 days",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss} | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}:{line}</cyan>",
    level="INFO",
)

# Создаем бота и диспетчер
bot = Bot(
    token=settings.BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)


# Создаем диспетчер
dp = Dispatcher()


# Создаем фабрику сессий БД
session_factory = get_session_factory()


@dp.update.outer_middleware()
async def db_session_middleware(handler, event, data):
    """Middleware для передачи сессии БД в обработчики."""
    async with session_factory()() as session:
        data['session'] = session
        return await handler(event, data)


# Включаем роутеры
dp.include_router(start_router)
dp.include_router(profile_router)
dp.include_router(trial_router)
dp.include_router(buy_router)
dp.include_router(help_router)
dp.include_router(admin_router)
dp.include_router(admin_settings_router)
dp.include_router(referrals_router)


@dp.message(Command("ping"))
async def cmd_ping(message: Message):
    """Проверка работоспособности бота."""
    await message.answer("🏓 <b>Pong!</b>\n\nБот работает исправно.")


@dp.message(Command("me"))
async def cmd_me(message: Message):
    """Показать информацию о текущем пользователе."""
    user_id = message.from_user.id
    
    async with get_session_factory()() as session:
        from sqlalchemy import select
        result = await session.execute(select(User).where(User.user_id == user_id))
        user = result.scalar_one_or_none()
        
        if user:
            text = (
                f"👤 <b>Ваша информация</b>\n\n"
                f"ID: <code>{user.user_id}</code>\n"
                f"Username: @{user.username or 'N/A'}\n"
                f"Marzban: <code>{user.marzban_username or 'N/A'}</code>\n"
                f"Баланс: {user.balance:.2f}₽\n"
                f"Реф. баланс: {user.referral_balance:.2f}₽\n"
                f"Триал: {'Использован' if user.is_trial_used else 'Доступен'}\n"
            )
            
            if user.expire_date:
                from datetime import datetime
                days_left = (user.expire_date - datetime.utcnow()).days
                text += f"Подписка: {'Активна' if days_left > 0 else 'Истекла'} ({days_left} дн.)\n"
            
            await message.answer(text)
        else:
            await message.answer("❌ Вы ещё не зарегистрированы. Нажмите /start")
            
    logger.info(f"Пользователь {user_id} запросил информацию о себе")


@dp.message(Command("me"))
async def cmd_me(message: Message):
    """Показать информацию о текущем пользователе."""
    user_id = message.from_user.id
    
    async with get_session_factory()() as session:
        from sqlalchemy import select
        result = await session.execute(select(User).where(User.user_id == user_id))
        user = result.scalar_one_or_none()
        
        if user:
            text = (
                f"👤 <b>Ваша информация</b>\n\n"
                f"ID: <code>{user.user_id}</code>\n"
                f"Username: @{user.username or 'N/A'}\n"
                f"Marzban: <code>{user.marzban_username or 'N/A'}</code>\n"
                f"Баланс: {user.balance:.2f}₽\n"
                f"Реф. баланс: {user.referral_balance:.2f}₽\n"
                f"Триал: {'Использован' if user.is_trial_used else 'Доступен'}\n"
            )
            
            if user.expire_date:
                from datetime import datetime
                days_left = (user.expire_date - datetime.utcnow()).days
                text += f"Подписка: {'Активна' if days_left > 0 else 'Истекла'} ({days_left} дн.)\n"
            
            await message.answer(text)
        else:
            await message.answer("❌ Вы ещё не зарегистрированы. Нажмите /start")

            
    logger.info(f"Пользователь {user_id} запросил информацию о себе")


@dp.message(Command("me"))
async def cmd_me(message: Message):
    """Показать информацию о текущем пользователе."""
    user_id = message.from_user.id
    
    async with get_session_factory()() as session:
        from sqlalchemy import select
        result = await session.execute(select(User).where(User.user_id == user_id))
        user = result.scalar_one_or_none()
        
        if user:
            text = (
                f"👤 <b>Ваша информация</b>\n\n"
                f"ID: <code>{user.user_id}</code>\n"
                f"Username: @{user.username or 'N/A'}\n"
                f"Marzban: <code>{user.marzban_username or 'N/A'}</code>\n"
                f"Баланс: {user.balance:.2f}₽\n\n"
                f"Реф. баланс: {user.referral_balance:.2f}₽\n"
                f"Триал: {'Использован' if user.is_trial_used else 'Доступен'}\n"
            )
            
            if user.expire_date:
                from datetime import datetime
                days_left = (user - datetime.utcnow()).days
                text += f"Подписка: {'Активна' if days_left > 0 else 'Истекла'} ({days_left} дн.)\n"
            
            await message.answer(text)
        else:
            await message.answer("❌ Вы ещё не зарегистрированы. Нажмите /start")
            
    logger.info(f"Пользователь {user_id} запросил информацию о себе")


async def on_startup():
    """Действия при запуске бота."""
    logger.info("Запуск бота...")
    
    # Инициализация базы данных
    await init_db()
    logger.info("База данных инициализирована")
    
    # Инициализация дефолтных настроек
    async with get_session_factory()() as session:
        await init_default_settings(session)
    logger.info("Дефолтные настройки инициализированы")
    
    # Инициализация планировщика
    scheduler = create_scheduler(bot, get_session_factory())
    await scheduler.start()
    logger.info("Планировщик уведомлений запущен")
    
    # Информация о боте
    bot_info = await bot.get_me()
    logger.info(f"Бот запущен: @{bot_info.username} (ID: {bot_info.id})")
    
    # Информация об администраторах
    admin_count = len(settings.admin_ids_list)
    logger.info(f"Зарегистрировано администраторов: {admin_count}")
    
    # Установка кнопки меню слева от поля ввода
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    logger.info("Кнопка меню установлена")

    # Установка команд (для всех пользователей)
    base_commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="me", description="Мой профиль"),
        BotCommand(command="buy", description="Купить подписку"),
        BotCommand(command="trial", description="Бесплатный триал"),
        BotCommand(command="referral", description="Реферальная программа"),
        BotCommand(command="help", description="Помощь"),
    ]
    
    # Сначала устанавливаем базовые команды для всех пользователей
    await bot.set_my_commands(base_commands, scope=BotCommandScopeDefault())
    logger.info("Общие команды установлены")


async def on_shutdown():
    """Действия при остановке бота."""
    logger.info("Остановка бота...")
    
    # Остановка планировщика
    scheduler = get_scheduler()
    if scheduler:
        await scheduler.stop()
        logger.info("Планировщик остановлен")
    
    # Закрытие соединений
    await marzban_service.close()
    logger.info("Marzban API клиент закрыт")
    
    await close_db()
    await bot.session.close()
    logger.info("Сессия БД закрыта")


async def main():
    """Основная функция запуска бота через polling."""
    # Регистрируем обработчики сигналов
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(sig, lambda: asyncio.create_task(on_shutdown()))
    
    # Запускаем бота
    try:
        await on_startup()
        await dp.start_polling(bot, allowed_updates=None)
    except KeyboardInterrupt:
        pass
    finally:
        pass
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
from aiogram.types import (
    Message, BotCommand, BotCommandScopeDefault, 
    BotCommandScopeAllPrivateChats, BotCommandScopeChat, 
    MenuButtonCommands, MenuButtonWebApp, WebAppInfo
)
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
from handlers.referrals import router as referrals_router

# Импортируем сервисы CryptoBot v2
from services.crypto_bot_v2 import crypto_bot_v2_service
from services.crypto_webhook import handle_crypto_webhook_update

# Импортируем вебхук-сервер для Platega и Mini App
from utils.webhook_server import run_webhooks


async def update_trial_command_for_user(user_id: int, has_active_subscription: bool):
    """Обновить команду /trial для конкретного пользователя."""
    base_commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="me", description="Мой профиль"),
        BotCommand(command="buy", description="Купить подписку"),
        BotCommand(command="sub", description="Подписка"),
        BotCommand(command="referral", description="Реферальная программа"),
        BotCommand(command="help", description="Помощь"),
    ]

    # Добавляем /trial только если нет активной подписки
    if not has_active_subscription:
        base_commands.insert(4, BotCommand(command="trial", description="Пробный период"))

    # Для администраторов добавляем /admin
    if user_id in settings.admin_ids_list:
        base_commands.insert(0, BotCommand(command="admin", description="Админ-панель"))

    await bot.set_my_commands(
        base_commands,
        scope=BotCommandScopeChat(chat_id=user_id)
    )


async def update_trial_commands_for_all_users():
    """Обновить команды для всех пользователей."""
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(select(User))
        users = result.scalars().all()

        for user in users:
            has_subscription = user.expire_date and user.expire_date > datetime.utcnow()
            await update_trial_command_for_user(user.user_id, has_subscription)


# Настройка логгирования
logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}:{line}</cyan> - <level>{message}</level>",
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
    format="{time:YYYY-MM-DD HH:mm:ss} | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}:{line}</cyan> - {message}",
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


@dp.update.outer_middleware
async def db_session_middleware(handler, event, data):
    """Middleware для передачи сессии БД в обработчики."""
    factory = get_session_factory()
    async with factory() as session:
        data['session'] = session
        return await handler(event, data)


# Включаем роутеры
dp.include_router(start_router)
dp.include_router(profile_router)
dp.include_router(trial_router)
dp.include_router(buy_router)
dp.include_router(help_router)
dp.include_router(admin_router)
dp.include_router(referrals_router)


@dp.message(Command("me"))
async def cmd_me(message: Message):
    """Показать информацию о текущем пользователе."""
    user_id = message.from_user.id
    
    session_factory = get_session_factory()
    async with session_factory() as session:
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
                days_left = (user.expire_date - datetime.utcnow()).days
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
    factory = get_session_factory()
    async with factory() as session:
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

    # Установка кнопки Mini App слева от поля ввода (вместо стандартного Меню)
    webapp_url = "https://nemo-vpn-webapp.vercel.app/"
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(
            text="Nemo VIP", 
            web_app=WebAppInfo(url=webapp_url)
        )
    )
    logger.info("Кнопка Mini App установлена в главное меню")

    # Установка команд для всех пользователей
    base_commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="me", description="Мой профиль"),
        BotCommand(command="buy", description="Купить подписку"),
        BotCommand(command="sub", description="Подписка"),
        BotCommand(command="trial", description="Пробный период"),
        BotCommand(command="referral", description="Реферальная программа"),
        BotCommand(command="help", description="Помощь"),
    ]

    await bot.set_my_commands(base_commands, scope=BotCommandScopeAllPrivateChats())
    logger.info("Общие команды установлены")

    # Установка команды admin только для администраторов
    admin_commands = [
        BotCommand(command="admin", description="Админ-панель"),
    ]

    for admin_id in settings.admin_ids_list:
        await bot.set_my_commands(
            base_commands + admin_commands,
            scope=BotCommandScopeChat(chat_id=admin_id)
        )
    logger.info("Админские команды установлены")

    # Скрываем команду /trial для пользователей с активной подпиской
    await update_trial_commands_for_all_users()
    logger.info("Команды /trial обновлены для всех пользователей")

    # Запускаем обновленный вебхук-сервер
    await run_webhooks(bot)
    logger.info("Вебхук-сервер запущен")


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
        await on_shutdown()


if __name__ == "__main__":
    asyncio.run(main())
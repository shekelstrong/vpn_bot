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
from aiogram.types import Message, BotCommand, BotCommandScopeDefault, MenuButtonCommands
from loguru import logger

from config import settings, init_default_settings
from database.engine import init_db, close_db, get_session_factory
from database.models import User
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
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
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
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
)


# Создаем бота и диспетчер
bot = Bot(
    token=settings.BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)

dp = Dispatcher()

# Создаём фабрику сессий и добавляем middleware для БД
session_factory = get_session_factory()


@dp.update.outer_middleware()
async def db_session_middleware(handler, event, data):
    """Middleware для передачи сессии БД в обработчики."""
    async with session_factory() as session:
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

    # Информация о боте
    bot_info = await bot.get_me()

    # Установка команд (для всех пользователей - БЕЗ /admin)
    base_commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="me", description="Мой профиль"),
        BotCommand(command="buy", description="Купить подписку"),
        BotCommand(command="trial", description="Бесплатный триал"),
        BotCommand(command="referral", description="Реферальная программа"),
        BotCommand(command="help", description="Помощь"),
    ]
    
    # Сначала устанавливаем базовые команды для всех пользователей
    await bot.set_my_commands(base_commands, scope=BotCommandScopeAllPrivateChats())
    logger.info("Общие команды установлены")

    # Команды для админов (добавляем команду /admin только для них)
    if settings.admin_ids_list:
        admin_commands = base_commands + [
            BotCommand(command="admin", description="Админ-панель")
        ]
        
        for admin_id in settings.admin_ids_list:
            try:
                await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=admin_id))
            except Exception as e:
                logger.warning(f"Не удалось установить админ-команды для {admin_id}: {e}")
        
        logger.info(f"Админ-команды установлены для {len(settings.admin_ids_list)} админов")
    
    logger.info("=" * 50)
    logger.info("Nemo VPN Bot готов к работе!")
    logger.info("=" * 50)


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
    logger.info("Соединения с БД закрыты")
    
    await bot.session.close()
    logger.info("Сессия бота закрыта")
    
    logger.info("=" * 50)
    logger.info("Бот остановлен")
    logger.info("=" * 50)


async def main():
    """Основная функция запуска бота через polling."""
    # Регистрируем обработчики сигналов
    loop = asyncio.get_running_loop()
    
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(
            sig,
            lambda: asyncio.create_task(shutdown_and_exit()),
        )
    
    # Запуск бота
    await on_startup()
    
    try:
        # Запускаем polling (удаление webhook на всякий случай)
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook удален, запущен polling...")
        
        # Запускаем polling
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logger.info("Получен сигнал прерывания")
    finally:
        await on_shutdown()


async def shutdown_and_exit():
    """Корректное завершение работы."""
    logger.info("Получен сигнал завершения работы")
    await on_shutdown()
    
    # Завершаем все задачи
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    
    for task in tasks:
        task.cancel()
    
    await asyncio.gather(*tasks, return_exceptions=True)
    
    # Выходим
    sys.exit(0)


if __name__ == "__main__":
    # Создаем директорию для логов если не существует
    Path("logs").mkdir(exist_ok=True)
    
    # Запускаем бота
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.critical(f"Критическая ошибка: {e}")
        raise
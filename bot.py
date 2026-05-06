#!/usr/bin/env python3
"""
Nemo VPN Bot - Telegram бот для управления VPN подписками.
"""

import os
import ssl
if not os.environ.get('PYTHONHTTPSVERIFY', '') and getattr(ssl, '_create_unverified_context', None):
    ssl._create_default_https_context = ssl._create_unverified_context

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
from handlers.traffic_buy import router as traffic_buy_router
from handlers.gift import router as gift_router
from handlers.referral_buy import router as referral_buy_router
from handlers.vk_link import link_router

from services.crypto_bot_v2 import crypto_bot_v2_service
from services.crypto_webhook import handle_crypto_webhook_update
from utils.webhook_server import run_webhooks


async def update_trial_command_for_user(user_id: int, has_active_subscription: bool):
    base_commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="me", description="Мой профиль"),
        BotCommand(command="buy", description="Купить подписку"),
        BotCommand(command="sub", description="Подписка"),
        BotCommand(command="referral", description="Реферальная программа"),
        BotCommand(command="traffic", description="Докупить трафик"),
        BotCommand(command="gift", description="Подарить подписку"),
        BotCommand(command="help", description="Помощь"),
    ]
    if not has_active_subscription:
        base_commands.insert(4, BotCommand(command="trial", description="Пробный период"))
    if user_id in settings.admin_ids_list:
        base_commands.insert(0, BotCommand(command="admin", description="Админ-панель"))
    try:
        await bot.set_my_commands(base_commands, scope=BotCommandScopeChat(chat_id=user_id))
    except Exception as e:
        logger.warning(f"Failed to set commands for user {user_id}: {e}")


async def update_trial_commands_for_all_users():
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(select(User))
        users = result.scalars().all()
        for user in users:
            has_subscription = user.expire_date and user.expire_date > datetime.utcnow()
            await update_trial_command_for_user(user.user_id, has_subscription)


logger.remove()
logger.add(sys.stdout, format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}:{line}</cyan> - <level>{message}</level>", level="INFO")
log_path = Path("logs")
log_path.mkdir(exist_ok=True)
logger.add(log_path / "bot_{time:YYYY-MM-DD}.log", rotation="00:00", retention="7 days", level="DEBUG", format="{time:YYYY-MM-DD HH:mm:ss} | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}:{line}</cyan> - {message}")

bot = Bot(token=settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
session_factory = get_session_factory()


@dp.update.outer_middleware
async def db_session_middleware(handler, event, data):
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
dp.include_router(traffic_buy_router)
dp.include_router(gift_router)
dp.include_router(referral_buy_router)

dp.include_router(link_router)


@dp.message(Command("me"))
async def cmd_me(message: Message):
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
                f"Баланс: {user.balance:.2f}₽\n"
                f"Реф. баланс: {user.referral_balance:.2f}₽\n"
                f"Триал: {'Использован' if user.is_trial_used else 'Доступен'}\n"
            )
            if user.expire_date:
                days_left = (user.expire_date - datetime.utcnow()).days
                text += f"Подписка: {'Активна' if days_left > 0 else 'Истекла'} ({days_left} дн.)\n"
            await message.answer(text)
        else:
            await message.answer("❌ Вы ещё не зарегистрированы. Нажмите /start")
    logger.info(f"Пользователь {user_id} запросил информацию о себе")


async def on_startup():
    logger.info("Запуск бота...")
    await init_db()
    logger.info("База данных инициализирована")

    factory = get_session_factory()
    async with factory() as session:
        await init_default_settings(session)
    logger.info("Дефолтные настройки инициализированы")

    scheduler = create_scheduler(bot, get_session_factory())
    await scheduler.start()
    logger.info("Планировщик уведомлений запущен")

    bot_info = await bot.get_me()
    logger.info(f"Бот запущен: @{bot_info.username} (ID: {bot_info.id})")
    logger.info(f"Зарегистрировано администраторов: {len(settings.admin_ids_list)}")

    webapp_url = "https://nemo-vpn-webapp.vercel.app/"
    await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="Nemo VIP", web_app=WebAppInfo(url=webapp_url)))
    logger.info("Кнопка Mini App установлена")

    base_commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="me", description="Мой профиль"),
        BotCommand(command="buy", description="Купить подписку"),
        BotCommand(command="sub", description="Подписка"),
        BotCommand(command="trial", description="Пробный период"),
        BotCommand(command="referral", description="Реферальная программа"),
        BotCommand(command="traffic", description="Докупить трафик"),
        BotCommand(command="gift", description="Подарить подписку"),
        BotCommand(command="help", description="Помощь"),
    ]
    await bot.set_my_commands(base_commands, scope=BotCommandScopeAllPrivateChats())
    logger.info("Общие команды установлены")

    admin_commands = [BotCommand(command="admin", description="Админ-панель")]
    for admin_id in settings.admin_ids_list:
        await bot.set_my_commands(base_commands + admin_commands, scope=BotCommandScopeChat(chat_id=admin_id))
    logger.info("Админские команды установлены")

    await update_trial_commands_for_all_users()
    logger.info("Команды /trial обновлены для всех пользователей")

    await run_webhooks(bot)
    logger.info("Вебхук-сервер запущен")


async def on_shutdown():
    logger.info("Остановка бота...")
    scheduler = get_scheduler()
    if scheduler:
        await scheduler.stop()
    await marzban_service.close()
    await close_db()
    await bot.session.close()


async def main():
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(sig, lambda: asyncio.create_task(on_shutdown()))
    try:
        await on_startup()
        await dp.start_polling(bot, allowed_updates=None)
    except KeyboardInterrupt:
        pass
    finally:
        await on_shutdown()


if __name__ == "__main__":
    asyncio.run(main())

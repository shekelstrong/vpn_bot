import re
from aiogram import Router, F
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger
from datetime import datetime, timedelta
from database.models import User

link_router = Router(name="vk_link_router")


@link_router.message(F.text.regexp(r'^\d{6}$'))
async def handle_vk_link_code(message: Message, session: AsyncSession):
    """Привязка VK аккаунта через 6-значный код.
    
    VK бот сохраняет last_notified_step = 'tg_link:CODE:unix_timestamp'
    TG пользователь отправляет CODE → аккаунты связываются.
    """
    code = message.text.strip()
    user_id = message.from_user.id
    
    prefix = f"tg_link:{code}:"
    
    # Ищем VK пользователя с таким кодом
    result = await session.execute(
        select(User).where(User.last_notified_step.like(f"{prefix}%"))
    )
    vk_user = result.scalar_one_or_none()
    
    if not vk_user:
        await message.answer(
            "❌ Код не найден или истёк срок действия.\n"
            "Пожалуйста, получите новый код в VK боте."
        )
        return
    
    # Парсим timestamp из last_notified_step
    # Формат: tg_link:CODE:unix_timestamp (число)
    try:
        parts = vk_user.last_notified_step.split(":")
        timestamp_str = parts[2]
        # VK бот записывает Unix timestamp (int), а не ISO формат
        link_timestamp = datetime.utcfromtimestamp(int(timestamp_str))
    except (IndexError, ValueError, OSError) as e:
        logger.error(f"Failed to parse link timestamp: {vk_user.last_notified_step}, error: {e}")
        vk_user.last_notified_step = None
        await session.commit()
        await message.answer(
            "❌ Ошибка при обработке кода. Получите новый код в VK боте."
        )
        return
    
    # Проверяем, что код не старше 10 минут
    now = datetime.utcnow()
    if now - link_timestamp > timedelta(minutes=10):
        vk_user.last_notified_step = None
        await session.commit()
        await message.answer(
            "⏰ Код истёк. Получите новый код в VK боте (срок действия 10 минут)."
        )
        return
    
    # === Привязываем аккаунты ===
    
    # Получаем TG пользователя
    tg_result = await session.execute(select(User).where(User.user_id == user_id))
    tg_user = tg_result.scalar_one_or_none()
    
    if not tg_user:
        tg_user = User(
            user_id=user_id,
            username=message.from_user.username,
            platform="both",
            vk_id=vk_user.vk_id,
        )
        session.add(tg_user)
    else:
        tg_user.vk_id = vk_user.vk_id
        tg_user.platform = "both"
    
    # Обновляем VK пользователя
    vk_user.platform = "both"
    vk_user.last_notified_step = None
    
    await session.commit()
    
    logger.info(f"VK-TG link: TG user {user_id} linked to VK user {vk_user.user_id} (vk_id={vk_user.vk_id})")
    
    await message.answer(
        "✅ <b>Аккаунты успешно связаны!</b>\n\n"
        f"Ваш Telegram привязан к VK профилю.\n"
        "Теперь вы можете использовать VPN с обеих платформ.",
        parse_mode="HTML"
    )
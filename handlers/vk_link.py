import re
from aiogram import Router, F
from aiogram.types import Message
from sqlalchemy import select, delete
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
    
    Если VK-юзер уже существует в БД — сливаем его данные в TG-юзера
    и удаляем VK-юзера (unique constraint на vk_id не даёт просто скопировать).
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
    try:
        parts = vk_user.last_notified_step.split(":")
        timestamp_str = parts[2]
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
    
    # === Сливаем аккаунты ===
    
    # Получаем TG пользователя
    tg_result = await session.execute(select(User).where(User.user_id == user_id))
    tg_user = tg_result.scalar_one_or_none()
    
    if not tg_user:
        # TG юзера нет — создаём с данными из VK
        tg_user = User(
            user_id=user_id,
            username=message.from_user.username,
            platform="both",
            vk_id=vk_user.vk_id,
            marzban_username=vk_user.marzban_username,
            is_trial_used=vk_user.is_trial_used,
            balance=vk_user.balance,
            referral_balance=vk_user.referral_balance,
            referrer_id=vk_user.referrer_id,
            expire_date=vk_user.expire_date,
            tier=vk_user.tier,
            device_count=vk_user.device_count,
            gb_limit=vk_user.gb_limit,
            expire_standard=vk_user.expire_standard,
            expire_premium=vk_user.expire_premium,
            channel_bonus_given=vk_user.channel_bonus_given,
            refs_paid_count=vk_user.refs_paid_count,
            task_channel_sub=vk_user.task_channel_sub,
        )
        session.add(tg_user)
        # Удаляем VK-юзера (его данные перенесены)
        await session.delete(vk_user)
    else:
        # TG юзер есть — сливаем данные из VK в TG
        # Переносим только если в TG пусто, чтобы не затереть
        if not tg_user.marzban_username and vk_user.marzban_username:
            tg_user.marzban_username = vk_user.marzban_username
        # Баланс суммируем
        tg_user.balance = (tg_user.balance or 0) + (vk_user.balance or 0)
        tg_user.referral_balance = (tg_user.referral_balance or 0) + (vk_user.referral_balance or 0)
        # Переносим expire_date — берём максимальный
        if vk_user.expire_date:
            if not tg_user.expire_date or vk_user.expire_date > tg_user.expire_date:
                tg_user.expire_date = vk_user.expire_date
        if vk_user.expire_standard:
            if not tg_user.expire_standard or vk_user.expire_standard > tg_user.expire_standard:
                tg_user.expire_standard = vk_user.expire_standard
        if vk_user.expire_premium:
            if not tg_user.expire_premium or vk_user.expire_premium > tg_user.expire_premium:
                tg_user.expire_premium = vk_user.expire_premium
        # Переносим tier если VK-юзер имеет более высокий
        if vk_user.tier == "premium" and tg_user.tier != "premium":
            tg_user.tier = "premium"
        # Переносим подписки/флаги
        if vk_user.is_trial_used and not tg_user.is_trial_used:
            tg_user.is_trial_used = True
        if vk_user.channel_bonus_given and not tg_user.channel_bonus_given:
            tg_user.channel_bonus_given = True
        # Суммируем реферальные счётчики
        tg_user.refs_paid_count = (tg_user.refs_paid_count or 0) + (vk_user.refs_paid_count or 0)
        # Привязываем VK
        tg_user.vk_id = vk_user.vk_id
        tg_user.platform = "both"
        # Удаляем VK-юзера (чтобы освободить unique constraint на vk_id)
        await session.delete(vk_user)
    
    await session.commit()
    
    logger.info(f"VK-TG link: TG user {user_id} linked to VK id {vk_user.vk_id} (merged from VK user {vk_user.user_id})")
    
    await message.answer(
        "✅ <b>Аккаунты успешно связаны!</b>\n\n"
        f"Ваш Telegram привязан к VK профилю.\n"
        "Теперь вы можете использовать VPN с обеих платформ.",
        parse_mode="HTML"
    )

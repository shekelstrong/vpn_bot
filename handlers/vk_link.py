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
    и удаляем VK-юзера (unique constraint на vk_id).
    
    ВАЖНО: сначала удаляем VK-юзера (чтобы освободить vk_id),
    затем привязываем vk_id к TG-юзеру. Иначе UniqueViolationError.
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
    
    # Сохраняем данные VK-юзера перед удалением
    vk_id = vk_user.vk_id
    vk_marzban = vk_user.marzban_username
    vk_is_trial = vk_user.is_trial_used
    vk_balance = vk_user.balance or 0
    vk_referral_balance = vk_user.referral_balance or 0
    vk_referrer_id = vk_user.referrer_id
    vk_expire_date = vk_user.expire_date
    vk_tier = vk_user.tier
    vk_device_count = vk_user.device_count
    vk_gb_limit = vk_user.gb_limit
    vk_expire_standard = vk_user.expire_standard
    vk_expire_premium = vk_user.expire_premium
    vk_channel_bonus = vk_user.channel_bonus_given
    vk_refs_paid = vk_user.refs_paid_count or 0
    vk_task_channel_sub = vk_user.task_channel_sub
    
    # СНАЧАЛА удаляем VK-юзера (освобождаем vk_id unique constraint)
    await session.delete(vk_user)
    await session.flush()  # Гарантируем что DELETE выполнится до UPDATE
    
    # Теперь получаем TG пользователя
    tg_result = await session.execute(select(User).where(User.user_id == user_id))
    tg_user = tg_result.scalar_one_or_none()
    
    if not tg_user:
        # TG юзера нет — создаём с данными из VK
        tg_user = User(
            user_id=user_id,
            username=message.from_user.username,
            platform="both",
            vk_id=vk_id,
            marzban_username=vk_marzban,
            is_trial_used=vk_is_trial,
            balance=vk_balance,
            referral_balance=vk_referral_balance,
            referrer_id=vk_referrer_id,
            expire_date=vk_expire_date,
            tier=vk_tier,
            device_count=vk_device_count,
            gb_limit=vk_gb_limit,
            expire_standard=vk_expire_standard,
            expire_premium=vk_expire_premium,
            channel_bonus_given=vk_channel_bonus,
            refs_paid_count=vk_refs_paid,
            task_channel_sub=vk_task_channel_sub,
        )
        session.add(tg_user)
    else:
        # TG юзер есть — сливаем данные из VK в TG
        if not tg_user.marzban_username and vk_marzban:
            tg_user.marzban_username = vk_marzban
        # Баланс суммируем
        tg_user.balance = (tg_user.balance or 0) + vk_balance
        tg_user.referral_balance = (tg_user.referral_balance or 0) + vk_referral_balance
        # Переносим expire_date — берём максимальный
        if vk_expire_date:
            if not tg_user.expire_date or vk_expire_date > tg_user.expire_date:
                tg_user.expire_date = vk_expire_date
        if vk_expire_standard:
            if not tg_user.expire_standard or vk_expire_standard > tg_user.expire_standard:
                tg_user.expire_standard = vk_expire_standard
        if vk_expire_premium:
            if not tg_user.expire_premium or vk_expire_premium > tg_user.expire_premium:
                tg_user.expire_premium = vk_expire_premium
        # Переносим tier если VK-юзер имеет более высокий
        if vk_tier == "premium" and tg_user.tier != "premium":
            tg_user.tier = "premium"
        # Переносим подписки/флаги
        if vk_is_trial and not tg_user.is_trial_used:
            tg_user.is_trial_used = True
        if vk_channel_bonus and not tg_user.channel_bonus_given:
            tg_user.channel_bonus_given = True
        # Суммируем реферальные счётчики
        tg_user.refs_paid_count = (tg_user.refs_paid_count or 0) + vk_refs_paid
        # Привязываем VK
        tg_user.vk_id = vk_id
        tg_user.platform = "both"
    
    await session.commit()
    
    logger.info(f"VK-TG link: TG user {user_id} linked to VK id {vk_id}")
    
    await message.answer(
        "✅ <b>Аккаунты успешно связаны!</b>\n\n"
        f"Ваш Telegram привязан к VK профилю.\n"
        "Теперь вы можете использовать VPN с обеих платформ.",
        parse_mode="HTML"
    )

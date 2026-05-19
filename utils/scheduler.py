"""
Планировщик уведомлений для бота Nemo VPN.

ИЗМЕНЕНИЯ:
1. Добавлена задача check_tier_expiry — каждый час проверяет раздельные сроки (expire_standard, expire_premium)
2. Если у пользователя истёк один из тарифов — убирает inbound из Marzban и отправляет уведомление
3. Ссылка подписки остаётся той же, но истёкший ключ пропадает при обновлении в Happ
4. Все уведомления упоминают Happ (не V2Box)
"""

import asyncio
from datetime import datetime, timedelta
from typing import List, Tuple
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from aiogram import Bot
from loguru import logger

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from database.models import User, Notification
from config import settings


NOTIFICATION_STEPS = {
    10080: "7d",
    7200: "5d",
    4320: "3d",
    1440: "24h",
    720: "12h",
    360: "6h",
    180: "3h",
    120: "2h",
    60: "1h",
}

NOTIFICATION_MESSAGES = {
    "7d": "⏰ Ваша подписка Nemo VPN истекает через 7 дней!\n\n"
          "Не оставайтесь без защиты — продлите подписку заранее.\n\n"
          "Для продления перейдите в раздел «Купить подписку 📦»",
    "5d": "⏰ Ваша подписка Nemo VPN истекает через 5 дней!\n\n"
          "Время продлить подписку.",
    "3d": "⚠️ Ваша подписка Nemo VPN истекает через 3 дня!\n\n"
          "Не откладывайте продление.",
    "24h": "🚨 Ваша подписка Nemo VPN истекает через 24 часа!\n\n"
           "Это последнее напоминание за день.",
    "12h": "🚨 Осталось 12 часов до окончания подписки Nemo VPN!",
    "6h": "⛔ Подписка Nemo VPN истекает через 6 часов!",
    "3h": "⛔ Осталось 3 часа до окончания подписки!",
    "2h": "🔴 Подписка Nemo VPN истекает через 2 часа!",
    "1h": "🔴 ПОСЛЕДНЕЕ НАПОМИНАНИЕ! Подписка истекает через 1 час!",
    "expired": "❌ Ваша подписка Nemo VPN истекла.\n\n"
               "Для возобновления доступа приобретите новую подписку.",
    "tier_expired_standard": "🛡 <b>Срок стандартного VPN истёк</b>\n\n"
                             "Обновите подписку в Happ — истёкший ключ исчезнет автоматически.\n"
                             "Если у вас активен VIP — он продолжит работать.\n\n"
                             "Для продления перейдите в «Купить подписку 📦»",
    "tier_expired_premium": "🚀 <b>Срок VIP (обход белых списков) истёк</b>\n\n"
                            "Обновите подписку в Happ — истёкший VIP-ключ исчезнет автоматически.\n"
                            "Стандартный VPN продолжит работать (если активен).\n\n"
                            "Для продления VIP перейдите в «Купить подписку 📦»",
}


class NotificationScheduler:
    def __init__(self, bot: Bot, db_session_factory):
        self.bot = bot
        self.db_session_factory = db_session_factory
        self.scheduler = AsyncIOScheduler()
        self._is_running = False
    
    async def start(self):
        if self._is_running:
            return
        
        # Уведомления об истечении (каждые 10 мин)
        self.scheduler.add_job(
            self._check_notifications,
            trigger=IntervalTrigger(minutes=10),
            id="check_notifications",
            replace_existing=True,
        )
        
        # Проверка истекших подписок (каждый час)
        self.scheduler.add_job(
            self._check_expired_users,
            trigger=IntervalTrigger(hours=1),
            id="check_expired",
            replace_existing=True,
        )
        
        # НОВОЕ: Проверка раздельных сроков тарифов (каждый час)
        self.scheduler.add_job(
            self._check_tier_expiry,
            trigger=IntervalTrigger(hours=1),
            id="check_tier_expiry",
            replace_existing=True,
        )
        
        self.scheduler.start()
        self._is_running = True
        logger.info("Планировщик уведомлений запущен (с проверкой раздельных тарифов)")
    
    async def stop(self):
        if not self._is_running:
            return
        self.scheduler.shutdown()
        self._is_running = False
        logger.info("Планировщик уведомлений остановлен")
    
    # =====================================================================
    # СТАНДАРТНЫЕ УВЕДОМЛЕНИЯ (без изменений)
    # =====================================================================
    
    async def _check_notifications(self):
        logger.debug("Запуск проверки уведомлений...")
        async with self.db_session_factory() as session:
            try:
                now = datetime.utcnow()
                result = await session.execute(
                    select(User).options(selectinload(User.notifications)).where(
                        and_(
                            User.expire_date.isnot(None),
                            User.expire_date > now,
                            User.marzban_username.isnot(None),
                        )
                    )
                )
                users = result.scalars().all()
                for user in users:
                    await self._process_user_notification(session, user, now)
            except Exception as e:
                logger.error(f"Ошибка проверки уведомлений: {e}")
    
    async def _process_user_notification(self, session, user, now):
        if not user.expire_date:
            return
        time_left = user.expire_date - now
        minutes_left = int(time_left.total_seconds() / 60)
        notified_steps = user.last_notified_step.split(",") if user.last_notified_step else []
        for minutes, step_name in NOTIFICATION_STEPS.items():
            if minutes_left <= minutes and minutes_left > minutes - 30:
                if step_name not in notified_steps:
                    await self._send_notification(session, user, step_name)
                    notified_steps.append(step_name)
        user.last_notified_step = ",".join(notified_steps)
        await session.commit()
    
    async def _send_notification(self, session, user, step_name):
        message_text = NOTIFICATION_MESSAGES.get(step_name, "")
        if not message_text:
            return
        try:
            message = await self.bot.send_message(
                chat_id=user.user_id, text=message_text, parse_mode="HTML"
            )
            notification = Notification(
                user_id=user.user_id, notification_type=step_name,
                message_id=message.message_id,
            )
            session.add(notification)
            await session.commit()
            logger.info(f"Отправлено уведомление {step_name} пользователю {user.user_id}")
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления {user.user_id}: {e}")
            await session.rollback()
    
    async def _check_expired_users(self):
        async with self.db_session_factory() as session:
            try:
                now = datetime.utcnow()
                expired_threshold = now - timedelta(hours=24)
                result = await session.execute(
                    select(User).options(selectinload(User.notifications)).where(
                        and_(
                            User.expire_date.isnot(None),
                            User.expire_date < expired_threshold,
                            User.marzban_username.isnot(None),
                        )
                    )
                )
                expired_users = result.scalars().all()
                for user in expired_users:
                    # Проверяем что ещё не отправляли "expired"
                    notified_steps = user.last_notified_step.split(",") if user.last_notified_step else []
                    if "expired" in notified_steps:
                        continue
                    try:
                        await self.bot.send_message(
                            chat_id=user.user_id,
                            text=NOTIFICATION_MESSAGES.get("expired", ""),
                        )
                        notified_steps.append("expired")
                        user.last_notified_step = ",".join(notified_steps)
                        await session.commit()
                        logger.info(f"Обработан истекший пользователь {user.user_id}")
                    except Exception as e:
                        logger.error(f"Ошибка обработки истекшего {user.user_id}: {e}")
            except Exception as e:
                logger.error(f"Ошибка проверки истекших: {e}")
    
    # =====================================================================
    # НОВОЕ: ПРОВЕРКА РАЗДЕЛЬНЫХ СРОКОВ ТАРИФОВ
    # =====================================================================
    
    async def _check_tier_expiry(self):
        """
        Каждый час проверяем expire_standard и expire_premium.
        Если один из тарифов истёк — обновляем inbound-ы в Marzban
        и отправляем уведомление пользователю.
        """
        from services.xui_api import xui_service as marzban_service
        
        async with self.db_session_factory() as session:
            try:
                now = datetime.utcnow()
                
                # Ищем пользователей у которых есть marzban_username и хотя бы один тариф истёк недавно
                # (в пределах последних 2 часов, чтобы не спамить)
                recent_window = now - timedelta(hours=2)
                
                result = await session.execute(
                    select(User).where(
                        and_(
                            User.marzban_username.isnot(None),
                            or_(
                                and_(
                                    User.expire_standard.isnot(None),
                                    User.expire_standard < now,
                                    User.expire_standard > recent_window,
                                ),
                                and_(
                                    User.expire_premium.isnot(None),
                                    User.expire_premium < now,
                                    User.expire_premium > recent_window,
                                ),
                            ),
                        )
                    )
                )
                users = result.scalars().all()
                
                for user in users:
                    await self._process_tier_expiry(session, user, now, marzban_service)
                
                if users:
                    logger.info(f"Обработано {len(users)} пользователей с истёкшими тарифами")
                
            except Exception as e:
                logger.error(f"Ошибка проверки раздельных тарифов: {e}")
    
    async def _process_tier_expiry(self, session, user, now, marzban_service):
        """Обработать истечение конкретного тарифа у пользователя."""
        try:
            # Определяем какие inbound-ы ещё активны
            active_inbounds = []
            standard_expired = False
            premium_expired = False
            
            if user.expire_standard and user.expire_standard > now:
                active_inbounds.append("vless-reality-standard")
            elif user.expire_standard and user.expire_standard <= now:
                standard_expired = True
            
            if user.expire_premium and user.expire_premium > now:
                active_inbounds.append("vless-reality-whitelist")
            elif user.expire_premium and user.expire_premium <= now:
                premium_expired = True
            
            # Если оба тарифа истекли — не трогаем, это обработает _check_expired_users
            if not active_inbounds:
                return
            
            # Обновляем Marzban: оставляем только активные inbound-ы
            marzban_data = await marzban_service.get_user(user.marzban_username)
            if not marzban_data:
                return
            
            current_inbounds = marzban_data.get("inbounds", {}).get("vless", [])
            
            # Если inbound-ы уже правильные — пропускаем
            if set(current_inbounds) == set(active_inbounds):
                return
            
            # Обновляем inbound-ы
            await marzban_service.update_user_inbounds(user.marzban_username, active_inbounds)
            logger.info(f"3x-ui: обновлены inbound-ы для {user.marzban_username} → {active_inbounds}")
            
            # Обновляем tier пользователя на основе активных подписок
            if premium_expired and not standard_expired:
                user.tier = "standard"
                logger.info(f"Tier пользователя {user.user_id} изменён на 'standard' (VIP истёк)")
            elif standard_expired and not premium_expired:
                user.tier = "premium"
                logger.info(f"Tier пользователя {user.user_id} изменён на 'premium' (стандарт истёк)")

            # Пересчитываем expire_date
            user.recalculate_expire_date()
            await session.commit()
            
            # Отправляем уведомление пользователю
            if standard_expired:
                await self._send_notification(session, user, "tier_expired_standard")
            if premium_expired:
                await self._send_notification(session, user, "tier_expired_premium")
            
        except Exception as e:
            logger.error(f"Ошибка обработки тарифа для {user.user_id}: {e}")


# Глобальный экземпляр
scheduler = None

def create_scheduler(bot: Bot, db_session_factory) -> NotificationScheduler:
    global scheduler
    scheduler = NotificationScheduler(bot, db_session_factory)
    return scheduler

def get_scheduler() -> NotificationScheduler:
    return scheduler

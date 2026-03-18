"""
Планировщик уведомлений для бота Nemo VPN.
Автоматическая проверка истечения подписок и отправка уведомлений.
"""

import asyncio
from datetime import datetime, timedelta
from typing import List, Tuple
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram import Bot
from loguru import logger

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from database.models import User, Notification
from config import settings


# Интервалы уведомлений в минутах до истечения
NOTIFICATION_STEPS = {
    10080: "7d",    # 7 дней
    7200: "5d",     # 5 дней
    4320: "3d",     # 3 дня
    1440: "24h",    # 24 часа
    720: "12h",     # 12 часов
    360: "6h",      # 6 часов
    180: "3h",      # 3 часа
    120: "2h",      # 2 часа
    60: "1h",       # 1 час
}

# Тексты уведомлений
NOTIFICATION_MESSAGES = {
    "7d": "⏰ Ваша подписка Nemo VPN истекает через 7 дней!\n\n"
          "Не оставайтесь без защиты — продлите подписку заранее.\n\n"
          "Для продления перейдите в раздел «Купить подписку 📦»",
    
    "5d": "⏰ Ваша подписка Nemo VPN истекает через 5 дней!\n\n"
          "Время продлить подписку и продолжить пользоваться VPN без ограничений.",
    
    "3d": "⚠️ Ваша подписка Nemo VPN истекает через 3 дня!\n\n"
          "Не откладывайте продление — обеспечьте себе бесперебойный доступ к VPN.",
    
    "24h": "🚨 Ваша подписка Nemo VPN истекает через 24 часа!\n\n"
          "Это последнее напоминание за день. Продлите подписку сейчас!",
    
    "12h": "🚨 Осталось 12 часов до окончания подписки Nemo VPN!\n\n"
          "Поторопитесь продлить, чтобы не потерять доступ.",
    
    "6h": "⛔ Ваша подписка Nemo VPN истекает через 6 часов!\n\n"
          "Продлите прямо сейчас, чтобы не прерывать соединение.",
    
    "3h": "⛔ Осталось 3 часа до окончания подписки!\n\n"
          "Не рискуйте своей безопасностью — продлите Nemo VPN.",
    
    "2h": "🔴 Ваша подписка Nemo VPN истекает через 2 часа!\n\n"
          "Это критическое время! Продлевайте немедленно.",
    
    "1h": "🔴 ПОСЛЕДНЕЕ НАПОМИНАНИЕ!\n\n"
          "Ваша подписка Nemo VPN истекает через 1 час!\n\n"
          "Продлите прямо сейчас, чтобы не потерять доступ к VPN!",
    
    "expired": "❌ Ваша подписка Nemo VPN истекла.\n\n"
               "Для возобновления доступа приобретите новую подписку.\n\n"
               "Мы ценим вас и надеемся на продолжение сотрудничества!",
}


class NotificationScheduler:
    """
    Планировщик уведомлений об истечении подписки.
    
    Проверяет пользователей каждые 10 минут и отправляет уведомления
    согласно настроенным интервалам.
    """
    
    def __init__(self, bot: Bot, db_session_factory):
        self.bot = bot
        self.db_session_factory = db_session_factory
        self.scheduler = AsyncIOScheduler()
        self._is_running = False
    
    async def start(self):
        """Запустить планировщик."""
        if self._is_running:
            logger.warning("Планировщик уже запущен")
            return
        
        # Добавляем задачу проверки уведомлений
        self.scheduler.add_job(
            self._check_notifications,
            trigger=IntervalTrigger(minutes=10),
            id="check_notifications",
            name="Проверка уведомлений об истечении",
            replace_existing=True,
        )
        
        # Добавляем задачу проверки истекших пользователей
        self.scheduler.add_job(
            self._check_expired_users,
            trigger=IntervalTrigger(hours=1),
            id="check_expired",
            name="Проверка истекших пользователей",
            replace_existing=True,
        )
        
        self.scheduler.start()
        self._is_running = True
        
        logger.info("Планировщик уведомлений запущен")
    
    async def stop(self):
        """Остановить планировщик."""
        if not self._is_running:
            return
        
        self.scheduler.shutdown()
        self._is_running = False
        
        logger.info("Планировщик уведомлений остановлен")
    
    async def _check_notifications(self):
        """Проверить и отправить уведомления."""
        logger.debug("Запуск проверки уведомлений...")
        
        async with self.db_session_factory() as session:
            try:
                # Получаем всех пользователей с активной подпиской
                now = datetime.utcnow()
                
                result = await session.execute(
                    select(User).where(
                        and_(
                            User.expire_date.isnot(None),
                            User.expire_date > now,
                            User.marzban_username.isnot(None),
                        )
                    )
                )
                users: List[User] = result.scalars().all()
                
                logger.debug(f"Найдено {len(users)} пользователей с активной подпиской")
                
                for user in users:
                    await self._process_user_notification(session, user, now)
                
            except Exception as e:
                logger.error(f"Ошибка проверки уведомлений: {e}")
    
    async def _process_user_notification(
        self,
        session: AsyncSession,
        user: User,
        now: datetime
    ):
        """
        Обработать уведомления для конкретного пользователя.
        
        Args:
            session: Сессия БД.
            user: Пользователь.
            now: Текущее время.
        """
        if not user.expire_date:
            return
        
        # Вычисляем время до истечения в минутах
        time_left = user.expire_date - now
        minutes_left = int(time_left.total_seconds() / 60)
        
        # Получаем уже отправленные уведомления
        notified_steps = user.last_notified_step.split(",") if user.last_notified_step else []
        
        # Проверяем каждый интервал
        for minutes, step_name in NOTIFICATION_STEPS.items():
            # Проверяем, нужно ли отправлять уведомление
            if minutes_left <= minutes and minutes_left > minutes - 30:  # Окно 30 минут
                # Проверяем, не отправляли ли уже это уведомление
                if step_name not in notified_steps:
                    await self._send_notification(session, user, step_name)
                    notified_steps.append(step_name)
        
        # Обновляем список отправленных уведомлений
        user.last_notified_step = ",".join(notified_steps)
        await session.commit()
    
    async def _send_notification(
        self,
        session: AsyncSession,
        user: User,
        step_name: str
    ):
        """
        Отправить уведомление пользователю.
        
        Args:
            session: Сессия БД.
            user: Пользователь.
            step_name: Тип уведомления.
        """
        message_text = NOTIFICATION_MESSAGES.get(step_name, "")
        if not message_text:
            return
        
        try:
            # Отправляем сообщение
            message = await self.bot.send_message(
                chat_id=user.user_id,
                text=message_text,
            )
            
            # Сохраняем в БД
            notification = Notification(
                user_id=user.user_id,
                notification_type=step_name,
                message_id=message.message_id,
            )
            session.add(notification)
            await session.commit()
            
            logger.info(f"Отправлено уведомление {step_name} пользователю {user.user_id}")
            
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления пользователю {user.user_id}: {e}")
            await session.rollback()
    
    async def _check_expired_users(self):
        """Проверить и обработать истекших пользователей."""
        logger.debug("Запуск проверки истекших пользователей...")
        
        async with self.db_session_factory() as session:
            try:
                now = datetime.utcnow()
                expired_threshold = now - timedelta(hours=24)
                
                # Находим пользователей, у которых подписка истекла более 24 часов назад
                result = await session.execute(
                    select(User).where(
                        and_(
                            User.expire_date.isnot(None),
                            User.expire_date < expired_threshold,
                            User.marzban_username.isnot(None),
                        )
                    )
                )
                expired_users: List[User] = result.scalars().all()
                
                logger.debug(f"Найдено {len(expired_users)} истекших пользователей")
                
                for user in expired_users:
                    await self._process_expired_user(session, user)
                
            except Exception as e:
                logger.error(f"Ошибка проверки истекших пользователей: {e}")
    
    async def _process_expired_user(
        self,
        session: AsyncSession,
        user: User
    ):
        """
        Обработать истекшего пользователя.
        
        Args:
            session: Сессия БД.
            user: Пользователь.
        """
        try:
            # Отправляем уведомление об истечении
            message_text = NOTIFICATION_MESSAGES.get("expired", "")
            
            await self.bot.send_message(
                chat_id=user.user_id,
                text=message_text,
            )
            
            # Удаляем пользователя из Marzban (опционально)
            # from services.marzban_api import marzban_service
            # await marzban_service.delete_user(user.marzban_username)
            
            logger.info(f"Обработан истекший пользователь {user.user_id}")
            
        except Exception as e:
            logger.error(f"Ошибка обработки истекшего пользователя {user.user_id}: {e}")
            await session.rollback()


# Глобальный экземпляр (будет инициализирован в bot.py)
scheduler: NotificationScheduler = None


def create_scheduler(bot: Bot, db_session_factory) -> NotificationScheduler:
    """Создать глобальный экземпляр планировщика."""
    global scheduler
    scheduler = NotificationScheduler(bot, db_session_factory)
    return scheduler


def get_scheduler() -> NotificationScheduler:
    """Получить глобальный экземпляр планировщика."""
    return scheduler

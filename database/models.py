"""
Модуль моделей базы данных для Nemo VPN Bot.

ИЗМЕНЕНИЯ:
- Добавлено поле expire_standard (DateTime) — срок стандартной подписки
- Добавлено поле expire_premium (DateTime) — срок VIP подписки (обход белых списков)
- Добавлено поле channel_bonus_given (Boolean) — флаг: начислен ли бонус +3 дня за подписку на канал
- expire_date остаётся для обратной совместимости = max(expire_standard, expire_premium)

MIGRATION: Новые колонки nullable, старые записи не ломаются.
При первом запуске с новыми полями — SQLAlchemy создаст колонки автоматически (если используется create_all).
Для существующей БД нужен ALTER TABLE:
  ALTER TABLE users ADD COLUMN expire_standard DATETIME NULL;
  ALTER TABLE users ADD COLUMN expire_premium DATETIME NULL;
  ALTER TABLE users ADD COLUMN channel_bonus_given BOOLEAN DEFAULT 0;
"""
from datetime import datetime
from sqlalchemy import (
    Column, BigInteger, String, Boolean, Float, DateTime,
    ForeignKey, Text, Integer, UniqueConstraint
)
from sqlalchemy.orm import relationship, Mapped, mapped_column
from typing import Optional, List
from database.engine import Base

class User(Base):
    """Модель пользователя Telegram / VK."""
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    
    vk_id: Mapped[Optional[int]] = mapped_column(BigInteger, unique=True, nullable=True)
    platform: Mapped[str] = mapped_column(String(10), default="tg")
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    marzban_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, unique=True)
    marzban_username_vk: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    is_trial_used: Mapped[bool] = mapped_column(Boolean, default=False)
    balance: Mapped[float] = mapped_column(Float, default=0.0)
    referral_balance: Mapped[float] = mapped_column(Float, default=0.0)
    referrer_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.user_id"), nullable=True)
    
    # Единый expire_date = max(expire_standard, expire_premium). Остаётся для обратной совместимости.
    expire_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_notified_step: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    tier: Mapped[str] = mapped_column(String(50), default="standard")
    
    # Раздельные сроки подписок по тарифам
    expire_standard: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    expire_premium: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    device_count: Mapped[int] = mapped_column(Integer, default=1)
    gb_limit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    task_channel_sub: Mapped[bool] = mapped_column(Boolean, default=False)
    refs_paid_count: Mapped[int] = mapped_column(Integer, default=0)
    
    # Бонус за подписку на канал (начисляется 1 раз при первой оплате)
    channel_bonus_given: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    referrer: Mapped[Optional["User"]] = relationship(
        "User", back_populates="referrals", remote_side=[user_id], foreign_keys=[referrer_id]
    )
    referrals: Mapped[List["User"]] = relationship(
        "User", back_populates="referrer", foreign_keys=[referrer_id]
    )
    transactions: Mapped[List["Transaction"]] = relationship(
        "Transaction", back_populates="user", cascade="all, delete-orphan"
    )
    notifications: Mapped[List["Notification"]] = relationship(
        "Notification", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User(user_id={self.user_id}, platform={self.platform}, username={self.username}, tier={self.tier})>"

    def recalculate_expire_date(self):
        """Пересчитать единый expire_date как max(expire_standard, expire_premium)."""
        dates = [d for d in [self.expire_standard, self.expire_premium] if d is not None]
        self.expire_date = max(dates) if dates else None

class Transaction(Base):
    """Модель транзакции (платежа)."""
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.user_id"), nullable=False)
    
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="RUB")
    payment_method: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    payment_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped["User"] = relationship("User", back_populates="transactions")

    __table_args__ = (
        UniqueConstraint("payment_id", name="uq_transaction_payment_id"),
    )

class Notification(Base):
    """Модель отправленных уведомлений."""
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.user_id"), nullable=False)
    notification_type: Mapped[str] = mapped_column(String(50), nullable=False)
    message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship("User", back_populates="notifications")

class PaymentInvoice(Base):
    """Модель счета на оплату."""
    __tablename__ = "payment_invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.user_id"), nullable=False)
    
    invoice_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="RUB")
    payment_method: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    device_count: Mapped[int] = mapped_column(Integer, default=1)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class BotSettings(Base):
    """Модель настроек бота."""
    __tablename__ = "bot_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class GiftCode(Base):
    """Модель подарочного кода."""
    __tablename__ = "gift_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    creator_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tier: Mapped[str] = mapped_column(String(50), default="standard")
    days: Mapped[int] = mapped_column(Integer, nullable=False)
    gb_limit: Mapped[float] = mapped_column(Float, default=0)
    is_used: Mapped[bool] = mapped_column(Boolean, default=False)
    used_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<GiftCode(code={self.code}, tier={self.tier}, days={self.days}, is_used={self.is_used})>"

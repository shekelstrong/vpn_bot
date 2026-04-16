"""
Модуль моделей базы данных для Nemo VPN Bot.
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

    # Главный ID (для TG это TG ID, для VK это 2 триллиона + VK ID)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    
    vk_id: Mapped[Optional[int]] = mapped_column(BigInteger, unique=True, nullable=True)
    platform: Mapped[str] = mapped_column(String(10), default="tg")
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    marzban_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, unique=True)
    
    is_trial_used: Mapped[bool] = mapped_column(Boolean, default=False)
    balance: Mapped[float] = mapped_column(Float, default=0.0)
    referral_balance: Mapped[float] = mapped_column(Float, default=0.0)
    referrer_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.user_id"), nullable=True)
    
    expire_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_notified_step: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    tier: Mapped[str] = mapped_column(String(50), default="standard")
    
    # === НОВЫЕ ПОЛЯ ДЛЯ MINI APP И ЗАДАНИЙ ===
    device_count: Mapped[int] = mapped_column(Integer, default=1)
    gb_limit: Mapped[Optional[float]] = mapped_column(Float, nullable=True) # None = безлимитный трафик (для старых пользователей)
    task_channel_sub: Mapped[bool] = mapped_column(Boolean, default=False) # Выполнено ли задание подписки на канал
    refs_paid_count: Mapped[int] = mapped_column(Integer, default=0) # Количество рефералов, совершивших покупку
    # =========================================

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Связи
    referrer: Mapped[Optional["User"]] = relationship(
        "User",
        back_populates="referrals",
        remote_side=[user_id],
        foreign_keys=[referrer_id]
    )
    referrals: Mapped[List["User"]] = relationship(
        "User",
        back_populates="referrer",
        foreign_keys=[referrer_id]
    )
    transactions: Mapped[List["Transaction"]] = relationship(
        "Transaction",
        back_populates="user",
        cascade="all, delete-orphan"
    )
    notifications: Mapped[List["Notification"]] = relationship(
        "Notification",
        back_populates="user",
        cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User(user_id={self.user_id}, platform={self.platform}, username={self.username}, tier={self.tier})>"

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

    def __repr__(self) -> str:
        return f"<Transaction(id={self.id}, user_id={self.user_id}, amount={self.amount}, status={self.status})>"

class Notification(Base):
    """Модель отправленных уведомлений."""
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.user_id"), nullable=False)
    
    notification_type: Mapped[str] = mapped_column(String(50), nullable=False)
    message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship("User", back_populates="notifications")

    def __repr__(self) -> str:
        return f"<Notification(id={self.id}, user_id={self.user_id}, type={self.notification_type})>"

class PaymentInvoice(Base):
    """Модель счета на оплату (для отслеживания статусов)."""
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<PaymentInvoice(id={self.id}, invoice_id={self.invoice_id}, status={self.status})>"

class BotSettings(Base):
    """Модель настроек бота."""
    __tablename__ = "bot_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<BotSettings(key={self.key}, value={self.value})>"
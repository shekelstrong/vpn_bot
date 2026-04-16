"""
Модуль подключения к базе данных.
Асинхронный движок SQLAlchemy.
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker, AsyncEngine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text
from typing import Optional

from config import settings

class Base(DeclarativeBase):
    """Базовый класс для всех моделей."""
    pass

# Глобальные переменные для движка и сессии
engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker] = None

def get_engine() -> AsyncEngine:
    """Получить или создать асинхронный движок."""
    global engine
    if engine is None:
        # Используем PostgreSQL из файла конфигурации (.env)
        engine = create_async_engine(
            settings.DATABASE_URL,
            echo=False, # Отключаем спам SQL-запросов в логи
        )
    return engine

def get_session_factory() -> async_sessionmaker:
    """Получить фабрику сессий."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )
    return _session_factory

async def get_db_session():
    """Получить новую сессию базы данных."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

async def create_tables():
    """Создать все таблицы в базе данных."""
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def drop_tables():
    """Удалить все таблицы в базе данных (для отладки)."""
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

async def init_db():
    """Инициализировать базу данных: создать таблицы и применить миграции."""
    await create_tables()
    
    # Безопасная миграция: добавляем колонки "на горячую", если их нет.
    # Это гарантированно сохранит всех старых пользователей, их балансы и подписки.
    async with get_engine().begin() as conn:
        try:
            await conn.execute(text("ALTER TABLE users ADD COLUMN tier VARCHAR(50) DEFAULT 'standard'"))
        except Exception:
            # Ошибка здесь означает, что колонка уже создана ранее. Игнорируем.
            pass
            
        # === Миграции для Mini App ===
        try:
            await conn.execute(text("ALTER TABLE users ADD COLUMN device_count INTEGER DEFAULT 1"))
        except Exception:
            pass
            
        try:
            await conn.execute(text("ALTER TABLE users ADD COLUMN gb_limit FLOAT"))
        except Exception:
            pass
            
        try:
            await conn.execute(text("ALTER TABLE users ADD COLUMN task_channel_sub BOOLEAN DEFAULT FALSE"))
        except Exception:
            pass
            
        try:
            await conn.execute(text("ALTER TABLE users ADD COLUMN refs_paid_count INTEGER DEFAULT 0"))
        except Exception:
            pass

async def close_db():
    """Закрыть соединения с базой данных."""
    global engine, _session_factory
    if engine:
        await engine.dispose()
        engine = None
        _session_factory = None
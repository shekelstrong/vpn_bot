"""
Модуль подключения к базе данных.
Асинхронный движок SQLAlchemy.
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker, AsyncEngine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text
from typing import Optional
from loguru import logger

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
            echo=False,
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
    logger.info("🛠 Инициализация структуры базы данных...")
    await create_tables()
    
    # Прямое применение миграций через ALTER TABLE IF NOT EXISTS (поддерживается в PG 9.6+)
    # Это гарантирует, что новые колонки появятся в базе без удаления старых данных.
    async with get_engine().begin() as conn:
        migrations = [
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS tier VARCHAR(50) DEFAULT 'standard'",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS device_count INTEGER DEFAULT 1",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS gb_limit FLOAT",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS task_channel_sub BOOLEAN DEFAULT FALSE",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS refs_paid_count INTEGER DEFAULT 0"
        ]
        
        for sql in migrations:
            try:
                await conn.execute(text(sql))
            except Exception as e:
                logger.error(f"⚠️ Ошибка при выполнении миграции ({sql}): {e}")

    logger.info("✅ Миграции базы данных завершены")

async def close_db():
    """Закрыть соединения с базой данных."""
    global engine, _session_factory
    if engine:
        await engine.dispose()
        engine = None
        _session_factory = None
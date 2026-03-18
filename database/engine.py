"""
Модуль подключения к базе данных.
Асинхронный движок SQLAlchemy для SQLite (локальная база).
"""
import os
from pathlib import Path
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker, AsyncEngine
from sqlalchemy.orm import DeclarativeBase
from typing import Optional

class Base(DeclarativeBase):
    """Базовый класс для всех моделей."""
    pass

# Глобальные переменные для движка и сессии
engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker] = None

# Жестко задаем абсолютный путь к файлу БД в корне проекта (рядом с bot.py)
BASE_DIR = Path(__file__).parent.parent
DB_PATH = BASE_DIR / "vpn_bot.db"
SQLITE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

def get_engine() -> AsyncEngine:
    """Получить или создать асинхронный движок."""
    global engine
    if engine is None:
        # Игнорируем .env и используем наш железобетонный локальный путь
        engine = create_async_engine(
            SQLITE_URL,
            echo=True, # Включаем вывод SQL-запросов в терминал для отладки
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
    async with get_session_factory() as session:
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
    """Инициализировать базу данных: создать таблицы."""
    await create_tables()

async def close_db():
    """Закрыть соединения с базой данных."""
    global engine, _session_factory
    if engine:
        await engine.dispose()
        engine = None
        _session_factory = None
# AGENTS.md - Руководство для агентов кода

## 🚀 Команды

### Запуск и тестирование
- `python bot.py` - запуск бота
- `python webhooks.py` - запуск вебхуков
- `pytest tests/` - все тесты
- `pytest tests/test_file.py::test_function` - один тест
- `pytest -v` - подробный вывод

### Линтинг и типизация
- `ruff check .` - проверка стиля
- `ruff format .` - форматирование
- `mypy .` - проверка типов
- `ruff check . && ruff format --check . && mypy .` - все проверки

### Docker
- `docker-compose up -d --build` - запуск сервисов
- `docker-compose logs -f bot` - логи бота
- `docker-compose down` - остановка сервисов

## 📝 Стиль кода

### Импорты
1. Стандартные библиотеки Python
2. Сторонние библиотеки
3. Локальные модули проекта

```python
import os
from datetime import datetime

from aiogram import Router
from sqlalchemy import select
from loguru import logger

from database.models import User
from services.marzban_api import marzban_service
```

### Типизация
- Всегда используйте type hints
- `Optional[T]` для nullable значений
- `List[T]`, `Dict[K, V]` из `typing`
- `Mapped[T]` для SQLAlchemy моделей

```python
from typing import Optional, List, Dict, Any

async def get_user(user_id: int) -> Optional[User]:
    """Получить пользователя по ID."""
    pass
```

### Именование
- Переменные и функции: `snake_case`
- Классы: `PascalCase`
- Константы: `UPPER_CASE`
- Приватные методы: `_leading_underscore`
- Асинхронные функции: `async def`

### Документация
- Docstrings на русском языке
- Формат: """Краткое описание.\n\nПодробное описание."""
- Для сложных функций добавляйте Args и Returns

```python
async def create_user(tg_id: int, username: Optional[str] = None) -> Dict[str, Any]:
    """Создать нового пользователя в Marzban.
    
    Args:
        tg_id: Telegram ID пользователя
        username: Имя пользователя (опционально)
    
    Returns:
        Словарь с данными созданного пользователя
    """
    pass
```

### Обработка ошибок
- Используйте try-except для внешних вызовов
- Логируйте ошибки через `logger.error()`, `logger.warning()`, `logger.critical()`
- Не скрывайте ошибки без логирования

```python
try:
    result = await marzban_service.create_user(tg_id, username)
    logger.info(f"Пользователь {tg_id} создан успешно")
except httpx.HTTPStatusError as e:
    logger.error(f"Ошибка HTTP при создании пользователя: {e}")
    raise
```

## 🔧 Архитектура

### Структура
```
vpn_bot/
├── bot.py, webhooks.py, config.py
├── handlers/ - обработчики команд (start, profile, buy, trial, help, admin, referrals)
├── services/ - внешние API (marzban_api, payment_crypto, payment_platega)
├── database/ - модели и движок БД
├── keyboards/ - inline и reply клавиатуры
└── utils/ - scheduler, states
```

### Принципы
- Асинхронность: весь код async/await
- ORM: SQLAlchemy 2.0 async с AsyncSession
- Логирование: loguru
- Конфигурация: Pydantic Settings из .env
- Роутеры: aiogram Router

### База данных
```python
async with session_factory() as session:
    user = User(user_id=tg_id, username=username)
    session.add(user)
    await session.commit()
    await session.refresh(user)
```

### API (httpx)
- `httpx.AsyncClient`
- Таймаут 30 секунд
- Для macOS: `verify=False`
- Механизм ретраев

## 🎯 Специфические правила

### Telegram Bot (aiogram 3.x)
- `Router()` для модульности
- Команды: `Command("start")`, `CommandStart()`
- Callback: `F.data == "back_to_main"`
- Текст: `F.text.startswith("Мой профиль")`
- HTML parse_mode по умолчанию

### Локализация и безопасность
- Все сообщения, комментарии, документация и логи на русском
- Не коммитьте `.env`
- Не логируйте секреты
- Используйте `config.py` для настроек
- Проверяйте `user_id in settings.admin_ids_list` для админских команд

### Планировщик (APScheduler)
- Интегрирован в bot.py
- Не создавайте дополнительные планировщики
- Используйте `get_scheduler()` для доступа

## ⚠️ Важные замечания
- SSL/TLS: патч для macOS (bot.py:12-16)
- Вебхуки: отдельный процесс на порту 8080
- Реферальная система: 3-уровневая (15%, 10%, 5%)
- Триал: 24 часа, 1 GB, один на пользователя
- Подписка: 100₽/месяц, VLESS Reality

## 📦 Основные зависимости
- aiogram>=3.3.0, sqlalchemy>=2.0.0, asyncpg>=0.29.0
- httpx>=0.25.0, apscheduler>=3.10.0
- pydantic>=2.0.0, loguru>=0.7.0

## 🔍 Отладка
- `/ping` - проверка работоспособности
- `/me` - информация о пользователе
- Логи: `logs/` директория
- Docker: `docker-compose logs -f bot`

---

**Рабочий процесс**: изучите код → следуйте стилю → добавляйте type hints → пишите docstrings → логируйте → обрабатывайте ошибки → не ломайте функционал

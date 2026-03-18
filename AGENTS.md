# AGENTS.md - Руководство для агентов кода

## 🚀 Команды для запуска и тестирования

### Основные команды
- **Запуск бота**: `python bot.py`
- **Запуск вебхуков**: `python webhooks.py`
- **Установка зависимостей**: `pip install -r requirements.txt`

### Docker команды
- **Запуск всех сервисов**: `docker-compose up -d --build`
- **Просмотр логов**: `docker-compose logs -f bot`
- **Остановка сервисов**: `docker-compose down`
- **Перезапуск бота**: `docker-compose restart bot`

### Тестирование
- **Проверка бота**: `/ping` - проверка работоспособности
- **Информация о пользователе**: `/me` - данные текущего пользователя
- **Проверка админки**: `/admin` - админ-панель (только для ADMIN_IDS)
- **Запуск тестов (pytest)**: `pytest tests/` - все тесты
- **Запуск одного теста**: `pytest tests/test_file.py::test_function`
- **Запуск с подробным выводом**: `pytest -v`
- **Запуск конкретного файла**: `pytest tests/test_specific.py`

### Линтинг и форматирование
- **Проверка кода (ruff)**: `ruff check .` - проверка стиля
- **Форматирование (ruff)**: `ruff format .` - автоформатирование
- **Типизация (mypy)**: `mypy .` - проверка типов
- **Все проверки**: `ruff check . && ruff format --check . && mypy .`

### Логи
- Логи сохраняются в папку `logs/` с ротацией по дням
- Формат: `bot_YYYY-MM-DD.log`
- Уровень логирования по умолчанию: INFO

## 📝 Стиль кода

### Импорты
Импорты должны быть организованы в следующем порядке:
1. Стандартные библиотеки Python
2. Сторонние библиотеки
3. Локальные модули проекта

Пример:
```python
import os
import asyncio
from datetime import datetime

from aiogram import Router, F
from sqlalchemy import select
from loguru import logger

from database.models import User
from services.marzban_api import marzban_service
```

### Типизация
- **Всегда** используйте type hints для функций и методов
- Используйте `Optional[T]` для nullable значений
- Используйте `List[T]`, `Dict[K, V]` из модуля `typing`
- Для SQLAlchemy моделей используйте `Mapped[T]` (SQLAlchemy 2.0)

Пример:
```python
from typing import Optional, List, Dict, Any

async def get_user(user_id: int) -> Optional[User]:
    """Получить пользователя по ID."""
    pass

async def process_data(data: Dict[str, Any]) -> List[User]:
    """Обработать данные."""
    pass
```

### Именование
- **Переменные и функции**: `snake_case`
- **Классы**: `PascalCase`
- **Константы**: `UPPER_CASE`
- **Приватные методы**: `_leading_underscore`
- **Асинхронные функции**: всегда начинаются с `async def`

### Документация
- Все функции и классы должны иметь docstrings на русском языке
- Формат: """Краткое описание.\n\nПодробное описание."""
- Для сложных функций добавляйте Args и Returns

Пример:
```python
async def create_user(
    tg_id: int,
    username: Optional[str] = None,
    expire_days: int = 30
) -> Dict[str, Any]:
    """
    Создать нового пользователя в Marzban.

    Args:
        tg_id: Telegram ID пользователя
        username: Имя пользователя (опционально)
        expire_days: Срок действия в днях

    Returns:
        Словарь с данными созданного пользователя
    """
    pass
```

### Обработка ошибок
- Всегда используйте try-except блоки для внешних вызовов (API, БД)
- Логируйте ошибки через `logger.error()` или `logger.warning()`
- Для критических ошибок - используйте `logger.critical()`
- Не скрывайте ошибки без логирования

Пример:
```python
try:
    result = await marzban_service.create_user(tg_id, username)
    logger.info(f"Пользователь {tg_id} создан успешно")
except httpx.HTTPStatusError as e:
    logger.error(f"Ошибка HTTP при создании пользователя: {e}")
    raise
except Exception as e:
    logger.error(f"Неожиданная ошибка: {e}")
    raise
```

## 🔧 Архитектура проекта

### Структура директорий
```
vpn_bot/
├── bot.py              # Точка входа (запуск через polling)
├── webhooks.py         # Вебхуки для платежей
├── config.py           # Pydantic настройки
├── handlers/           # Обработчики команд бота
│   ├── start.py        # /start и главное меню
│   ├── profile.py      # Профиль пользователя
│   ├── buy.py          # Покупка подписки
│   ├── trial.py        # Бесплатный триал
│   ├── help.py         # Помощь
│   ├── admin.py        # Админ-панель
│   └── referrals.py    # Реферальная система
├── services/           # Внешние сервисы
│   ├── marzban_api.py  # Клиент Marzban API
│   ├── payment_crypto.py  # CryptoBot
│   └── payment_platega.py # Platega
├── database/           # База данных
│   ├── models.py       # SQLAlchemy модели
│   └── engine.py       # Движок БД
├── keyboards/          # Клавиатуры бота
│   ├── inline.py       # Inline кнопки
│   └── reply.py        # Reply кнопки
└── utils/              # Утилиты
    ├── scheduler.py    # Планировщик уведомлений
    └── states.py       # FSM состояния
```

### Ключевые принципы
1. **Асинхронность**: весь код асинхронный (async/await)
2. **ORM**: SQLAlchemy 2.0 async с AsyncSession
3. **Логирование**: loguru для всех операций
4. **Конфигурация**: Pydantic Settings из .env
5. **Роутеры**: aiogram Router для модульности

### Работа с базой данных
- Всегда используйте async context manager: `async with session_factory() as session:`
- Не забывайте делать `await session.commit()` после изменений
- Используйте `await session.refresh(obj)` для обновления объекта

Пример:
```python
async with session_factory() as session:
    user = User(user_id=tg_id, username=username)
    session.add(user)
    await session.commit()
    await session.refresh(user)
```

### Работа с API (httpx)
- Используйте асинхронный клиент: `httpx.AsyncClient`
- Устанавливайте таймаут (обычно 30 секунд)
- Для локальной разработки на macOS: `verify=False` для SSL
- Внедрите механизм ретраев для временных ошибок

### Middleware
- Middleware для БД уже настроен в bot.py
- Сессия БД автоматически передается в обработчики через `data['session']`

## 🎯 Специфические правила

### Telegram Bot (aiogram 3.x)
- Используйте `Router()` для модульности
- Для команд: `Command("start")`, `CommandStart()`
- Для callback: `F.data == "back_to_main"`
- Для текстовых сообщений: `F.text.startswith("Мой профиль")`
- HTML parse_mode по умолчанию

### Локализация
- Все пользовательские сообщения на русском языке
- Все комментарии и документация на русском языке
- Логи на русском языке

### Безопасность
- Никогда не коммитите `.env` файл
- Не логируйте секретные данные (токены, пароли)
- Используйте переменные окружения через `config.py`
- Для админских команд проверяйте `user_id in settings.admin_ids_list`

### Планировщик (APScheduler)
- Планировщик уже интегрирован в bot.py
- Не создавайте дополнительные планировщики
- Используйте `get_scheduler()` для доступа к планировщику

## ⚠️ Важные замечания

1. **SSL/TLS**: На macOS используется патч для отключения строгой проверки SSL (см. bot.py:12-16)
2. **Вебхуки**: Отдельный процесс на порту 8080, запускается параллельно с ботом
3. **Реферальная система**: 3-уровневая (15%, 10%, 5%)
4. **Триал**: 24 часа, 1 GB трафика, один на пользователя
5. **Подписка**: 100₽/месяц, VLESS Reality протокол

## 📦 Зависимости

Основные зависимости:
- aiogram>=3.3.0 - Telegram Bot framework
- sqlalchemy>=2.0.0 - ORM
- asyncpg>=0.29.0 - PostgreSQL async driver
- httpx>=0.25.0 - Async HTTP client
- apscheduler>=3.10.0 - Task scheduler
- pydantic>=2.0.0 - Data validation
- loguru>=0.7.0 - Logging

## 🔍 Отладка

- Используйте `/ping` для проверки работоспособности
- Используйте `/me` для просмотра информации о текущем пользователе
- Проверяйте логи в `logs/` директории
- Для Docker: `docker-compose logs -f bot`

## 📝 Рабочий процесс

1. Перед началом работы изучите существующий код в соответствующем модуле
2. Следуйте существующему стилю кода
3. Добавляйте type hints везде, где это возможно
4. Пишите docstrings на русском языке
5. Логируйте все важные операции
6. Обрабатывайте ошибки gracefully
7. Тестируйте изменения локально перед коммитом
8. Не ломайте существующий функционал

---

**Важно**: Этот файл создан для агентов кода. При внесении изменений убедитесь, что они соответствуют этому руководству.

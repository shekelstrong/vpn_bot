# AGENTS.md - Руководство для агентов кода

## 🚀 Команды

### Установка зависимостей
```bash
pip install -r requirements.txt
# Dev-зависимости для линтинга и тестирования
pip install pytest pytest-asyncio ruff mypy
```

### Запуск
- `python bot.py` - запуск бота с вебхук-сервером (встроенный, порт из WEB_PORT)
- Вебхук-сервер запускается автоматически вместе с ботом и обрабатывает платежи от CryptoBot и Platega

### Тестирование
- `pytest tests/` - все тесты
- `pytest tests/test_file.py` - конкретный файл тестов
- `pytest tests/test_file.py::test_function` - конкретный тест
- `pytest -v` - подробный вывод
- `pytest -xvs` - остановка при первой ошибке, подробный вывод

### Линтинг и форматирование
- `ruff check .` - проверка стиля
- `ruff check --fix .` - исправление найденных проблем
- `ruff format .` - форматирование
- `mypy .` - проверка типов
- `ruff check . && ruff format --check . && mypy .` - все проверки последовательно

## 📝 Стиль кода

### Импорты (строгий порядок)
```python
# 1. Стандартные библиотеки Python
import os
from datetime import datetime

# 2. Сторонние библиотеки (по алфавиту)
from aiogram import Router, F
from loguru import logger
from sqlalchemy import select

# 3. Локальные модули проекта (по алфавиту)
from config import settings
from database.models import User
```

### Типизация (обязательно)
- Всегда используйте type hints для всех функций и переменных
- `Optional[T]` для nullable значений
- `await` для асинхронных функций
- Максимальная длина строки: 120 символов

```python
from typing import Optional

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
- Колбек-функции: `on_<action>`

### Документация и логирование
- Docstrings на русском языке для всех публичных функций
- Формат: """Краткое описание."""
- Логи на русском языке через `logger.info()`, `logger.error()`, `logger.critical()`
- Не логируйте секреты

### Обработка ошибок
- Используйте try-except для всех внешних вызовов (API, БД)
- Никогда не скрывайте ошибки без логирования
- Возвращайте понятные сообщения об ошибках для пользователей

```python
from httpx import HTTPStatusError

try:
    result = await marzban_service.create_user(tg_id)
    logger.info(f"Пользователь {tg_id} создан успешно")
except HTTPStatusError as e:
    logger.error(f"Ошибка HTTP при создании пользователя {tg_id}: {e}")
    raise Exception("Не удалось создать пользователя в Marzban")
except Exception as e:
    logger.critical(f"Неожиданная ошибка: {e}")
    raise
```

## 🔧 Архитектура

### Структура проекта
```
vpn_bot/
├── bot.py              # Главный файл бота
├── webhooks.py         # Вебхуки для платежей
├── config.py           # Настройки (Pydantic Settings)
├── handlers/           # Обработчики команд
├── services/           # Внешние API (Marzban, платежи)
├── database/           # База данных (SQLAlchemy 2.0)
├── keyboards/          # Inline и reply клавиатуры
└── utils/              # Утилиты (scheduler, states)
```

### Основные принципы
- **Асинхронность**: Весь код использует async/await
- **ORM**: SQLAlchemy 2.0 async с AsyncSession
- **Бот**: aiogram 3.x с Router архитектурой
- **Конфигурация**: Pydantic Settings из .env файла
- **Логирование**: loguru с ротацией логов в logs/
- **HTTP клиент**: httpx.AsyncClient с verify=False для macOS

### Работа с БД (SQLAlchemy 2.0)
```python
from sqlalchemy import select
from database.engine import get_session_factory

async def update_user_balance(user_id: int, amount: int):
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(User).where(User.user_id == user_id)
        )
        user = result.scalar_one_or_none()
        if user:
            user.balance += amount
            await session.commit()
            await session.refresh(user)
```

## 🎯 Специфические правила

### Telegram Bot (aiogram 3.x)
```python
# Роутер для модульности
router = Router(name="feature_router")

# Команды и callback
@router.message(Command("start"))
@router.callback_query(F.data == "back_to_main")

# HTML parse_mode по умолчанию
await message.answer("<b>Жирный</b> текст")
```

### Локализация и безопасность
- **Весь текст на русском**: сообщения, комментарии, документация, логи
- **Безопасность**:
  - Не коммитьте `.env` файл
  - Не логируйте секреты
  - Проверяйте `user_id in settings.admin_ids_list` для админских команд
  - Валидируйте все входные данные от пользователей

### macOS SSL патч
```python
# bot.py:12-16
if not os.environ.get('PYTHONHTTPSVERIFY', '') and getattr(ssl, '_create_unverified_context', None):
    ssl._create_default_https_context = ssl._create_unverified_context
```

### Бизнес-логика
- **Реферальная система**: 3 уровня (15%, 10%, 5%)
- **Триал**: 24 часа, 1 GB трафика, один на пользователя
- **Подписка**: 100₽/месяц, протокол VLESS Reality
- **Вывод средств**: минимальная сумма 1000₽
- **Платежные системы**: CryptoBot (USDT), Platega (банковские карты)

### Платежная система Platega
- **Webhook URL**: формируется как `https://ВАШ_ДОМЕН/webhook/platega`
- **Вебхук-сервер**: запускается автоматически в `bot.py` через `webhook_server.start(bot)`
- **Обработка вебхуков**: файл `services/platega_webhook.py` функция `handle_platega_webhook_update`
- **URL для возврата**: `/pay_success` и `/pay_failed` для перенаправления пользователя в бота после оплаты

---

**Рабочий процесс**: изучите существующий код → следуйте стилю проекта → добавляйте type hints → пишите docstrings → логируйте действия → обрабатывайте ошибки → не ломайте существующий функционал → тестируйте изменения

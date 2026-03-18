# AGENTS.md - Руководство для агентов кода

## 🚀 Команды

### Установка зависимостей
```bash
pip install -r requirements.txt
# Dev-зависимости для линтинга и тестирования
pip install pytest pytest-asyncio ruff mypy
```

### Запуск
- `python bot.py` - запуск бота
- `python webhooks.py` - запуск вебхуков (отдельный процесс, порт 8080)

### Тестирование
- `pytest tests/` - все тесты
- `pytest tests/test_file.py` - конкретный файл тестов
- `pytest tests/test_file.py::test_function` - конкретный тест
- `pytest -v` - подробный вывод
- `pytest --cov` - покрытие кода (если установлен pytest-cov)
- `pytest -xvs` - остановка при первой ошибке, подробный вывод

### Линтинг и форматирование
- `ruff check .` - проверка стиля
- `ruff check --fix .` - исправление найденных проблем
- `ruff format .` - форматирование
- `ruff format --check .` - проверка форматирования без изменений
- `mypy .` - проверка типов
- `ruff check . && ruff format --check . && mypy .` - все проверки последовательно

### Docker
- `docker-compose up -d --build` - запуск сервисов
- `docker-compose logs -f bot` - логи бота
- `docker-compose logs -f webhooks` - логи вебхуков
- `docker-compose down` - остановка сервисов

## 📝 Стиль кода

### Импорты (строгий порядок)
```python
# 1. Стандартные библиотеки Python
import os
import ssl
from datetime import datetime, timedelta

# 2. Сторонние библиотеки (по алфавиту)
import httpx
from aiogram import Router, F, Bot
from aiogram.filters import CommandStart
from loguru import logger
from pydantic import Field
from sqlalchemy import select

# 3. Локальные модули проекта (по алфавиту)
from config import settings
from database.models import User
from keyboards.inline import get_main_menu_keyboard
from services.marzban_api import marzban_service
```

### Типизация (обязательно)
- Всегда используйте type hints для всех функций и переменных
- `Optional[T]` для nullable значений
- `List[T]`, `Dict[K, V]`, `Tuple[T, ...]` из `typing`
- `Mapped[T]` для колонок SQLAlchemy моделей
- `await` для асинхронных функций
- `Any` только когда тип невозможно определить

```python
from typing import Optional, List, Dict, Any

async def get_user(user_id: int) -> Optional[User]:
    """Получить пользователя по ID."""
    pass

async def create_subscription(
    user_id: int,
    months: int
) -> Dict[str, Any]:
    """Создать подписку."""
    pass
```

### Именование
- Переменные и функции: `snake_case`
- Классы: `PascalCase`
- Константы: `UPPER_CASE`
- Приватные методы: `_leading_underscore`
- Асинхронные функции: `async def`
- Колбек-функции: `on_<action>`

### Документация
- Docstrings на русском языке для всех публичных функций и классов
- Формат: """Краткое описание.\n\nПодробное описание."""
- Для функций с параметрами добавляйте Args и Returns
- Максимальная длина строки: 120 символов

```python
async def create_user(tg_id: int, username: Optional[str] = None) -> Dict[str, Any]:
    """Создать нового пользователя в Marzban.
    
    Генерирует уникальное имя пользователя, создает запись в Marzban API
    и добавляет пользователя в локальную базу данных.
    
    Args:
        tg_id: Telegram ID пользователя
        username: Имя пользователя (опционально)
    
    Returns:
        Словарь с данными созданного пользователя: {user_id, marzban_username, ...}
    
    Raises:
        httpx.HTTPStatusError: При ошибке API Marzban
    """
    pass
```

### Обработка ошибок
- Используйте try-except для всех внешних вызовов (API, БД)
- Логируйте ошибки через `logger.error()`, `logger.warning()`, `logger.critical()`
- Никогда не скрывайте ошибки без логирования
- Возвращайте понятные сообщения об ошибках для пользователей

```python
from httpx import HTTPStatusError

try:
    result = await marzban_service.create_user(tg_id, username)
    logger.info(f"Пользователь {tg_id} создан успешно")
except HTTPStatusError as e:
    logger.error(f"Ошибка HTTP при создании пользователя {tg_id}: {e}")
    raise Exception("Не удалось создать пользователя в Marzban")
except Exception as e:
    logger.critical(f"Неожиданная ошибка: {e}")
    raise
```

### Логирование
- Используйте loguru (уже настроен в bot.py)
- Уровни: debug, info, warning, error, critical
- Логи на русском языке
- Не логируйте секреты (токены, пароли, API ключи)

```python
logger.debug(f"Отладочная информация: {data}")
logger.info(f"Пользователь {user_id} выполнил действие")
logger.warning(f"Предупреждение: {message}")
logger.error(f"Ошибка: {error}")
logger.critical(f"Критическая ошибка: {error}")
```

## 🔧 Архитектура

### Структура проекта
```
vpn_bot/
├── bot.py              # Главный файл бота
├── webhooks.py         # Вебхуки для платежей
├── config.py           # Настройки (Pydantic Settings)
├── handlers/           # Обработчики команд
│   ├── start.py        # /start и главное меню
│   ├── profile.py      # Профиль пользователя
│   ├── buy.py          # Покупка подписки
│   ├── trial.py        # Триальный период
│   ├── help.py         # Справка
│   ├── admin.py        # Админ-команды
│   └── referrals.py    # Реферальная система
├── services/           # Внешние API
│   ├── marzban_api.py  # Marzpan API (VPN)
│   ├── payment_crypto.py   # CryptoBot платежи
│   └── payment_platega.py  # Platega платежи
├── database/           # База данных
│   ├── models.py       # SQLAlchemy модели
│   └── engine.py       # AsyncSession factory
├── keyboards/          # Inline и reply клавиатуры
└── utils/              # Утилиты
    ├── scheduler.py    # APScheduler
    └── states.py       # FSM состояния
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

### HTTP запросы (httpx)
```python
import httpx

# Создание клиента (см. services/marzban_api.py)
client = httpx.AsyncClient(timeout=30.0, verify=False)

# Механизм ретраев (см. _request метод)
for attempt in range(3):
    try:
        response = await client.post(url, json=data)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        if attempt == 2:
            raise
        await asyncio.sleep(1)
```

## 🎯 Специфические правила

### Telegram Bot (aiogram 3.x)
```python
# Роутер для модульности
router = Router(name="feature_router")

# Команды
@router.message(Command("start"))
@router.message(CommandStart())

# Callback кнопки
@router.callback_query(F.data == "back_to_main")

# Фильтрация текста
@router.message(F.text.startswith("Мой профиль"))
@router.message(F.text.contains("ключ"))

# HTML parse_mode по умолчанию
await message.answer("<b>Жирный</b> текст")
```

### FSM (состояния)
```python
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

class Form(StatesGroup):
    waiting_for_input = State()

# Получение и сохранение состояния
state = await state.get_data()
await state.update_data(key=value)
await state.clear()
```

### Локализация и безопасность
- **Весь текст на русском**: сообщения, комментарии, документация, логи
- **Безопасность**:
  - Не коммитьте `.env` файл
  - Не логируйте секреты (токены, пароли, ключи API)
  - Используйте `config.py` для всех настроек
  - Проверяйте `user_id in settings.admin_ids_list` для админских команд
  - Валидируйте все входные данные от пользователей

### Планировщик (APScheduler)
- Планировщик интегрирован в bot.py
- Не создавайте дополнительные планировщики
- Используйте `get_scheduler()` для доступа к планировщику
- Добавляйте задачи через `scheduler.add_job(...)`

## ⚠️ Важные замечания

### macOS SSL патч
```python
# bot.py:12-16
if not os.environ.get('PYTHONHTTPSVERIFY', '') and getattr(ssl, '_create_unverified_context', None):
    ssl._create_default_https_context = ssl._create_unverified_context
```

### Вебхуки
- Запускаются отдельным процессом: `python webhooks.py`
- Работают на порту 8080
- Получают уведомления от CryptoBot и Platega

### Бизнес-логика
- **Реферальная система**: 3 уровня (15%, 10%, 5%)
- **Триал**: 24 часа, 1 GB трафика, один на пользователя
- **Подписка**: 100₽/месяц, протокол VLESS Reality
- **Вывод средств**: минимальная сумма 1000₽

## 📦 Основные зависимости
```
aiogram>=3.3.0          # Telegram Bot API
sqlalchemy>=2.0.0       # ORM
asyncpg>=0.29.0         # PostgreSQL async driver
httpx>=0.25.0           # HTTP client
apscheduler>=3.10.0     # Task scheduler
pydantic>=2.0.0         # Data validation
pydantic-settings>=2.0.0 # Settings management
loguru>=0.7.0           # Logging
python-dotenv>=1.0.0    # .env files
aiocryptopay>=0.4.0     # CryptoBot API
qrcode>=7.4.2           # QR codes
```

## 🔍 Отладка

### Команды для проверки
- `/ping` - проверка работоспособности бота
- `/me` - информация о текущем пользователе
- Админ команды: `/admin`, `/stats`, `/broadcast`

### Логи
- Логи хранятся в директории `logs/`
- Формат: `bot_YYYY-MM-DD.log`
- Ротация: каждый день в полночь
- Хранение: 7 дней

### Docker
```bash
docker-compose logs -f bot        # Логи бота
docker-compose logs -f webhooks   # Логи вебхуков
docker-compose exec bot python -c "..."  # Выполнить команду в контейнере
```

---

**Рабочий процесс**: изучите существующий код → следуйте стилю проекта → добавляйте type hints → пишите docstrings → логируйте действия → обрабатывайте ошибки → не ломайте существующий функционал → тестируйте изменения

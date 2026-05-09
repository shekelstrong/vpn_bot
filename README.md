<div align="center">

# 🐟 Nemo VPN — Telegram Bot

**Полнофункциональный Telegram-бот для управления VPN-подпиской**
**Full-featured Telegram bot for managing your VPN subscription**

[![Python 3.10](https://img.shields.io/badge/Python-3.10-blue?logo=python&logoColor=white)](https://python.org)
[![aiogram 3.x](https://img.shields.io/badge/aiogram-3.x-26A5E4?logo=telegram&logoColor=white)](https://github.com/aiogram/aiogram)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Marzban](https://img.shields.io/badge/Marzban-API-green?logo=v2ray&logoColor=white)](https://github.com/gozargah/marzban)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![License](https://img.shields.io/badge/License-Proprietary-red)](LICENSE)

🤖 **Bot:** [@nemo_vpn_bot](https://t.me/nemo_vpn_bot) · 🌐 **Site:** [nemo-landing-gamma.vercel.app](https://nemo-landing-gamma.vercel.app) · 📱 **VK:** [vk.com/nemovpn](https://vk.com/nemovpn)

</div>

---

## 🇷🇺 Описание | 🇬🇧 Description

**🇷🇺** Telegram-бот для VPN-сервиса Nemo. Подписки, оплата (крипто + карты), реферальная система, интеграция с Marzban, VLESS Reality протокол — всё в одном боте.

**🇬🇧** Telegram bot for the Nemo VPN service. Subscriptions, payments (crypto + cards), referral system, Marzban integration, VLESS Reality protocol — all in one bot.

---

## ✨ Возможности | ✨ Features

### 💳 Подписки и оплата | Subscriptions & Payment
- 🛡 **Стандарт** — 100 ₽/мес, безлимитный трафик | **Standard** — 100 ₽/mo, unlimited traffic
- 🚀 **VIP** — 300 ₽/мес, обход белых списков | **VIP** — 300 ₽/mo, whitelist bypass
- 💰 CryptoBot (USDT) + Platega (МИР/СБП/карты) | CryptoBot (USDT) + Platega (cards/SBP)
- 🎁 Подарочные коды — купи VPN в подарок | Gift codes — buy VPN as a gift
- 📦 Докупка трафика для VIP | Traffic top-up for VIP

### 🔐 VPN и протоколы | VPN & Protocols
- 🔑 VLESS Reality — стелс-протокол | stealth protocol
- 📡 Marzban API — управление юзерами | user management
- 🔄 Автоматическая генерация ключей | automatic key generation
- 🛠 Регенерация ключей пользователем | user key regeneration

### 👥 Реферальная система | Referral System
- 💎 3 уровня: 15% / 10% / 5% | 3 tiers: 15% / 10% / 5%
- 💰 Вывод от 1000 ₽ | Withdrawal from 1000 ₽
- 🔗 Уникальная реферальная ссылка | Unique referral link

### 🎯 Бонусы | Bonuses
- 🆓 Триал — 24ч, 1 ГБ (один раз) | Trial — 24h, 1 GB (once)
- 📺 +3 дня за подписку на канал | +3 days for channel subscription
- 👥 +5 / +14 / +30 дней за рефералов | +5 / +14 / +30 days for referrals

### 🔧 Технологии | Tech
- ⚡ aiogram 3.x + Router architecture
- 🐘 PostgreSQL + SQLAlchemy 2.0 async
- 🔔 APScheduler — уведомления об истечении | expiration notifications
- 🌐 Встроенный webhook-сервер (aiohttp) | built-in webhook server
- 🐳 Docker Compose — бот + PostgreSQL + Redis + Nginx

---

## 🏗 Архитектура | Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    Nemo VPN Ecosystem                     │
│                                                          │
│  ┌──────────┐  ┌───────────┐  ┌────────┐  ┌──────────┐ │
│  │ Telegram │  │   VK Bot  │  │ MiniApp│  │ Landing  │ │
│  │   Bot    │  │ (vkbottle)│  │  (JS)  │  │(Next.js) │ │
│  └─────┬────┘  └─────┬─────┘  └───┬────┘  └────┬─────┘ │
│        │              │            │             │       │
│        ▼              ▼            ▼             │       │
│  ┌──────────────────────────────────────┐       │       │
│  │    Python Backend (vpn_bot)          │       │       │
│  │  ┌─────────┐ ┌───────────┐ ┌──────┐ │       │       │
│  │  │aiogram3 │ │aiohttp    │ │APSch │ │       │       │
│  │  │handlers │ │webhook srv│ │eduler│ │       │       │
│  │  └─────────┘ └───────────┘ └──────┘ │       │       │
│  │  ┌──────────┐ ┌──────┐ ┌─────────┐  │       │       │
│  │  │services/ │ │db/   │ │config   │  │       │       │
│  │  │marzban   │ │models│ │pydantic │  │       │       │
│  │  │payments  │ │engine│ │settings │  │       │       │
│  │  └──────────┘ └──────┘ └─────────┘  │       │       │
│  └──────────────┬───────────────────────┘       │       │
│                 │                               │       │
│        ┌────────┴────────┐                      │       │
│        ▼                 ▼                      │       │
│  ┌──────────┐   ┌──────────────┐               │       │
│  │PostgreSQL│   │   Marzban    │               │       │
│  │   (DB)   │   │  (VLESS/Xray)│               │       │
│  └──────────┘   └──────────────┘                      │
│                                                       │
│  ┌──────────┐   ┌──────────┐                          │
│  │  Redis   │   │  Nginx   │                          │
│  └──────────┘   └──────────┘                          │
└──────────────────────────────────────────────────────────┘
```

---

## 🚀 Быстрый старт | Quick Start

### 📋 Предварительные требования | Prerequisites

- Python 3.10+
- Docker & Docker Compose
- PostgreSQL 15+
- Marzban panel with admin access

### 🔧 Установка | Installation

```bash
# Клонируйте репозиторий | Clone the repo
git clone https://github.com/shekelstrong/vpn_bot.git
cd vpn_bot

# Создайте .env файл | Create .env file
cp .env.example .env
# Отредактируйте .env | Edit .env with your values
nano .env

# Запуск через Docker | Run with Docker
docker compose up -d

# Или локально | Or locally
pip install -r requirements.txt
python bot.py
```

### 🐳 Docker Compose

Проект поднимает 5 контейнеров | The project runs 5 containers:

- **nemo_vpn_bot** — Telegram bot
- **nemo_vpn_webhooks** — Webhook server для Platega/CryptoBot
- **nemo_vpn_db** — PostgreSQL 15
- **nemo_vpn_redis** — Redis 7
- **nemo_vpn_nginx** — Nginx reverse proxy

---

## 🔑 Переменные окружения | Environment Variables

| Variable | 🇷🇺 Описание | 🇬🇧 Description | Default |
|---|---|---|---|
| `BOT_TOKEN` | Токен Telegram бота | Telegram bot token | — *(required)* |
| `ADMIN_IDS` | ID админов через запятую | Admin user IDs (comma-separated) | — *(required)* |
| `CHANNEL_USERNAME` | Telegram канал для бонуса | Telegram channel for bonus | `@your_channel` |
| `CHANNEL_CHAT_ID` | Chat ID канала | Channel chat ID | `-1000000000000` |
| `MARZBAN_URL` | URL панели Marzban | Marzban panel URL | `https://your-marzban-url.com` |
| `MARZBAN_ADMIN_USERNAME` | Логин Marzban | Marzban admin username | — *(required)* |
| `MARZBAN_ADMIN_PASSWORD` | Пароль Marzban | Marzban admin password | — *(required)* |
| `DATABASE_URL` | URL подключения к БД | Database connection URL | `sqlite+aiosqlite:///vpn_bot.db` |
| `POSTGRES_PASSWORD` | Пароль PostgreSQL | PostgreSQL password | — |
| `CRYPTO_BOT_TOKEN` | Токен CryptoBot API | CryptoBot API token | — *(required)* |
| `USDT_TO_RUB_RATE` | Курс USDT → RUB | USDT to RUB rate | `90.0` |
| `PLATEGA_MERCHANT_ID` | Merchant ID Platega | Platega merchant ID | — *(required)* |
| `PLATEGA_API_KEY` | API ключ Platega | Platega API key | — *(required)* |
| `PLATEGA_SECRET_KEY` | Секретный ключ Platega | Platega webhook secret | — *(required)* |
| `PLATEGA_BASE_URL` | Базовый URL Platega | Platega base URL | `https://app.platega.io` |
| `WEB_PORT` | Порт webhook-сервера | Webhook server port | `8080` |
| `BASE_URL` | Домен для вебхуков | Base URL for webhooks | `localhost` |
| `VLESS_PORT` | Порт VLESS Reality | VLESS Reality port | `8444` |
| `VLESS_SNI` | SNI для VLESS | VLESS SNI | `your-sni.com` |
| `VLESS_PUBLIC_KEY` | Публичный ключ VLESS | VLESS public key | `your-public-key` |
| `VLESS_SHORT_ID` | Short ID VLESS | VLESS short ID | `fb8e00` |
| `REFERRAL_PERCENTAGES` | Проценты рефералов | Referral percentages (L1,L2,L3) | `15,10,5` |
| `SUBSCRIPTION_PRICE_RUB` | Цена стандартной подписки | Standard subscription price | `100` |
| `PREMIUM_PRICE_RUB` | Цена VIP подписки | VIP subscription price | `300` |

---

## 📁 Структура проекта | Project Structure

```
vpn_bot/
├── bot.py                  # 🤖 Точка входа | Entry point
├── webhooks.py             # 🌐 Webhook-сервер | Webhook server
├── config.py               # ⚙️ Конфигурация | Config (Pydantic Settings)
├── handlers/               # 📨 Обработчики | Command handlers
│   ├── start.py            #    /start, регистрация
│   ├── buy.py              #    Покупка подписки
│   ├── trial.py             #    Триал-период
│   ├── profile.py          #    Профиль пользователя
│   ├── gift.py             #    Подарочные коды
│   ├── referral_buy.py     #    Реферальная покупка
│   ├── referrals.py        #    Реферальная система
│   ├── traffic_buy.py      #    Докупка трафика
│   └── help.py             #    Помощь
├── services/               # 🔌 Внешние API | External services
│   ├── marzban_api.py      #    Marzban API client
│   ├── payment_crypto.py   #    CryptoBot payments
│   ├── payment_platega.py  #    Platega payments
│   ├── crypto_bot_v2.py    #    CryptoBot v2 client
│   ├── crypto_webhook.py   #    CryptoBot webhook handler
│   └── platega_webhook.py  #    Platega webhook handler
├── database/               # 🐘 База данных | Database
│   ├── engine.py           #    Async engine & sessions
│   └── models.py           #    SQLAlchemy 2.0 models
├── keyboards/              # ⌨️ Клавиатуры | Keyboards
│   ├── inline.py           #    Inline keyboards
│   └── reply.py            #    Reply keyboards
├── utils/                  # 🛠 Утилиты | Utilities
│   ├── scheduler.py        #    APScheduler jobs
│   ├── states.py           #    FSM states
│   └── webhook_server.py  #    Webhook HTTP server
├── docker-compose.yml      # 🐳 Docker Compose
├── Dockerfile              # 🐳 Docker image
├── nginx.conf              # 🔀 Nginx config
└── requirements.txt        # 📦 Dependencies
```

---

## 📸 Скриншоты | Screenshots

> 🖼 *Скриншоты будут добавлены* | *Screenshots to be added*

---

## 🔗 Связанные репозитории | Related Repos

| Репозиторий | Описание | Description |
|---|---|---|
| [vpn_bot](https://github.com/shekelstrong/vpn_bot) | 🤖 Telegram VPN бот | Telegram VPN bot |
| [vpn-vk-bot](https://github.com/shekelstrong/vpn-vk-bot) | 💬 VK Community бот | VK Community bot |
| [nemo-vpn-webapp](https://github.com/shekelstrong/nemo-vpn-webapp) | 📱 Telegram Mini App | Telegram Mini App |
| [nemo-landing](https://github.com/shekelstrong/nemo-landing) | 🌐 Лендинг (Next.js) | Landing page |

---

## 📄 Лицензия | License

Proprietary — все права защищены. | All rights reserved.

---

<div align="center">

**🐟 Nemo VPN** — Свобода начинается здесь | Freedom starts here

[🌐 Website](https://nemo-landing-gamma.vercel.app) · [🤖 Telegram](https://t.me/nemo_vpn_bot) · [💬 VK](https://vk.com/nemovpn)

</div>
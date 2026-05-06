<div align="center">

# 🌊 Nemo VPN — Telegram Bot

**Full-featured Telegram bot for VPN subscription management**

[![Python](https://img.shields.io/badge/python-3.11-3776AB?logo=python&logoColor=white)](https://python.org)
[![Aiogram](https://img.shields.io/badge/aiogram-3.x-26A5E4?logo=telegram&logoColor=white)](https://docs.aiogram.dev)
[![Docker](https://img.shields.io/badge/docker-ready-2496ED?logo=docker&logoColor=white)](https://docker.com)
[![PostgreSQL](https://img.shields.io/badge/postgresql-15+-4169E1?logo=postgresql&logoColor=white)](https://postgresql.org)
[![Marzban](https://img.shields.io/badge/marzban-API-orange)](https://marzban.dev)
[![CI/CD](https://img.shields.io/badge/CI%2FCD-GitHub_Actions-2088FF?logo=github-actions&logoColor=white)](https://github.com/shekelstrong/vpn_bot/actions)
[![License](https://img.shields.io/badge/license-proprietary-red)](.)

</div>

## ✨ Features

- 🤖 **Telegram Bot** — Aiogram 3.x with FSM and inline keyboards
- 💳 **CryptoBot + Platega** — crypto & card/SBP payments
- 🚀 **VLESS Reality** — next-gen VPN protocol via Marzban API
- 🛡 **Two tiers** — Standard VPN & Premium (bypass blocking)
- 🔗 **VK↔TG Linking** — unified accounts across Telegram & VK
- 📱 **Mini App** — Telegram Web App for subscription management
- 👥 **3-level referrals** — earn from referred users
- 🎁 **Gift codes** — share VPN with friends
- 📊 **Admin panel** — user search, withdrawal management, stats
- 🔄 **Auto-deploy** — CI/CD via GitHub Actions → server on push

## 🏗 Architecture

```
┌─────────────┐     ┌──────────────┐     ┌────────────┐
│  Telegram   │────▶│  TG VPN Bot  │────▶│  Marzban   │
│   Users     │     │  (Aiogram)   │     │    API     │
└─────────────┘     └──────┬───────┘     └────────────┘
                           │                    ▲
                    ┌──────▼───────┐             │
                    │  PostgreSQL  │             │
                    │   + Redis    │             │
                    └──────┬───────┘             │
                           │                    │
┌─────────────┐     ┌──────▼───────┐     ┌──────┴─────┐
│  VK Users   │────▶│  VK Bot     │────▶│  Marzban   │
│             │     │  (Vkbottle) │     │    API     │
└─────────────┘     └──────────────┘     └────────────┘
```

## 🛠 Tech Stack

| Component | Technology |
|-----------|-----------|
| Bot Framework | Aiogram 3.x |
| Database | PostgreSQL 15 + SQLAlchemy (async) |
| Cache | Redis |
| VPN Panel | Marzban API |
| Protocol | VLESS Reality |
| Payments | CryptoBot, Platega |
| Deploy | Docker Compose + GitHub Actions |
| Mini App | Vanilla JS + Tailwind CSS |

## ⚡ Quick Start

```bash
# Clone
git clone https://github.com/shekelstrong/vpn_bot.git
cd vpn_bot

# Configure
cp .env.example .env
# Edit .env with your tokens and API keys

# Run
docker compose up -d
```

## 📁 Project Structure

```
vpn_bot/
├── handlers/
│   ├── admin/          # Admin panel & notifications
│   ├── buy.py          # Purchase flow
│   ├── start.py        # /start & onboarding
│   ├── profile.py      # User profile & subscription info
│   ├── vk_link.py      # VK↔TG account linking
│   └── platega_webhook.py  # Card payment webhooks
├── services/
│   ├── marzban_api.py   # Marzban API client
│   ├── payment_crypto.py  # CryptoBot integration
│   └── payment_platega.py # Platega integration
├── database/
│   ├── models.py        # SQLAlchemy models
│   └── session.py       # Async DB sessions
├── utils/
│   └── webhook_server.py  # Mini App API server
├── docker-compose.yml
└── Dockerfile
```

## 🔗 Related

- [VK Bot](https://github.com/shekelstrong/vpn-vk-bot) — VK Community version
- [Mini App](https://github.com/shekelstrong/nemo-vpn-webapp) — Telegram Web App
- [Nemo VPN Landing](https://github.com/shekelstrong/nemo-landing) — Website

---

<div align="center">
<sub>Built with ❤️ by <a href="https://github.com/shekelstrong">shekelstrong</a></sub>
</div>

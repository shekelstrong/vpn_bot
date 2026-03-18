# Nemo VPN Bot - Project Context

## Project Overview

**Nemo VPN Bot** is a Telegram bot for selling and managing VPN subscriptions via the Marzban API using the VLESS Reality protocol. It provides a complete solution for VPN subscription management with integrated payment systems, a 3-level referral program, and automated notifications.

### Core Features
- **Free Trial**: 24-hour trial with 1GB traffic limit
- **Paid Subscriptions**: 100₽/month with discounts for longer terms (3/6/12 months)
- **Payment Integration**: CryptoBot (crypto) and Platega (bank cards)
- **Referral System**: 3-level program (15%, 10%, 5% commissions)
- **Auto-notifications**: Expiry reminders at 7d, 5d, 3d, 24h, 12h, 6h, 3h, 2h, 1h
- **Admin Panel**: User management, statistics, broadcasts, gift subscriptions

## Tech Stack

| Category | Technology |
|----------|------------|
| **Language** | Python 3.10+ |
| **Bot Framework** | aiogram 3.x (async) |
| **Database** | PostgreSQL / SQLite + SQLAlchemy 2.0 Async |
| **HTTP Client** | httpx (async) |
| **Scheduler** | APScheduler |
| **Webhooks** | aiohttp (port 8080) |
| **Validation** | Pydantic 2.x |
| **Logging** | loguru |
| **Deployment** | Docker + docker-compose |

## Project Structure

```
vpn_bot/
├── bot.py                  # Main bot entry point (polling)
├── webhooks.py             # Webhook server for payments (port 8080)
├── config.py               # Pydantic settings + DB settings helpers
├── requirements.txt        # Python dependencies
├── docker-compose.yml      # Docker services (bot, webhooks, db, redis)
├── database/
│   ├── models.py           # SQLAlchemy models (User, Transaction, etc.)
│   └── engine.py           # Async engine + session factory
├── handlers/
│   ├── start.py            # /start command, main menu
│   ├── profile.py          # User profile
│   ├── buy.py              # Purchase subscriptions
│   ├── trial.py            # Free trial
│   ├── help.py             # Help & FAQ
│   ├── admin/
│   │   ├── __init__.py     # Admin panel
│   │   ├── notifications.py# Admin/user notifications
│   │   └── settings.py     # Bot settings management
│   └── referrals.py        # Referral program
├── services/
│   ├── marzban_api.py      # Marzban API client
│   ├── payment_crypto.py   # CryptoBot integration
│   └── payment_platega.py  # Platega integration
├── keyboards/
│   ├── inline.py           # Inline keyboards
│   └── reply.py            # Reply keyboards
├── utils/
│   ├── scheduler.py        # Notification scheduler (APScheduler)
│   └── states.py           # FSM states
└── logs/                   # Log files (rotated daily)
```

## Database Models

### User
- `user_id`: Telegram ID (primary key)
- `username`: Telegram username
- `marzban_username`: Unique Marzban username
- `is_trial_used`: Trial usage flag
- `balance`: Main balance (RUB)
- `referral_balance`: Referral earnings (RUB)
- `referrer_id`: Referrer's Telegram ID (self-referential)
- `expire_date`: Subscription expiry date
- `last_notified_step`: Last sent notification step

### Transaction
- `id`, `user_id`, `amount`, `currency`, `payment_method`
- `status`: pending/paid/failed/refunded
- `payment_id`: Payment system ID

### PaymentInvoice
- Tracks invoice status in payment systems

### BotSettings
- Dynamic bot settings stored in DB (prices, discounts, etc.)

### Notification
- Sent notifications history

## Configuration

### Environment Variables (.env)
```env
# Telegram
BOT_TOKEN=your_bot_token
ADMIN_IDS=123456789,987654321

# Marzban API
MARZBAN_URL=https://vpn.dealflow.bond
MARZBAN_ADMIN_USERNAME=admin
MARZBAN_ADMIN_PASSWORD=password

# Database
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/vpn_bot

# Payments
CRYPTO_BOT_TOKEN=cryptobot_token
PLATEGA_SECRET_KEY=platega_secret_key

# VLESS Reality
VLESS_PORT=8444
VLESS_SNI=dl.google.com
VLESS_PUBLIC_KEY=...
VLESS_SHORT_ID=fb8e00
VLESS_FINGERPRINT=chrome
```

### Key Configuration Properties (config.py)
- `settings.admin_ids_list` - List of admin Telegram IDs
- `settings.referral_percentages_list` - [15, 10, 5]
- `settings.notification_intervals_list` - Minutes before expiry
- `settings.marzban_api_url` - Full Marzban API URL

## Key Commands

### Development
```bash
# Install dependencies
pip install -r requirements.txt

# Run bot (local)
python bot.py

# Run webhooks (separate process, port 8080)
python webhooks.py

# Docker
docker-compose up -d --build
docker-compose logs -f bot
docker-compose logs -f webhooks
```

### Bot Commands
- `/start` - Main menu
- `/me` - User profile
- `/buy` - Purchase subscription
- `/trial` - Free trial
- `/referral` - Referral program
- `/help` - Help
- `/admin` - Admin panel (admins only)

## Architecture Patterns

### Database Session Middleware
```python
@dp.update.outer_middleware
async def db_session_middleware(handler, event, data):
    factory = get_session_factory()
    async with factory() as session:
        data['session'] = session
        return await handler(event, data)
```

### Service Pattern (Marzban API)
```python
class MarzbanService:
    def __init__(self):
        self._client = httpx.AsyncClient(timeout=30.0, verify=False)
    
    async def get_token(self) -> str:
        # Token caching with expiration
    
    async def _request(self, method, endpoint, ...):
        # Retry logic (3 attempts)
```

### Payment Processing Flow (webhooks.py)
1. Receive webhook from CryptoBot/Platega
2. Validate signature and payment status
3. Extract user ID from custom_payload or PaymentInvoice
4. Update Transaction status to "paid"
5. Extend subscription in DB
6. **Distribute referral bonuses** (3 levels: 15%, 10%, 5%)
7. Update/create Marzban user
8. Send notifications to user, referrers, and admins

### Notification Scheduler (utils/scheduler.py)
- Runs every 10 minutes
- Checks users with active subscriptions
- Sends notifications based on time remaining
- Tracks sent notifications to avoid duplicates

## Important Implementation Details

### macOS SSL Patch (bot.py:12-16)
```python
# Disables strict SSL certificate verification for local development
if not os.environ.get('PYTHONHTTPSVERIFY', '') and getattr(ssl, '_create_unverified_context', None):
    ssl._create_default_https_context = ssl._create_unverified_context
```

### Database Engine (database/engine.py)
- Defaults to SQLite for local development (`vpn_bot.db`)
- PostgreSQL URL from `DATABASE_URL` env var for production
- Async session factory with `expire_on_commit=False`

### Referral System Logic
```python
# 3-level chain traversal
percentages = [15, 10, 5]  # Level 1, 2, 3
current_referrer_id = user.referrer_id

for level, pct in enumerate(percentages, 1):
    if not current_referrer_id:
        break
    referrer = get_user_by_id(current_referrer_id)
    bonus = amount * (pct / 100)
    referrer.referral_balance += bonus
    current_referrer_id = referrer.referrer_id  # Move up the chain
```

### VLESS Link Generation
```python
vless_link = (
    f"vless://{uuid}@{host}:{port}"
    f"?encryption=none&security=reality&sni={sni}"
    f"&fp={fingerprint}&pbk={public_key}"
    f"&sid={short_id}&type=tcp&headerType=none"
    f"#{username}"
)
```

## Common Operations

### Create User in Marzban
```python
from services.marzban_api import marzban_service

result = await marzban_service.create_user(
    tg_id=user_id,
    username=username,
    expire_days=30,
    data_limit_gb=0.0  # Unlimited for paid
)
```

### Calculate Tariff Price with Discount
```python
from config import calculate_tariff_price

price = await calculate_tariff_price(session, base_price=100, months=3)
# Returns 270 (10% discount for 3 months)
```

### Send Admin Notification
```python
from handlers.admin.notifications import notify_admin_payment

await notify_admin_payment(
    bot=bot,
    user_id=user_id,
    amount_rub=100,
    username="user123",
    method="cryptobot",
    referrers_bonuses=[{'level': 1, 'id': 123, 'bonus': 15}]
)
```

## Testing & Debugging

### Debug Commands
- `/ping` - Bot health check
- `/me` - Current user info

### Logs
- Location: `logs/bot_YYYY-MM-DD.log`, `logs/webhooks_YYYY-MM-DD.log`
- Rotation: Daily at midnight
- Retention: 7 days

### Common Issues
1. **SSL errors on macOS**: SSL patch is already applied in bot.py
2. **User not found in Marzban**: Service returns `None` for 404 (handled)
3. **Payment not processed**: Check webhook logs and signature validation

## Coding Conventions

- **Language**: Russian for all user-facing text, comments, docstrings
- **Typing**: Full type hints for all functions
- **Async**: All I/O operations are async
- **Error Handling**: Try-except with logging for all external calls
- **Logging**: loguru with levels (debug, info, warning, error, critical)
- **Docstrings**: Russian, Google-style with Args/Returns

## Security Notes

- Never commit `.env` file
- Never log secrets (tokens, passwords, API keys)
- Admin commands check `user_id in settings.admin_ids_list`
- Webhook signatures validated for Platega
- Payment IDs stored as unique constraints

## Deployment Checklist

1. Fill all `.env` variables
2. Start PostgreSQL (Docker or local)
3. Run `docker-compose up -d --build`
4. Check logs: `docker-compose logs -f bot`
5. Configure payment webhooks on server:
   - CryptoBot: `https://your-server.com/webhook/crypto`
   - Platega: `https://your-server.com/webhook/platega`
6. Test with `/ping` command

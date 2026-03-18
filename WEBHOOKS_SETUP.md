# Настройка вебхуков для платежных систем

## 📋 Обзор

Для обработки платежей от CryptoBot и Platega необходимо настроить вебхуки. Вебхук — это URL, на который платежная система отправляет уведомления об изменении статуса платежа.

---

## 🔧 Запуск вебхук-сервера

### Локальный запуск (для тестирования)

1. **Запустите вебхук-сервер:**
```bash
# Linux/Mac
./start_webhooks.sh

# Windows
start_webhooks.bat

# Или вручную
python run_webhooks.py
```

2. **Сервер запустится на порту 8080:**
- CryptoBot: `http://localhost:8080/webhook/crypto`
- Platega: `http://localhost:8080/webhook/platega`

### Для тестирования локально используйте ngrok:

```bash
# Установите ngrok
# https://ngrok.com/download

# Запустите туннель
ngrok http 8080
```

Вы получите временный URL вида: `https://xxxx-xxxx.ngrok.io`

---

## 💰 Настройка CryptoBot Webhook

### Шаг 1: Зайдите в @CryptoPay

1. Откройте бота [@CryptoPay](https://t.me/CryptoPay)
2. Перейдите в раздел **Admin** → **Apps**
3. Выберите ваше приложение или создайте новое

### Шаг 2: Укажите webhook URL

В настройках приложения укажите:
```
https://your-domain.com/webhook/crypto
```

Или для тестирования:
```
https://xxxx-xxxx.ngrok.io/webhook/crypto
```

### Шаг 3: Проверка работы

CryptoBot отправляет уведомления при изменении статуса счета:

**Пример payload:**
```json
{
  "invoice_id": 12345,
  "amount": "100.00",
  "currency": "RUB",
  "status": "paid",
  "custom_payload": "user_123456_sub_30d"
}
```

**custom_payload** используется для определения:
- `user_123456` — Telegram ID пользователя
- `sub_30d` — срок подписки (30 дней)

---

## 💳 Настройка Platega Webhook

### Шаг 1: Зайдите в панель Platega

Откройте [панель Platega](https://platega.io/) и авторизуйтесь.

### Шаг 2: Настройте webhook

В разделе **Настройки** → **Webhooks** укажите:
```
https://your-domain.com/webhook/platega
```

### Шаг 3: Укажите секретный ключ

В `.env` файле укажите:
```env
PLATEGA_SECRET_KEY=ваш_секретный_ключ
```

### Шаг 4: Проверка подписи

Platega отправляет подпись в заголовке `X-Platega-Signature`.

**Пример payload:**
```json
{
  "order_id": "platega_123456_abc123",
  "amount": 100.0,
  "currency": "RUB",
  "status": "success",
  "custom_id": "123456789",
  "payment_id": "plg_12345",
  "signature": "abc123..."
}
```

**custom_id** содержит Telegram ID пользователя.

---

## 🌐 Размещение на сервере

### Вариант 1: Запуск через systemd

Создайте файл `/etc/systemd/system/nemo-webhooks.service`:

```ini
[Unit]
Description=Nemo VPN Webhooks Server
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/path/to/vpn_bot
Environment="PATH=/path/to/venv/bin"
ExecStart=/path/to/venv/bin/python run_webhooks.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Запустите:
```bash
sudo systemctl daemon-reload
sudo systemctl enable nemo-webhooks
sudo systemctl start nemo-webhooks
```

### Вариант 2: Запуск через supervisor

Создайте файл `/etc/supervisor/conf.d/nemo-webhooks.conf`:

```ini
[program:nemo-webhooks]
command=/path/to/venv/bin/python run_webhooks.py
directory=/path/to/vpn_bot
user=www-data
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/nemo-webhooks.log
```

Запустите:
```bash
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start nemo-webhooks
```

### Вариант 3: Через nginx + gunicorn

**Установите gunicorn:**
```bash
pip install gunicorn
```

**Запустите:**
```bash
gunicorn -w 4 -b 0.0.0.0:8080 webhook_crypto:create_app
```

**Настройте nginx:**
```nginx
server {
    listen 80;
    server_name vpn.yourdomain.com;

    location /webhook/crypto {
        proxy_pass http://127.0.0.1:8080/webhook/crypto;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    location /webhook/platega {
        proxy_pass http://127.0.0.1:8081/webhook/platega;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

---

## 🔍 Проверка работы

### Логи вебхук-сервера

```bash
# Просмотр логов
tail -f logs/webhooks_*.log

# Или через journalctl (для systemd)
sudo journalctl -u nemo-webhooks -f
```

### Тестирование через curl

**CryptoBot:**
```bash
curl -X POST http://localhost:8080/webhook/crypto \
  -H "Content-Type: application/json" \
  -d '{
    "invoice_id": 99999,
    "amount": "100.00",
    "currency": "RUB",
    "status": "paid",
    "custom_payload": "user_123456_sub_30d"
  }'
```

**Platega:**
```bash
curl -X POST http://localhost:8080/webhook/platega \
  -H "Content-Type: application/json" \
  -H "X-Platega-Signature: test" \
  -d '{
    "order_id": "test_123",
    "amount": 100.0,
    "currency": "RUB",
    "status": "success",
    "custom_id": "123456789",
    "signature": "test"
  }'
```

### Health check

```bash
curl http://localhost:8080/health
```

Должен вернуть: `{"status": "ok"}`

---

## 🚨 Решение проблем

### Вебхук не работает

1. **Проверьте, запущен ли сервер:**
```bash
ps aux | grep run_webhooks
```

2. **Проверьте логи:**
```bash
tail -f logs/webhooks_*.log
```

3. **Проверьте доступность порта:**
```bash
netstat -tlnp | grep 8080
```

### Ошибки подписи

- Убедитесь, что `PLATEGA_SECRET_KEY` указан верно
- Проверьте формат подписи в документации Platega

### Платежи не подтверждаются

1. Проверьте логи на наличие ошибок
2. Убедитесь, что `custom_payload` или `custom_id` содержат правильный Telegram ID
3. Проверьте подключение к базе данных

---

## 📞 Поддержка

При возникновении проблем:

1. Проверьте логи вебхук-сервера
2. Проверьте настройки в панелях CryptoBot и Platega
3. Убедитесь, что URL вебхука доступен извне

**Nemo VPN Team**

# Инструкция по развёртыванию Nemo VPN Bot

## 📋 Предварительные требования

1. **Docker** и **Docker Compose** установлены на сервере
2. **Marzban** панель уже работает по адресу `https://vpn.dealflow.bond`
3. Токен бота получен от [@BotFather](https://t.me/BotFather)
4. Аккаунты в платежных системах (CryptoBot, Platega)

---

## 🚀 Шаг 1: Подготовка файлов

### 1.1 Скопируйте файлы проекта
```bash
# Перейдите в директорию проекта
cd /path/to/api_bot/vpn_bot
```

### 1.2 Настройте переменные окружения

Откройте файл `.env` и заполните обязательные значения:

```bash
nano .env
```

**Обязательные параметры:**

```env
# Telegram Bot
BOT_TOKEN=8699535910:AAEJWQKEiArPCyppEilTJUjj7B1ov9SIdr4
ADMIN_IDS=ваш_TG_ID

# Marzban API
MARZBAN_URL=https://vpn.dealflow.bond
MARZBAN_ADMIN_USERNAME=ваш_логин_в_marzban
MARZBAN_ADMIN_PASSWORD=ваш_пароль_в_marzban

# Database
POSTGRES_PASSWORD=придумайте_надёжный_пароль

# Payment Systems
CRYPTO_BOT_TOKEN=токен_от_CryptoPay
PLATEGA_SECRET_KEY=ключ_от_Platega
```

**Как получить ADMIN_ID:**
1. Напишите боту [@userinfobot](https://t.me/userinfobot)
2. Скопируйте ваш ID (число)
3. Вставьте в `ADMIN_IDS`

---

## 🐳 Шаг 2: Запуск через Docker Compose

### 2.1 Запустите контейнеры
```bash
docker-compose up -d
```

### 2.2 Проверьте статус
```bash
docker-compose ps
```

Должны быть запущены:
- `nemo_vpn_bot` — сам бот
- `nemo_vpn_db` — база данных PostgreSQL
- `nemo_vpn_redis` — Redis (опционально)

### 2.3 Посмотрите логи
```bash
# Логи бота
docker-compose logs -f bot

# Логи базы данных
docker-compose logs -f db
```

---

## ⚙️ Шаг 3: Настройка вебхука Platega

Для обработки платежей от Platega нужен отдельный веб-сервер.

### 3.1 Запустите webhook сервер

```bash
# В отдельном терминале
docker-compose exec bot python webhook_platega.py
```

### 3.2 Настройте переадресацию портов

В `docker-compose.yml` добавьте для сервиса `bot`:

```yaml
ports:
  - "8080:8080"
```

Перезапустите:
```bash
docker-compose down
docker-compose up -d
```

### 3.3 Укажите URL вебхука в Platega

В панели Platega укажите:
```
https://ваш-домен.com:8080/webhook/platega
```

---

## 🔧 Шаг 4: Проверка работоспособности

### 4.1 Запустите бота в Telegram

1. Найдите вашего бота по username
2. Нажмите `/start`
3. Должно появиться главное меню

### 4.2 Проверьте админ-панель

1. Нажмите `/admin`
2. Должна открыться админ-панель
3. Проверьте статистику

### 4.3 Проверьте базу данных

```bash
docker-compose exec db psql -U postgres -d vpn_bot -c "SELECT COUNT(*) FROM users;"
```

---

## 🔒 Шаг 5: Безопасность

### 5.1 Настройте firewall

```bash
# Разрешите только необходимые порты
ufw allow 22/tcp        # SSH
ufw allow 443/tcp       # HTTPS (если нужно)
ufw allow 8080/tcp      # Webhook Platega
ufw enable
```

### 5.2 Обновите пароли

- Смените пароль PostgreSQL на надёжный
- Используйте сложные пароли для Marzban
- Регулярно обновляйте токены

### 5.3 Настройте SSL для вебхука

Для продакшена используйте nginx + Let's Encrypt:

```nginx
server {
    listen 80;
    server_name vpn.yourdomain.com;

    location /webhook/platega {
        proxy_pass http://localhost:8080/webhook/platega;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

## 📊 Шаг 6: Мониторинг

### 6.1 Просмотр логов

```bash
# Последние 100 строк
docker-compose logs --tail=100 bot

# Логи в реальном времени
docker-compose logs -f bot

# Логи за сегодня
docker-compose logs --since today bot
```

### 6.2 Проверка статистики

```bash
# Количество пользователей
docker-compose exec db psql -U postgres -d vpn_bot -c "SELECT COUNT(*) FROM users;"

# Активные подписки
docker-compose exec db psql -U postgres -d vpn_bot -c "SELECT COUNT(*) FROM users WHERE expire_date > NOW();"

# Общая выручка
docker-compose exec db psql -U postgres -d vpn_bot -c "SELECT SUM(amount) FROM transactions WHERE status='paid';"
```

### 6.3 Автоматический рестарт

Docker Compose уже настроен на `restart: unless-stopped`

Проверьте:
```bash
docker-compose ps
```

---

## 🛠 Решение проблем

### Бот не запускается

```bash
# Проверьте логи
docker-compose logs bot

# Перезапустите
docker-compose restart bot

# Пересоздайте контейнер
docker-compose down
docker-compose up -d
```

### Ошибка подключения к БД

```bash
# Проверьте, запущена ли БД
docker-compose ps db

# Проверьте логи БД
docker-compose logs db

# Дождитесь готовности БД
docker-compose logs -f db | grep "database system is ready"
```

### Ошибки Marzban API

1. Проверьте логин/пароль в `.env`
2. Убедитесь, что Marzban доступен:
```bash
curl https://vpn.dealflow.bond/api
```

### Платежи не работают

1. Проверьте токены в `.env`
2. Проверьте логи вебхука
3. Убедитесь, что порт 8080 открыт

---

## 📝 Обновление бота

```bash
# Остановите бота
docker-compose down

# Обновите код (git pull или копирование файлов)

# Пересоберите образ
docker-compose build --no-cache

# Запустите заново
docker-compose up -d
```

---

## 🧹 Очистка и удаление

### Удалить всё кроме томов БД
```bash
docker-compose down
```

### Удалить полностью всё
```bash
docker-compose down -v
rm -rf .env logs/
```

---

## 📞 Поддержка

При возникновении проблем:

1. Проверьте логи: `docker-compose logs -f bot`
2. Проверьте `.env` на корректность
3. Убедитесь, что все контейнеры запущены
4. Обратитесь в техподдержку

---

**Nemo VPN Bot** готов к работе! 🎉

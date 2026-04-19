import json
import httpx
import uuid
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta
from loguru import logger

from database.models import User, PaymentInvoice, Transaction
from keyboards.inline import (
    get_buy_keyboard,
    get_payment_keyboard,
    get_subscription_duration_keyboard,
    get_tier_selection_keyboard,
    get_main_menu_keyboard,
    get_traffic_buy_keyboard,
    get_gift_tier_keyboard,
    get_gift_duration_keyboard,
)
from services.marzban_api import marzban_service
from services.payment_crypto import crypto_bot_service
from handlers.admin.notifications import (
    notify_user_purchase,
    notify_admin_payment,
    notify_referrer_payment
)
from config import settings, get_db_setting, calculate_tariff_price
from utils.states import BuySubscription

router = Router()

# =====================================================================
# TRAFFIC BUY И GIFT — НОВЫЕ CALLBACKS
# =====================================================================

@router.callback_query(F.data == "traffic_buy")
async def traffic_buy_callback(callback: types.CallbackQuery, session: AsyncSession):
    """Показать клавиатуру с пакетами ГБ для докупки трафика."""
    await callback.answer()
    
    # Проверяем что у пользователя есть подписка
    result = await session.execute(select(User).where(User.user_id == callback.from_user.id))
    user = result.scalar_one_or_none()
    
    if not user or not user.marzban_username:
        await callback.message.edit_text(
            "❌ <b>Докупка трафика доступна только с активной подпиской.</b>\n\n"
            "Сначала оформите подписку!",
            reply_markup=get_back_keyboard("buy"),
            parse_mode="HTML"
        )
        return
    
    await callback.message.edit_text(
        "📦 <b>Докупка трафика</b>\n\n"
        "Выберите пакет дополнительного трафика.\n"
        "Трафик будет добавлен к вашему текущему лимиту.",
        reply_markup=get_traffic_buy_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("traffic_"))
async def traffic_select_package(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    """Обработка выбора пакета трафика."""
    await callback.answer()
    
    # Парсим размер пакета
    gb = int(callback.data.replace("traffic_", ""))
    
    TRAFFIC_PRICES = {50: 50, 100: 90, 300: 250, 500: 400}
    price = TRAFFIC_PRICES.get(gb)
    
    if not price:
        await callback.answer("Неверный пакет", show_alert=True)
        return
    
    await state.update_data(traffic_gb=gb, traffic_price=price)
    
    text = (
        f"📦 <b>Докупка трафика</b>\n\n"
        f"Пакет: <b>{gb} ГБ</b>\n"
        f"Цена: <b>{price} ₽</b>\n\n"
        f"💳 Выберите способ оплаты:"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=get_buy_keyboard(),
        parse_mode="HTML"
    )
    
    await state.set_state("traffic_select_payment")


@router.callback_query(F.data == "gift_start")
async def gift_start_callback(callback: types.CallbackQuery, session: AsyncSession):
    """Показать выбор тарифа для подарка."""
    await callback.answer()
    
    await callback.message.edit_text(
        "🎁 <b>Подарить VPN</b>\n\n"
        "Выберите тариф для друга.\n"
        "После оплаты вы получите подарочную ссылку, которую можно отправить любому человеку.",
        reply_markup=get_gift_tier_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("gift_") and F.data not in ("gift_start",))
async def gift_select_tier(callback: types.CallbackQuery, state: FSMContext):
    """Выбор тарифа для подарка."""
    await callback.answer()
    
    tier = callback.data.replace("gift_", "")
    if tier not in ("standard", "premium"):
        return
    
    await state.update_data(gift_tier=tier)
    
    tier_name = "🚀 VIP (Обход белых списков)" if tier == "premium" else "🛡 Обычный VPN"
    
    await callback.message.edit_text(
        f"🎁 <b>Подарить VPN</b>\n\n"
        f"Тариф: <b>{tier_name}</b>\n\n"
        f"Выберите срок подарочной подписки:",
        reply_markup=get_gift_duration_keyboard(tier),
        parse_mode="HTML"
    )
    
    await state.set_state("gift_select_duration")


@router.callback_query(F.data.startswith("gift_dur_"))
async def gift_select_duration(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора срока подарка."""
    await callback.answer()
    
    days = int(callback.data.replace("gift_dur_", ""))
    data = await state.get_data()
    tier = data.get("gift_tier", "premium")
    
    GIFT_PRICES = {
        ("premium", 30): 300, ("premium", 90): 800,
        ("premium", 180): 1400, ("premium", 365): 2500,
        ("standard", 30): 150, ("standard", 90): 400,
        ("standard", 180): 700, ("standard", 365): 1200,
    }
    price = GIFT_PRICES.get((tier, days), 300)
    
    await state.update_data(gift_days=days, gift_price=price)
    
    tier_name = "🚀 VIP" if tier == "premium" else "🛡 Обычный"
    
    text = (
        f"🎁 <b>Подарить VPN</b>\n\n"
        f"Тариф: <b>{tier_name}</b>\n"
        f"Срок: <b>{days} дней</b>\n"
        f"Цена: <b>{price} ₽</b>\n\n"
        f"💳 Выберите способ оплаты:"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=get_buy_keyboard(),
        parse_mode="HTML"
    )
    
    await state.set_state("gift_select_payment")


# =====================================================================
# ОСНОВНОЙ ПОТОК ПОКУПКИ ПОДПИСКИ (без изменений)
# =====================================================================

async def process_manual_payment(bot, session: AsyncSession, payment_invoice: PaymentInvoice):
    """Ручная обработка выдачи подписки, если вебхук потерялся по пути к серверу."""
    try:
        days = 30
        tier = "standard"
        
        if payment_invoice.payload:
            try:
                payload_data = json.loads(payment_invoice.payload)
                days = payload_data.get("days", 30)
                tier = payload_data.get("tier", "standard")
            except: pass

        result = await session.execute(select(User).where(User.user_id == payment_invoice.user_id))
        user = result.scalar_one_or_none()
        if not user: return

        payment_invoice.status = "paid"
        
        transaction = Transaction(
            user_id=user.user_id,
            amount=payment_invoice.amount,
            currency=payment_invoice.currency,
            payment_method=payment_invoice.payment_method,
            status="paid",
            payment_id=payment_invoice.invoice_id,
            description=f"Оплата подписки на {days} дней ({'VIP' if tier == 'premium' else 'Обычный'})",
        )
        session.add(transaction)

        now = datetime.utcnow()
        if user.expire_date and user.expire_date > now:
            user.expire_date = user.expire_date + timedelta(days=days)
        else:
            user.expire_date = now + timedelta(days=days)

        user.tier = tier

        marzban_account_exists = False
        if user.marzban_username:
            try:
                marzban_data = await marzban_service.get_user(user.marzban_username)
                if marzban_data:
                    marzban_account_exists = True
            except: pass

        if marzban_account_exists:
            await marzban_service.update_user_expiry(user.marzban_username, days, tier=tier)
        else:
            new_acc = await marzban_service.create_user(
                tg_id=user.user_id,
                username=user.username,
                expire_days=days,
                data_limit_gb=0.0,
                tier=tier
            )
            user.marzban_username = new_acc.get('username')

        referrers_bonuses = []
        percentages = settings.referral_percentages_list
        current_referrer_id = user.referrer_id

        for level, pct in enumerate(percentages, 1):
            if not current_referrer_id: break
            ref_res = await session.execute(select(User).where(User.user_id == current_referrer_id))
            referrer = ref_res.scalar_one_or_none()
            if not referrer: break
            
            bonus = payment_invoice.amount * (pct / 100)
            referrer.referral_balance += bonus
            referrers_bonuses.append({
                'level': level, 'id': referrer.user_id, 'username': referrer.username, 'bonus': bonus
            })
            
            await notify_referrer_payment(bot, referrer.user_id, user.user_id, bonus, level, user.username)
            current_referrer_id = referrer.referrer_id

        await session.commit()

        await notify_user_purchase(
            bot=bot,
            user_id=user.user_id,
            amount_rub=payment_invoice.amount,
            duration_days=days,
            is_extension=marzban_account_exists,
            marzban_username=user.marzban_username
        )

        await notify_admin_payment(bot, user.user_id, payment_invoice.amount, user.username, payment_invoice.payment_method, referrers_bonuses)
        logger.info(f"Ручная обработка платежа завершена для {user.user_id}")

    except Exception as e:
        logger.error(f"Ошибка ручной выдачи: {e}")
        await session.rollback()


@router.callback_query(F.data == "buy")
@router.message(Command("buy"))
@router.message(F.text.startswith("Купить подписку"))
async def show_buy(callback_or_message: types.CallbackQuery | types.Message, state: FSMContext, session: AsyncSession):
    """Показать меню выбора тарифа."""
    if isinstance(callback_or_message, types.CallbackQuery):
        callback = callback_or_message
        message = callback.message
        user_id = callback.from_user.id
        await callback.answer()
    else:
        message = callback_or_message
        callback = None
        user_id = message.from_user.id

    result = await session.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        await message.answer("❌ Пользователь не найден. Нажмите /start")
        return

    has_subscription = user.expire_date and user.expire_date > datetime.utcnow()

    text = "🛍 <b>Магазин подписок Nemo VPN</b>\n\n"
    if has_subscription:
        days_left = (user.expire_date - datetime.utcnow()).days
        text += f"⏳ <b>Ваша подписка активна ещё {max(0, days_left)} дн.</b>\n"
        text += "Новая подписка продлит текущую.\n\n"

    text += (
        "🛡 <b>Выберите тип VPN-подписки:</b>\n\n"
        "<b>Обычный VPN:</b>\n"
        "Стандартный сервер для повседневных задач.\n\n"
        "<b>🚀 Обход белых списков (VIP):</b>\n"
        "Передовая связка на базе ядра Xray (XTLS-Reality + Vision). "
        "Маскирует трафик под обычные запросы к разрешенным сайтам (Яндекс). "
        "Идеально обходит ТСПУ и глубокий анализ пакетов (DPI) от Роскомнадзора."
    )

    # Передаём флаг has_subscription чтобы показать кнопку "Докупить трафик"
    keyboard = get_tier_selection_keyboard(has_subscription=has_subscription)

    try:
        if message.video or message.animation or message.photo:
            await message.edit_caption(caption=text, reply_markup=keyboard, parse_mode="HTML")
        else:
            if not callback:
                await message.answer_animation(
                    animation="CgACAgIAAxkBAAIE7Wm804DyYQvViOUC--9rsXLvJ8ZtAALanwACxDgSamsbGW6emV70gQ",
                    caption=text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            else:
                await message.edit_text(text=text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        logger.warning(f"Не удалось отправить/отредактировать GIF, отправляем текстом. Ошибка: {e}")
        if callback:
            await message.edit_text(text=text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await message.answer(text=text, reply_markup=keyboard, parse_mode="HTML")
            
    await state.set_state(BuySubscription.selecting_tier)


@router.callback_query(F.data.startswith("tier_"))
async def select_tier(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    """Выбор тарифа и отображение сроков (или Web App для VIP)."""
    tier = callback.data.replace("tier_", "")
    await state.update_data(tier=tier)
    
    if tier == "premium":
        text = (
            "🚀 <b>Обход белых списков (VIP)</b>\n\n"
            "Для оформления данного тарифа, выбора выгодного лимита гигабайт и количества устройств, "
            "пожалуйста, перейдите в наше удобное Mini App 👇"
        )
        
        webapp_url = "https://nemo-vpn-webapp.vercel.app/" 
        
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="📱 Открыть Mini App", web_app=types.WebAppInfo(url=webapp_url))],
            [types.InlineKeyboardButton(text="« Назад", callback_data="buy")]
        ])
        
        try:
            if callback.message.video or callback.message.animation or callback.message.photo:
                await callback.message.edit_caption(caption=text, reply_markup=keyboard, parse_mode="HTML")
            else:
                await callback.message.edit_text(text=text, reply_markup=keyboard, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Ошибка редактирования меню VIP Mini App (пробуем новое сообщение): {e}")
            await callback.message.answer(text=text, reply_markup=keyboard, parse_mode="HTML")
            
        await callback.answer()
        return

    if tier == "premium":
        base_price_str = await get_db_setting(session, "premium_subscription_price", str(settings.PREMIUM_PRICE_RUB))
        price_test = 100
    else:
        base_price_str = await get_db_setting(session, "subscription_price", str(settings.SUBSCRIPTION_PRICE_RUB))
        price_test = 10
    
    base_price = float(base_price_str)
    
    price_1m = await calculate_tariff_price(session, base_price, 1)
    price_3m = await calculate_tariff_price(session, base_price, 3)
    price_6m = await calculate_tariff_price(session, base_price, 6)
    price_12m = await calculate_tariff_price(session, base_price, 12)

    keyboard = get_subscription_duration_keyboard(
        tier=tier,
        price_1m=price_1m,
        price_3m=price_3m,
        price_6m=price_6m,
        price_12m=price_12m,
        price_test=price_test
    )

    text = "⏱ <b>Выберите срок подписки:</b>"

    try:
        if callback.message.video or callback.message.animation or callback.message.photo:
            await callback.message.edit_caption(caption=text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await callback.message.edit_text(text=text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ошибка редактирования меню сроков: {e}")

    await state.set_state(BuySubscription.selecting_duration)
    await callback.answer()


@router.callback_query(F.data.startswith("duration_"))
async def select_duration(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    """Выбор срока подписки."""
    duration = callback.data
    data = await state.get_data()
    tier = data.get("tier", "standard")

    if tier == "premium":
        base_price = float(await get_db_setting(session, "premium_subscription_price", str(settings.PREMIUM_PRICE_RUB)))
    else:
        base_price = float(await get_db_setting(session, "subscription_price", str(settings.SUBSCRIPTION_PRICE_RUB)))

    if duration == "duration_test3d":
        days = 3
        price = 100 if tier == "premium" else 10
    elif duration == "duration_1month":
        days = 30
        price = await calculate_tariff_price(session, base_price, 1)
    elif duration == "duration_3month":
        days = 90
        price = await calculate_tariff_price(session, base_price, 3)
    elif duration == "duration_6month":
        days = 180
        price = await calculate_tariff_price(session, base_price, 6)
    elif duration == "duration_12month":
        days = 365
        price = await calculate_tariff_price(session, base_price, 12)
    else:
        await callback.answer("Неверный тариф", show_alert=True)
        return

    await state.update_data(days=days, price=int(price))

    tier_name = "🚀 Обход белых списков (VIP)" if tier == "premium" else "🛡 Обычный VPN"
    
    text = (
        f"✅ <b>Выбран тариф:</b> {tier_name}\n\n"
        f"⏳ Срок: <b>{days} дней</b>\n"
        f"💵 Цена: <b>{int(price)} ₽</b>\n\n"
        "💳 Выберите способ оплаты:"
    )
    
    keyboard = get_buy_keyboard()

    try:
        if callback.message.video or callback.message.animation or callback.message.photo:
            await callback.message.edit_caption(caption=text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await callback.message.edit_text(text=text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ошибка редактирования меню покупки: {e}")

    await state.set_state(BuySubscription.selecting_payment_method)
    await callback.answer()


@router.callback_query(F.data == "pay_crypto")
async def pay_crypto(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    """Оплата через CryptoBot (USDT)."""
    user_id = callback.from_user.id
    data = await state.get_data()
    
    # Проверяем контекст: traffic, gift или обычная подписка
    fsm_state = await state.get_state()
    
    if fsm_state == "traffic_select_payment":
        # Оплата трафика
        gb = data.get("traffic_gb")
        price_rub = data.get("traffic_price")
        
        await callback.answer("⏳ Создание счета...")
        try:
            price_usdt = round(price_rub / settings.USDT_TO_RUB_RATE, 2)
            bot_info = await callback.bot.get_me()
            bot_username = bot_info.username

            payment_invoice = PaymentInvoice(
                user_id=user_id,
                invoice_id=f"temp_{user_id}_{int(datetime.utcnow().timestamp())}",
                amount=price_rub,
                currency="RUB",
                payment_method="cryptobot",
                status="pending",
                payload=json.dumps({"type": "traffic", "gb": gb, "price": price_rub}),
                expires_at=datetime.utcnow() + timedelta(hours=1)
            )
            session.add(payment_invoice)
            await session.flush()
            order_id = payment_invoice.id

            result = await crypto_bot_service.create_invoice(
                amount_usdt=price_usdt,
                order_id=order_id,
                description=f"Nemo VPN: +{gb} ГБ трафика",
                paid_btn_name="Вернуться в бот",
                paid_btn_url=f"https://t.me/{bot_username}"
            )

            if not result:
                raise Exception("Не удалось создать счет в CryptoBot")

            invoice_url, real_invoice_id = result
            payment_invoice.invoice_id = str(real_invoice_id)
            await session.commit()

            text = (
                f"📦 <b>Оплата трафика криптовалютой</b>\n\n"
                f"Пакет: <b>{gb} ГБ</b>\n"
                f"Сумма: <b>{price_usdt} USDT</b>\n"
                f"Заказ: <code>#{order_id}</code>"
            )
            keyboard = get_payment_keyboard(invoice_url, str(real_invoice_id))

            try:
                await callback.message.edit_text(text=text, reply_markup=keyboard, parse_mode="HTML")
            except Exception:
                pass

            await state.set_state(BuySubscription.waiting_for_payment)
            logger.info(f"Создан счет CryptoBot #{order_id} для {user_id}: +{gb} ГБ ({price_usdt} USDT)")
        except Exception as e:
            logger.error(f"Ошибка создания счета CryptoBot (traffic): {e}")
            await callback.message.answer("❌ Ошибка при создании счета. Попробуйте позже.")
        await callback.answer()
        return
    
    elif fsm_state == "gift_select_payment":
        # Оплата подарка
        tier = data.get("gift_tier", "premium")
        days = data.get("gift_days", 30)
        price_rub = data.get("gift_price", 300)
        
        await callback.answer("⏳ Создание счета...")
        try:
            price_usdt = round(price_rub / settings.USDT_TO_RUB_RATE, 2)
            bot_info = await callback.bot.get_me()
            bot_username = bot_info.username

            payment_invoice = PaymentInvoice(
                user_id=user_id,
                invoice_id=f"temp_{user_id}_{int(datetime.utcnow().timestamp())}",
                amount=price_rub,
                currency="RUB",
                payment_method="cryptobot",
                status="pending",
                payload=json.dumps({"type": "gift", "tier": tier, "days": days}),
                expires_at=datetime.utcnow() + timedelta(hours=1)
            )
            session.add(payment_invoice)
            await session.flush()
            order_id = payment_invoice.id

            result = await crypto_bot_service.create_invoice(
                amount_usdt=price_usdt,
                order_id=order_id,
                description=f"Nemo VPN: подарок ({tier}, {days}дн)",
                paid_btn_name="Вернуться в бот",
                paid_btn_url=f"https://t.me/{bot_username}"
            )

            if not result:
                raise Exception("Не удалось создать счет в CryptoBot")

            invoice_url, real_invoice_id = result
            payment_invoice.invoice_id = str(real_invoice_id)
            await session.commit()

            tier_name = "VIP" if tier == "premium" else "Обычный"
            text = (
                f"🎁 <b>Оплата подарка криптовалютой</b>\n\n"
                f"Тариф: <b>{tier_name}</b>\n"
                f"Срок: <b>{days} дней</b>\n"
                f"Сумма: <b>{price_usdt} USDT</b>\n"
                f"Заказ: <code>#{order_id}</code>"
            )
            keyboard = get_payment_keyboard(invoice_url, str(real_invoice_id))

            try:
                await callback.message.edit_text(text=text, reply_markup=keyboard, parse_mode="HTML")
            except Exception:
                pass

            await state.set_state(BuySubscription.waiting_for_payment)
            logger.info(f"Создан счет CryptoBot #{order_id} (подарок) для {user_id}: {price_usdt} USDT")
        except Exception as e:
            logger.error(f"Ошибка создания счета CryptoBot (gift): {e}")
            await callback.message.answer("❌ Ошибка при создании счета. Попробуйте позже.")
        await callback.answer()
        return

    # Стандартная оплата подписки
    price_rub = data.get("price", settings.SUBSCRIPTION_PRICE_RUB)
    days = data.get("days", settings.SUBSCRIPTION_EXPIRE_DAYS)
    tier = data.get("tier", "standard")
    
    await callback.answer("⏳ Создание счета...")
    try:
        price_usdt = round(price_rub / settings.USDT_TO_RUB_RATE, 2)
        
        bot_info = await callback.bot.get_me()
        bot_username = bot_info.username

        payment_invoice = PaymentInvoice(
            user_id=user_id,
            invoice_id=f"temp_{user_id}_{int(datetime.utcnow().timestamp())}",
            amount=price_rub,
            currency="RUB",
            payment_method="cryptobot",
            status="pending",
            payload=f'{{"days": {days}, "amount_usdt": {price_usdt}, "tier": "{tier}"}}',
            expires_at=datetime.utcnow() + timedelta(hours=1)
        )
        session.add(payment_invoice)
        await session.flush()
        
        order_id = payment_invoice.id

        tier_name = "VIP" if tier == "premium" else "Обычный"
        result = await crypto_bot_service.create_invoice(
            amount_usdt=price_usdt,
            order_id=order_id,
            description=f"Nemo VPN подписка на {days} дней ({tier_name})",
            paid_btn_name="Вернуться в бот",
            paid_btn_url=f"https://t.me/{bot_username}"
        )

        if not result:
            raise Exception("Не удалось создать счет в CryptoBot")

        invoice_url, real_invoice_id = result
        payment_invoice.invoice_id = str(real_invoice_id)
        await session.commit()

        text = (
            "💎 <b>Оплата криптовалютой</b>\n\n"
            f"Сумма: <b>{price_usdt} USDT</b>\n"
            f"Заказ: <code>#{order_id}</code>\n\n"
            "<i>Вы можете оплатить через USDT (TRC20, TON, BEP20) или Toncoin.</i>"
        )
        keyboard = get_payment_keyboard(invoice_url, str(real_invoice_id))

        try:
            if callback.message.video or callback.message.animation or callback.message.photo:
                await callback.message.edit_caption(caption=text, reply_markup=keyboard, parse_mode="HTML")
            else:
                await callback.message.edit_text(text=text, reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            pass

        await state.update_data(order_id=str(order_id))
        await state.set_state(BuySubscription.waiting_for_payment)
        
        logger.info(f"Создан счет CryptoBot #{order_id} (ID: {real_invoice_id}) для {user_id}: {price_usdt} USDT (Тариф: {tier})")

    except Exception as e:
        logger.error(f"Ошибка создания счета CryptoBot: {e}")
        await callback.message.answer(
            "❌ Произошла ошибка при создании счета.\n\n"
            "Пожалуйста, попробуйте позже или выберите другой способ оплаты."
        )
    await callback.answer()


@router.callback_query(F.data == "pay_card")
async def pay_card(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    """Оплата банковской картой через Platega."""
    user_id = callback.from_user.id
    data = await state.get_data()
    
    # Проверяем контекст: traffic, gift или обычная подписка
    fsm_state = await state.get_state()
    
    if fsm_state == "traffic_select_payment":
        gb = data.get("traffic_gb")
        price = data.get("traffic_price")
        
        await callback.answer("⏳ Создание счета...")
        try:
            order_id = f"platega_{user_id}_{uuid.uuid4().hex[:8]}"
            from services.payment_platega import create_invoice
            
            payment_url = await create_invoice(
                amount_rub=int(price),
                order_id=order_id,
                user_id=user_id,
                description=f"Nemo VPN: +{gb} ГБ трафика"
            )

            if not payment_url:
                raise Exception("Не удалось создать счет в Platega")

            payment_invoice = PaymentInvoice(
                user_id=user_id,
                invoice_id=order_id,
                amount=price,
                currency="RUB",
                payment_method="platega",
                status="pending",
                payload=json.dumps({"type": "traffic", "gb": gb, "price": price}),
                expires_at=datetime.utcnow() + timedelta(hours=1)
            )
            session.add(payment_invoice)
            await session.commit()

            text = (
                f"💳 <b>Оплата трафика (Банковская карта)</b>\n\n"
                f"Пакет: <b>{gb} ГБ</b>\n"
                f"Сумма: <b>{price} ₽</b>\n\n"
                f"ID заказа: <code>{order_id}</code>"
            )
            keyboard = get_payment_keyboard(payment_url, order_id)

            try:
                await callback.message.edit_text(text=text, reply_markup=keyboard, parse_mode="HTML")
            except Exception:
                pass

            await state.update_data(invoice_id=order_id)
            await state.set_state(BuySubscription.waiting_for_payment)
            logger.info(f"Создан счет Platega {order_id} для {user_id} (+{gb} ГБ)")
        except Exception as e:
            logger.error(f"Ошибка создания счета Platega (traffic): {e}")
            await callback.message.answer("❌ Ошибка при создании счета. Попробуйте позже.")
        await callback.answer()
        return
    
    elif fsm_state == "gift_select_payment":
        tier = data.get("gift_tier", "premium")
        days = data.get("gift_days", 30)
        price = data.get("gift_price", 300)
        
        await callback.answer("⏳ Создание счета...")
        try:
            order_id = f"platega_{user_id}_{uuid.uuid4().hex[:8]}"
            from services.payment_platega import create_invoice
            
            payment_url = await create_invoice(
                amount_rub=int(price),
                order_id=order_id,
                user_id=user_id,
                description=f"Nemo VPN: подарок ({tier}, {days}дн)"
            )

            if not payment_url:
                raise Exception("Не удалось создать счет в Platega")

            payment_invoice = PaymentInvoice(
                user_id=user_id,
                invoice_id=order_id,
                amount=price,
                currency="RUB",
                payment_method="platega",
                status="pending",
                payload=json.dumps({"type": "gift", "tier": tier, "days": days}),
                expires_at=datetime.utcnow() + timedelta(hours=1)
            )
            session.add(payment_invoice)
            await session.commit()

            text = (
                f"💳 <b>Оплата подарка (Банковская карта)</b>\n\n"
                f"Тариф: <b>{'VIP' if tier == 'premium' else 'Обычный'}</b>\n"
                f"Срок: <b>{days} дней</b>\n"
                f"Сумма: <b>{price} ₽</b>\n\n"
                f"ID заказа: <code>{order_id}</code>"
            )
            keyboard = get_payment_keyboard(payment_url, order_id)

            try:
                await callback.message.edit_text(text=text, reply_markup=keyboard, parse_mode="HTML")
            except Exception:
                pass

            await state.update_data(invoice_id=order_id)
            await state.set_state(BuySubscription.waiting_for_payment)
            logger.info(f"Создан счет Platega {order_id} для {user_id} (подарок)")
        except Exception as e:
            logger.error(f"Ошибка создания счета Platega (gift): {e}")
            await callback.message.answer("❌ Ошибка при создании счета. Попробуйте позже.")
        await callback.answer()
        return

    # Стандартная оплата подписки
    price = data.get("price", settings.SUBSCRIPTION_PRICE_RUB)
    days = data.get("days", settings.SUBSCRIPTION_EXPIRE_DAYS)
    tier = data.get("tier", "standard")
    
    await callback.answer("⏳ Создание счета...")
    try:
        order_id = f"platega_{user_id}_{uuid.uuid4().hex[:8]}"
        from services.payment_platega import create_invoice
        
        tier_name = "VIP" if tier == "premium" else "Обычный"
        payment_url = await create_invoice(
            amount_rub=int(price),
            order_id=order_id,
            user_id=user_id,
            description=f"Nemo VPN подписка на {days} дней ({tier_name})"
        )

        if not payment_url:
            raise Exception("Не удалось создать счет в Platega")

        payment_invoice = PaymentInvoice(
            user_id=user_id,
            invoice_id=order_id,
            amount=price,
            currency="RUB",
            payment_method="platega",
            status="pending",
            payload=f'{{"days": {days}, "tier": "{tier}"}}',
            expires_at=datetime.utcnow() + timedelta(hours=1)
        )
        session.add(payment_invoice)
        await session.commit()

        text = (
            "💳 <b>Счет на оплату (Банковская карта)</b>\n\n"
            f"Сумма: <b>{price} ₽</b>\n"
            f"Срок подписки: <b>{days} дней</b>\n\n"
            "Нажмите «Оплатить» для перехода к оплате.\n"
            "Счет действителен в течение 1 часа.\n\n"
            f"ID заказа: <code>{order_id}</code>"
        )
        keyboard = get_payment_keyboard(payment_url, order_id)

        try:
            if callback.message.video or callback.message.animation or callback.message.photo:
                await callback.message.edit_caption(caption=text, reply_markup=keyboard, parse_mode="HTML")
            else:
                await callback.message.edit_text(text=text, reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            pass

        await state.update_data(invoice_id=order_id)
        await state.set_state(BuySubscription.waiting_for_payment)
        logger.info(f"Создан счет Platega {order_id} для пользователя {user_id} (Тариф: {tier})")

    except Exception as e:
        logger.error(f"Ошибка создания счета Platega: {e}")
        await callback.message.answer(
            "❌ Произошла ошибка при создании счета.\n\n"
            "Пожалуйста, попробуйте позже или выберите другой способ оплаты."
        )
    await callback.answer()


@router.callback_query(F.data.startswith("check_payment:"))
async def check_payment(callback: types.CallbackQuery, session: AsyncSession):
    """Проверка статуса оплаты."""
    user_id = callback.from_user.id
    invoice_id = callback.data.split(":")[1]

    await callback.answer("⏳ Проверяем оплату...", show_alert=False)

    result = await session.execute(
        select(PaymentInvoice).where(PaymentInvoice.invoice_id == invoice_id)
    )
    invoice = result.scalar_one_or_none()

    if not invoice:
        await callback.answer("Счет не найден. Создайте новый счет.", show_alert=True)
        return

    if invoice.status == "paid":
        await callback.answer("✅ Оплата уже подтверждена!", show_alert=True)
        return

    if invoice.status == "expired":
        await callback.answer("❌ Срок действия счета истек", show_alert=True)
        return

    if invoice.payment_method == "cryptobot":
        try:
            headers = {"Crypto-Pay-API-Token": settings.CRYPTO_BOT_TOKEN}
            async with httpx.AsyncClient(verify=False) as client:
                response = await client.get(
                    "https://pay.crypt.bot/api/getInvoices",
                    params={"invoice_ids": invoice_id},
                    headers=headers,
                    timeout=10.0
                )
                res_data = response.json()
                if res_data.get("ok") and res_data.get("result", {}).get("items"):
                    remote_invoice = res_data["result"]["items"][0]
                    status = remote_invoice.get("status")
                    
                    if status == "paid":
                        await process_manual_payment(callback.bot, session, invoice)
                        success_text = "✅ <b>Оплата подтверждена!</b> Подписка успешно выдана."
                        if callback.message.video or callback.message.animation or callback.message.photo:
                            await callback.message.edit_caption(caption=success_text, parse_mode="HTML")
                        else:
                            await callback.message.edit_text(text=success_text, parse_mode="HTML")
                        return
                    elif status in ["expired", "deleted"]:
                        invoice.status = "expired"
                        await session.commit()
                        fail_text = "❌ <b>Счет отменен или просрочен.</b>"
                        if callback.message.video or callback.message.animation or callback.message.photo:
                            await callback.message.edit_caption(caption=fail_text, parse_mode="HTML")
                        else:
                            await callback.message.edit_text(text=fail_text, parse_mode="HTML")
                        return
        except Exception as e:
            logger.error(f"Ошибка ручной проверки CryptoBot API: {e}")

    await callback.answer("⏳ Оплата ещё не поступила. Если вы только что оплатили, подождите минутку...", show_alert=True)


@router.callback_query(F.data == "cancel_payment")
async def cancel_payment(callback: types.CallbackQuery, state: FSMContext):
    """Отмена оплаты."""
    await state.clear()
    text = "❌ Оплата отменена.\n\nВыберите действие:"
    keyboard = get_main_menu_keyboard()
    
    try:
        if callback.message.video or callback.message.animation or callback.message.photo:
            await callback.message.edit_caption(caption=text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await callback.message.edit_text(text=text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        pass
        
    await callback.answer()

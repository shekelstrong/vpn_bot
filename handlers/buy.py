"""
Обработчик покупки подписки.
Интеграция с CryptoBot и Platega.
"""
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta
from loguru import logger

from database.models import User, PaymentInvoice
from keyboards.inline import (
    get_buy_keyboard,
    get_payment_keyboard,
    get_subscription_duration_keyboard,
    get_main_menu_keyboard,
)
from services.marzban_api import marzban_service
from services.payment_crypto import crypto_bot_service
from config import settings, get_db_setting, calculate_tariff_price

router = Router()

# Тарифы (дни)
SUBSCRIPTION_PERIODS = {
    "1month": {"days": 30, "months": 1},
    "3month": {"days": 90, "months": 3},
    "6month": {"days": 180, "months": 6},
    "12month": {"days": 365, "months": 12},
}

@router.callback_query(F.data == "buy")
@router.message(Command("buy"))
@router.message(F.text.startswith("Купить подписку"))
async def show_buy(callback_or_message: types.CallbackQuery | types.Message, session: AsyncSession):
    """Показать меню покупки подписки."""
    
    # ИСПРАВЛЕНИЕ: Правильно получаем user_id
    if isinstance(callback_or_message, types.CallbackQuery):
        callback = callback_or_message
        message = callback.message
        user_id = callback.from_user.id
        await callback.answer()
    else:
        message = callback_or_message
        callback = None
        user_id = message.from_user.id
    
    # Получаем базовую цену из настроек
    base_price = await get_db_setting(session, "subscription_price", str(settings.SUBSCRIPTION_PRICE_RUB))
    base_price = float(base_price)
    
    # Получаем пользователя
    result = await session.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        await message.answer("❌ Пользователь не найден. Нажмите /start")
        return
    
    # Проверяем текущий статус подписки
    has_subscription = user.expire_date and user.expire_date > datetime.utcnow()
    
    text = "🛒 <b>Магазин подписок Nemo VPN</b>\n\n"
    text += "Выберите срок подписки:\n\n"
    
    if has_subscription:
        days_left = (user.expire_date - datetime.utcnow()).days
        text += f"✅ <b>Ваша подписка активна ещё {days_left} дн.</b>\n"
        text += "Новая подписка продлит текущую.\n\n"
    
    # Рассчитываем цены с учетом скидок
    prices = {}
    for key, period in SUBSCRIPTION_PERIODS.items():
        months = period["months"]
        price = await calculate_tariff_price(session, base_price, months)
        prices[key] = price
        
        # Рассчитываем экономию (если есть скидка)
        discount_text = ""
        if months > 1:
            original_price = base_price * months
            savings = round(original_price - price, 2)
            discount_percent = round(savings / original_price * 100, 1)
            discount_text = f" (экономия {savings}₽, {discount_percent}% скидка)"
        
        text += f"▫️ {period['days']} дней — {int(price)}₽{discount_text}\n"
    
    await message.answer_video(
        video="оплата.mov",
        caption=text,
        reply_markup=get_subscription_duration_keyboard(
            price_1m=prices.get("1month", base_price),
            price_3m=prices.get("3month", base_price * 3),
            price_6m=prices.get("6month", base_price * 6),
            price_12m=prices.get("12month", base_price * 12)
        ),
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("duration"))
async def select_duration(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    """Выбор срока подписки."""
    duration = callback.data.replace("duration_", "")
    period = SUBSCRIPTION_PERIODS.get(duration)
    
    if not period:
        await callback.answer("❌ Неверный тариф", show_alert=True)
        return
    
    # Рассчитываем цену динамически
    base_price = await get_db_setting(session, "subscription_price", str(settings.SUBSCRIPTION_PRICE_RUB))
    base_price = float(base_price)
    months = period["months"]
    price = await calculate_tariff_price(session, base_price, months)
    
    # Сохраняем выбранный тариф
    await state.update_data(
        duration=duration,
        days=period["days"],
        price=int(price)
    )
    
    await callback.message.edit_text(
        text=(
            "✅ <b>Выбран тариф</b>\n\n"
            f"⏱ Срок: {period['days']} дней\n"
            f"💳 Цена: {int(price)}₽\n\n"
            "Выберите способ оплаты:"
        ),
        reply_markup=get_buy_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "pay_crypto")
async def pay_crypto(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    """Оплата через CryptoBot."""
    user_id = callback.from_user.id
    
    # Получаем данные из состояния
    data = await state.get_data()
    price = data.get("price", settings.SUBSCRIPTION_PRICE_RUB)
    days = data.get("days", settings.SUBSCRIPTION_EXPIRE_DAYS)

    await callback.answer("⏳ Создание счета...")

    try:
        # Создаем счет в CryptoBot
        custom_payload = f"user_{user_id}_sub_{days}d"
        
        invoice = await crypto_bot_service.create_invoice(
            amount=price,
            currency="RUB",
            description=f"Nemo VPN подписка на {days} дней",
            custom_payload=custom_payload,
            paid_btn_name="Вернуться в бот",
            paid_btn_url=f"https://t.me/{(await callback.bot.get_me()).username}",
            ttl=3600
        )

        invoice_id = invoice.get("invoice_id")
        invoice_url = invoice.get("invoice_url")

        # Сохраняем счет в БД
        payment_invoice = PaymentInvoice(
            user_id=user_id,
            invoice_id=str(invoice_id),
            amount=price,
            currency="RUB",
            payment_method="cryptobot",
            status="pending",
            payload=f'{{"days": {days}}}',
            expires_at=datetime.utcnow() + timedelta(hours=1)
        )
        session.add(payment_invoice)

        await callback.message.edit_text(
            text=(
                "💎 <b>Счет на оплату</b>\n\n"
                f"💰 Сумма: <b>{price}₽</b>\n"
                f"⏱ Срок подписки: <b>{days} дней</b>\n\n"
                "Нажмите «Оплатить» для перехода к оплате.\n"
                "Счет действителен в течение 1 часа.\n\n"
                f"ID счета: <code>{invoice_id}</code>"
            ),
            reply_markup=get_payment_keyboard(invoice_url, str(invoice_id))
        )

        await state.update_data(invoice_id=str(invoice_id))
        await state.set_state("waiting_for_payment")
        
        logger.info(f"Создан счет CryptoBot {invoice_id} для пользователя {user_id}")

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
    
    # Получаем данные из состояния
    data = await state.get_data()
    price = data.get("price", settings.SUBSCRIPTION_PRICE_RUB)
    days = data.get("days", settings.SUBSCRIPTION_EXPIRE_DAYS)

    await callback.answer("⏳ Создание счета...")

    try:
        import uuid
        order_id = f"platega_{user_id}_{uuid.uuid4().hex[:8]}"

        from services.payment_platega import platega_service
        
        payment_url = platega_service.create_payment_url(
            order_id=order_id,
            amount=price,
            currency="RUB",
            custom_id=str(user_id),
            description=f"Nemo VPN подписка на {days} дней"
        )

        # Сохраняем счет в БД
        payment_invoice = PaymentInvoice(
            user_id=user_id,
            invoice_id=order_id,
            amount=price,
            currency="RUB",
            payment_method="platega",
            status="pending",
            expires_at=datetime.utcnow() + timedelta(hours=1)
        )
        session.add(payment_invoice)

        await callback.message.edit_text(
            text=(
                "💳 <b>Счет на оплату (Банковская карта)</b>\n\n"
                f"💰 Сумма: <b>{price}₽</b>\n"
                f"⏱ Срок подписки: <b>{days} дней</b>\n\n"
                "Нажмите «Оплатить» для перехода к оплате.\n"
                "Счет действителен в течение 1 часа.\n\n"
                f"ID заказа: <code>{order_id}</code>"
            ),
            reply_markup=get_payment_keyboard(payment_url, order_id)
        )

        await state.update_data(invoice_id=order_id)
        await state.set_state("waiting_for_payment")
        
        logger.info(f"Создан счет Platega {order_id} для пользователя {user_id}")

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

    await callback.answer("⏳ Проверка оплаты...")

    # Получаем счет из БД
    result = await session.execute(
        select(PaymentInvoice).where(PaymentInvoice.invoice_id == invoice_id)
    )
    invoice = result.scalar_one_or_none()

    if not invoice:
        await callback.answer("❌ Счет не найден", show_alert=True)
        return

    # Проверяем статус
    if invoice.status == "paid":
        await callback.answer("✅ Оплата подтверждена!", show_alert=True)
        return
        
    if invoice.status == "pending":
        await callback.answer("⏳ Оплата ещё не подтверждена. Подождите...", show_alert=True)
        return
        
    if invoice.status == "expired":
        await callback.answer("❌ Срок действия счета истек", show_alert=True)
        return

    await callback.answer()

@router.callback_query(F.data == "cancel_payment")
async def cancel_payment(callback: types.CallbackQuery, state: FSMContext):
    """Отмена оплаты."""
    await state.clear()
    await callback.message.edit_text(
        text="❌ Оплата отменена.\n\nВыберите действие:",
        reply_markup=get_main_menu_keyboard()
    )
    await callback.answer()
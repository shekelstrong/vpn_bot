"""
Обработчик подарочной подписки.
"""
import json
import uuid
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta
from loguru import logger

from database.models import User, PaymentInvoice, Transaction, GiftCode
from keyboards.inline import (
    get_gift_tier_keyboard, get_gift_duration_keyboard, get_gift_payment_keyboard
)
from services.xui_api import xui_service as marzban_service
from services.payment_crypto import crypto_bot_service
from config import settings, get_db_setting

router = Router(name="gift_router")

# Цены подарочной подписки (единая подписка = оба конфига)
GIFT_PRICES = {
    "standard": {"1": 700, "3": 1800, "6": 3000, "12": 5500},
    "premium":  {"1": 700, "3": 1800, "6": 3000, "12": 5500},
}

# ГБ лимиты для подарков (БС инбаунд)
GIFT_GB = {"standard": 100, "premium": 100}


@router.callback_query(F.data == "gift_start")
@router.message(Command("gift"))
async def show_gift_start(callback_or_message: types.CallbackQuery | types.Message, session: AsyncSession, state: FSMContext):
    """Начало процесса подарочной подписки — выбор тарифа."""
    if isinstance(callback_or_message, types.CallbackQuery):
        message = callback_or_message.message
        await callback_or_message.answer()
    else:
        message = callback_or_message

    text = (
        "🎁 <b>Подарочная подписка</b>\n\n"
        "Подарите VPN друзьям и близким!\n\n"
        "1. Выберите тариф\n"
        "2. Выберите срок\n"
        "3. Оплатите\n"
        "4. Получите подарочную ссылку\n\n"
        "Выберите тариф:"
    )
    keyboard = get_gift_tier_keyboard()
    try:
        await message.edit_text(text=text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        await message.answer(text=text, reply_markup=keyboard, parse_mode="HTML")
    await state.set_state("gift_selecting_tier")


@router.callback_query(F.data.startswith("gift_tier_"))
async def gift_select_tier(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    """Выбор тарифа для подарка."""
    tier = callback.data.replace("gift_tier_", "")
    await state.update_data(gift_tier=tier)

    text = f"🎁 Выберите срок подарочной подписки ({'VIP' if tier == 'premium' else 'Обычный'}):"
    keyboard = get_gift_duration_keyboard(tier)
    try:
        await callback.message.edit_text(text=text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text=text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()
    await state.set_state("gift_selecting_duration")


@router.callback_query(F.data.startswith("gift_dur_"))
async def gift_select_duration(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    """Выбор срока → показ способов оплаты."""
    parts = callback.data.split("_")  # gift_dur_{tier}_{months}
    tier = parts[2]
    months = int(parts[3])
    days = months * 30

    price = GIFT_PRICES.get(tier, GIFT_PRICES["premium"]).get(str(months), 700)
    gb = GIFT_GB.get(tier, 100) * months

    await state.update_data(gift_tier=tier, gift_months=months, gift_days=days, gift_price=price, gift_gb=gb)

    user_id = callback.from_user.id
    result = await session.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    ref_balance = user.referral_balance if user else 0

    tier_name = "🛡 NEMO VPN (Стандарт + Обход БС)"
    text = (
        f"🎁 <b>Подарочная подписка</b>\n\n"
        f"💎 Тариф: <b>{tier_name}</b>\n"
        f"⏳ Срок: <b>{months} мес. ({days} дн.)</b>\n"
        f"📶 Трафик: <b>{gb if gb > 0 else 'Безлимит'} ГБ</b>\n"
        f"💵 Цена: <b>{price} ₽</b>\n\n"
        f"Выберите способ оплаты:"
    )

    keyboard = get_gift_payment_keyboard(tier, months, price, ref_balance)
    try:
        await callback.message.edit_text(text=text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text=text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()
    await state.set_state("gift_selecting_payment")


@router.callback_query(F.data == "gift_pay_crypto")
async def gift_pay_crypto(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    """Оплата подарка через CryptoBot."""
    data = await state.get_data()
    tier = data.get("gift_tier", "standard")
    days = data.get("gift_days", 30)
    price = data.get("gift_price", 100)
    gb = data.get("gift_gb", 0)
    user_id = callback.from_user.id

    try:
        price_usdt = round(price / settings.USDT_TO_RUB_RATE, 2)
        bot_info = await callback.bot.get_me()
        bot_username = bot_info.username

        invoice = PaymentInvoice(
            user_id=user_id,
            invoice_id=f"temp_gift_{user_id}_{int(datetime.utcnow().timestamp())}",
            amount=price,
            currency="RUB",
            payment_method="cryptobot",
            status="pending",
            payload=json.dumps({"type": "gift", "tier": tier, "days": days, "gb": gb, "price": price}),
            expires_at=datetime.utcnow() + timedelta(hours=1)
        )
        session.add(invoice)
        await session.flush()
        order_id = invoice.id

        result = await crypto_bot_service.create_invoice(
            amount_usdt=price_usdt,
            order_id=str(order_id),
            description=f"Nemo VPN: Подарок {days} дней ({'VIP' if tier == 'premium' else 'Обычный'})",
            paid_btn_name="Вернуться в бот",
            paid_btn_url=f"https://t.me/{bot_username}"
        )

        if not result:
            raise Exception("Не удалось создать счет в CryptoBot")

        invoice_url, real_invoice_id = result
        invoice.invoice_id = str(real_invoice_id)
        await session.commit()

        text = (
            f"🎁 <b>Оплата подарка криптовалютой</b>\n\n"
            f"Сумма: <b>{price_usdt} USDT</b>\n\n"
            f"После оплаты вы получите подарочную ссылку."
        )
        from keyboards.inline import get_payment_keyboard
        keyboard = get_payment_keyboard(invoice_url, str(real_invoice_id))
        await callback.message.edit_text(text=text, reply_markup=keyboard, parse_mode="HTML")
        logger.info(f"Создан счет CryptoBot на подарок для {user_id}")
    except Exception as e:
        logger.error(f"Ошибка создания счета подарка CryptoBot: {e}")
        await callback.message.answer("❌ Ошибка при создании счета. Попробуйте позже.")
    await callback.answer()


@router.callback_query(F.data == "gift_pay_card")
async def gift_pay_card(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    """Оплата подарка через Platega."""
    data = await state.get_data()
    tier = data.get("gift_tier", "standard")
    days = data.get("gift_days", 30)
    price = data.get("gift_price", 100)
    gb = data.get("gift_gb", 0)
    user_id = callback.from_user.id

    try:
        order_id = f"platega_gift_{user_id}_{uuid.uuid4().hex[:8]}"
        from services.payment_platega import create_invoice
        payment_url = await create_invoice(
            amount_rub=int(price),
            order_id=order_id,
            user_id=user_id,
            description=f"Nemo VPN: Подарок {days} дней ({'VIP' if tier == 'premium' else 'Обычный'})"
        )

        if not payment_url:
            raise Exception("Не удалось создать счет в Platega")

        invoice = PaymentInvoice(
            user_id=user_id,
            invoice_id=order_id,
            amount=price,
            currency="RUB",
            payment_method="platega",
            status="pending",
            payload=json.dumps({"type": "gift", "tier": tier, "days": days, "gb": gb, "price": price}),
            expires_at=datetime.utcnow() + timedelta(hours=1)
        )
        session.add(invoice)
        await session.commit()

        text = (
            f"🎁 <b>Оплата подарка картой</b>\n\n"
            f"Сумма: <b>{price} ₽</b>\n\n"
            f"После оплаты вы получите подарочную ссылку."
        )
        from keyboards.inline import get_payment_keyboard
        keyboard = get_payment_keyboard(payment_url, order_id)
        await callback.message.edit_text(text=text, reply_markup=keyboard, parse_mode="HTML")
        logger.info(f"Создан счет Platega на подарок для {user_id}")
    except Exception as e:
        logger.error(f"Ошибка создания счета подарка Platega: {e}")
        await callback.message.answer("❌ Ошибка при создании счета. Попробуйте позже.")
    await callback.answer()


@router.callback_query(F.data == "gift_pay_referral")
async def gift_pay_referral(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    """Оплата подарка из реферального баланса."""
    data = await state.get_data()
    tier = data.get("gift_tier", "standard")
    days = data.get("gift_days", 30)
    price = data.get("gift_price", 100)
    gb = data.get("gift_gb", 0)
    user_id = callback.from_user.id

    result = await session.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    total_balance = user.balance + user.referral_balance
    if total_balance < price:
        await callback.answer(f"❌ Недостаточно средств. Баланс: {total_balance:.0f}₽, нужно: {price}₽", show_alert=True)
        return

    # Списываем
    remaining = price
    if user.balance >= remaining:
        user.balance -= remaining
    else:
        remaining -= user.balance
        user.balance = 0.0
        user.referral_balance -= remaining

    # Создаём подарочный код
    bot_info = await callback.bot.get_me()
    code = await _create_gift_code(session, user_id, tier, days, gb)

    tx = Transaction(
        user_id=user_id,
        amount=price,
        currency="RUB",
        payment_method="referral_balance_gift",
        status="paid",
        payment_id=f"ref_gift_{uuid.uuid4().hex[:8]}",
        description=f"Подарочная подписка {days} дней ({tier}) из реферального баланса"
    )
    session.add(tx)
    await session.commit()

    gift_link = f"https://t.me/{bot_info.username}?start=gift_{code}"
    await callback.message.edit_text(
        f"🎁 <b>Подарочная подписка оплачена!</b>\n\n"
        f"Отправьте эту ссылку другу:\n\n"
        f"<code>{gift_link}</code>\n\n"
        f"⏳ Код действителен <b>30 дней</b>.",
        parse_mode="HTML"
    )
    await callback.answer()
    await state.clear()


async def _create_gift_code(session: AsyncSession, creator_id: int, tier: str, days: int, gb: float) -> str:
    """Создать подарочный код в БД и вернуть его."""
    code = str(uuid.uuid4())
    gift = GiftCode(
        code=code,
        creator_id=creator_id,
        tier=tier,
        days=days,
        gb_limit=gb,
        expires_at=datetime.utcnow() + timedelta(days=30)
    )
    session.add(gift)
    await session.flush()
    return code


async def process_gift_payment_success(bot, session: AsyncSession, user_id: int, tier: str, days: int, gb: float, price: float):
    """Вызывается после оплаты подарка — создаёт код и отправляет ссылку."""
    bot_info = await bot.get_me()
    code = await _create_gift_code(session, user_id, tier, days, gb)

    gift_link = f"https://t.me/{bot_info.username}?start=gift_{code}"

    await bot.send_message(
        user_id,
        f"🎁 <b>Подарочная подписка оплачена!</b>\n\n"
        f"Отправьте эту ссылку другу:\n\n"
        f"<code>{gift_link}</code>\n\n"
        f"⏳ Код действителен <b>30 дней</b>.",
        parse_mode="HTML"
    )
    logger.info(f"Подарочный код {code} создан для {user_id}")

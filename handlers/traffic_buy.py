"""
Обработчик докупки трафика (ГБ).
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

from database.models import User, PaymentInvoice, Transaction
from keyboards.inline import get_traffic_buy_keyboard, get_traffic_payment_keyboard, TRAFFIC_PACKAGES
from services.marzban_api import marzban_service
from services.payment_crypto import crypto_bot_service
from config import settings

router = Router(name="traffic_buy_router")


@router.callback_query(F.data == "traffic_buy")
@router.message(Command("traffic"))
async def show_traffic_buy(callback_or_message: types.CallbackQuery | types.Message, session: AsyncSession):
    """Показать меню докупки ГБ."""
    if isinstance(callback_or_message, types.CallbackQuery):
        message = callback_or_message.message
        user_id = callback_or_message.from_user.id
        await callback_or_message.answer()
    else:
        message = callback_or_message
        user_id = callback_or_message.from_user.id

    result = await session.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        await message.answer("❌ Пользователь не найден. Нажмите /start")
        return

    # Докупка трафика доступна только для VIP-тарифа
    if user.tier != "premium":
        try:
            await message.edit_text(
                "ℹ️ <b>Докупка трафика доступна только для VIP-тарифа.</b>\n\n"
                "У вас обычный VPN с безлимитным трафиком — докупать гигабайты не нужно!",
                parse_mode="HTML"
            )
        except Exception:
            await message.answer(
                "ℹ️ <b>Докупка трафика доступна только для VIP-тарифа.</b>\n\n"
                "У вас обычный VPN с безлимитным трафиком — докупать гигабайты не нужно!",
                parse_mode="HTML"
            )
        return

    text = (
        "📶 <b>Докупка трафика</b>\n\n"
        f"Текущий лимит: <b>{user.gb_limit or 0} ГБ</b>\n\n"
        "Выберите пакет дополнительного трафика:"
    )

    keyboard = get_traffic_buy_keyboard()

    try:
        await message.edit_text(text=text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        await message.answer(text=text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data.startswith("traffic_") and ~F.data.startswith("traffic_pay"))
async def select_traffic_package(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    """Выбор пакета ГБ → показ способов оплаты."""
    gb = int(callback.data.replace("traffic_", ""))
    price = next((p for g, p in TRAFFIC_PACKAGES if g == gb), None)
    if not price:
        await callback.answer("Пакет не найден", show_alert=True)
        return

    user_id = callback.from_user.id
    result = await session.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    ref_balance = user.referral_balance if user else 0

    await state.update_data(traffic_gb=gb, traffic_price=price)

    text = (
        f"📶 <b>Докупка трафика</b>\n\n"
        f"Пакет: <b>+{gb} ГБ</b>\n"
        f"Цена: <b>{price} ₽</b>\n\n"
        f"Выберите способ оплаты:"
    )

    keyboard = get_traffic_payment_keyboard(gb, price, ref_balance)
    try:
        await callback.message.edit_text(text=text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text=text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "traffic_pay_crypto")
async def traffic_pay_crypto(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    """Оплата докупки трафика через CryptoBot."""
    data = await state.get_data()
    gb = data.get("traffic_gb")
    price = data.get("traffic_price")
    user_id = callback.from_user.id

    if not gb or not price:
        await callback.answer("Ошибка: выберите пакет заново", show_alert=True)
        return

    try:
        price_usdt = round(price / settings.USDT_TO_RUB_RATE, 2)
        bot_info = await callback.bot.get_me()
        bot_username = bot_info.username

        invoice = PaymentInvoice(
            user_id=user_id,
            invoice_id=f"temp_traffic_{user_id}_{int(datetime.utcnow().timestamp())}",
            amount=price,
            currency="RUB",
            payment_method="cryptobot",
            status="pending",
            payload=json.dumps({"type": "traffic", "gb": gb, "price": price}),
            expires_at=datetime.utcnow() + timedelta(hours=1)
        )
        session.add(invoice)
        await session.flush()
        order_id = invoice.id

        result = await crypto_bot_service.create_invoice(
            amount_usdt=price_usdt,
            order_id=str(order_id),
            description=f"Nemo VPN: +{gb} ГБ трафика",
            paid_btn_name="Вернуться в бот",
            paid_btn_url=f"https://t.me/{bot_username}"
        )

        if not result:
            raise Exception("Не удалось создать счет в CryptoBot")

        invoice_url, real_invoice_id = result
        invoice.invoice_id = str(real_invoice_id)
        await session.commit()

        text = (
            f"📶 <b>Оплата трафика криптовалютой</b>\n\n"
            f"Пакет: <b>+{gb} ГБ</b>\n"
            f"Сумма: <b>{price_usdt} USDT</b>\n\n"
            f"Нажмите «Оплатить» для перехода к оплате."
        )
        from keyboards.inline import get_payment_keyboard
        keyboard = get_payment_keyboard(invoice_url, str(real_invoice_id))
        await callback.message.edit_text(text=text, reply_markup=keyboard, parse_mode="HTML")
        logger.info(f"Создан счет CryptoBot на трафик +{gb}ГБ для {user_id}")
    except Exception as e:
        logger.error(f"Ошибка создания счета трафика CryptoBot: {e}")
        await callback.message.answer("❌ Ошибка при создании счета. Попробуйте позже.")
    await callback.answer()


@router.callback_query(F.data == "traffic_pay_card")
async def traffic_pay_card(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    """Оплата докупки трафика через Platega."""
    data = await state.get_data()
    gb = data.get("traffic_gb")
    price = data.get("traffic_price")
    user_id = callback.from_user.id

    if not gb or not price:
        await callback.answer("Ошибка: выберите пакет заново", show_alert=True)
        return

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

        invoice = PaymentInvoice(
            user_id=user_id,
            invoice_id=order_id,
            amount=price,
            currency="RUB",
            payment_method="platega",
            status="pending",
            payload=json.dumps({"type": "traffic", "gb": gb, "price": price}),
            expires_at=datetime.utcnow() + timedelta(hours=1)
        )
        session.add(invoice)
        await session.commit()

        text = (
            f"📶 <b>Оплата трафика картой</b>\n\n"
            f"Пакет: <b>+{gb} ГБ</b>\n"
            f"Сумма: <b>{price} ₽</b>\n\n"
            f"Нажмите «Оплатить» для перехода к оплате."
        )
        from keyboards.inline import get_payment_keyboard
        keyboard = get_payment_keyboard(payment_url, order_id)
        await callback.message.edit_text(text=text, reply_markup=keyboard, parse_mode="HTML")
        logger.info(f"Создан счет Platega на трафик +{gb}ГБ для {user_id}")
    except Exception as e:
        logger.error(f"Ошибка создания счета трафика Platega: {e}")
        await callback.message.answer("❌ Ошибка при создании счета. Попробуйте позже.")
    await callback.answer()


@router.callback_query(F.data == "traffic_pay_referral")
async def traffic_pay_referral(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    """Оплата докупки трафика из реферального баланса."""
    data = await state.get_data()
    gb = data.get("traffic_gb")
    price = data.get("traffic_price")
    user_id = callback.from_user.id

    if not gb or not price:
        await callback.answer("Ошибка: выберите пакет заново", show_alert=True)
        return

    result = await session.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    # Докупка трафика доступна только для VIP-тарифа
    if user.tier != "premium":
        await callback.answer("Докупка трафика доступна только для VIP-тарифа", show_alert=True)
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

    # Начисляем ГБ
    current_gb = user.gb_limit or 0
    user.gb_limit = current_gb + gb

    # Обновляем Marzban
    if user.marzban_username:
        try:
            # Получаем текущий использованный трафик
            mz_data = await marzban_service.get_user(user.marzban_username)
            used_traffic = mz_data.get('used_traffic', 0) if mz_data else 0
            new_limit_bytes = int(user.gb_limit * 1024**3)
            await marzban_service.update_user_data_limit(user.marzban_username, new_limit_bytes)
        except Exception as e:
            logger.error(f"Ошибка обновления Marzban при докупке трафика: {e}")

    # Транзакция
    tx = Transaction(
        user_id=user_id,
        amount=price,
        currency="RUB",
        payment_method="referral_balance_traffic",
        status="paid",
        payment_id=f"ref_traffic_{uuid.uuid4().hex[:8]}",
        description=f"Докупка +{gb} ГБ трафика из реферального баланса"
    )
    session.add(tx)
    await session.commit()

    await callback.message.edit_text(
        f"✅ <b>Трафик докуплен!</b>\n\n"
        f"📶 Добавлено: <b>+{gb} ГБ</b>\n"
        f"📊 Новый лимит: <b>{user.gb_limit} ГБ</b>\n"
        f"💰 Списано: <b>{price} ₽</b> с баланса",
        parse_mode="HTML"
    )
    await callback.answer()
    await state.clear()

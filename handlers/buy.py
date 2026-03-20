import json
import httpx
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
    get_main_menu_keyboard,
)
from services.marzban_api import marzban_service
from services.payment_crypto import crypto_bot_service
from handlers.admin.notifications import (
    notify_user_purchase,
    notify_admin_payment,
    notify_referrer_payment
)
from config import settings, get_db_setting, calculate_tariff_price

router = Router()

# Тарифы (дни)
SUBSCRIPTION_PERIODS = {
    "test3d": {"days": 3, "months": 0, "fixed_price": 10}, # Тестовый тариф
    "1month": {"days": 30, "months": 1},
    "3month": {"days": 90, "months": 3},
    "6month": {"days": 180, "months": 6},
    "12month": {"days": 365, "months": 12},
}

async def _process_manual_payment(bot, session: AsyncSession, payment_invoice: PaymentInvoice):
    """Ручная обработка выдачи подписки, если вебхук потерялся по пути к серверу."""
    try:
        days = 30
        if payment_invoice.payload:
            try:
                payload_data = json.loads(payment_invoice.payload)
                days = payload_data.get("days", 30)
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
            description=f"Оплата подписки на {days} дней",
        )
        session.add(transaction)

        now = datetime.utcnow()
        if user.expire_date and user.expire_date > now:
            user.expire_date = user.expire_date + timedelta(days=days)
        else:
            user.expire_date = now + timedelta(days=days)

        marzban_account_exists = False
        if user.marzban_username:
            try:
                marzban_data = await marzban_service.get_user(user.marzban_username)
                if marzban_data:
                    marzban_account_exists = True
            except: pass

        if marzban_account_exists:
            await marzban_service.update_user_expiry(user.marzban_username, days)
        else:
            new_acc = await marzban_service.create_user(
                tg_id=user.user_id,
                username=user.username,
                expire_days=days,
                data_limit_gb=0.0
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
async def show_buy(callback_or_message: types.CallbackQuery | types.Message, session: AsyncSession):
    """Показать меню покупки подписки."""
    if isinstance(callback_or_message, types.CallbackQuery):
        callback = callback_or_message
        message = callback.message
        user_id = callback.fromuser.id if hasattr(callback, 'from_user') else callback.from_user.id
        await callback.answer()
    else:
        message = callback_or_message
        callback = None
        user_id = message.from_user.id

    base_price = await get_db_setting(session, "subscription_price", str(settings.SUBSCRIPTION_PRICE_RUB))
    base_price = float(base_price)

    result = await session.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        await message.answer("❌ Пользователь не найден. Нажмите /start")
        return

    has_subscription = user.expire_date and user.expire_date > datetime.utcnow()

    text = "🛒 <b>Магазин подписок Nemo VPN</b>\n\n"
    text += "Выберите срок подписки:\n\n"

    if has_subscription:
        days_left = (user.expire_date - datetime.utcnow()).days
        text += f"⭐️ <b>Ваша подписка активна ещё {days_left} дн.</b>\n"
        text += "Новая подписка продлит текущую.\n\n"

    prices = {}
    for key, period in SUBSCRIPTION_PERIODS.items():
        if "fixed_price" in period:
            price = float(period["fixed_price"])
        else:
            months = period["months"]
            price = await calculate_tariff_price(session, base_price, months)
        prices[key] = price

        discount_text = ""
        if "fixed_price" not in period and period["months"] > 1:
            original_price = base_price * period["months"]
            savings = round(original_price - price, 2)
            discount_percent = round(savings / original_price * 100, 1)
            discount_text = f" (экономия {savings}₽, {discount_percent}% скидка)"
        text += f"▪️ {period['days']} дней — {int(price)}₽{discount_text}\n"

    keyboard = get_subscription_duration_keyboard(
        price_test=prices.get("test3d", 10),
        price_1m=prices.get("1month", base_price),
        price_3m=prices.get("3month", base_price * 3),
        price_6m=prices.get("6month", base_price * 6),
        price_12m=prices.get("12month", base_price * 12)
    )

    try:
        # ИСПРАВЛЕНИЕ: Используем актуальный file_id и метод answer_animation для GIF
        await message.answer_animation(
            animation="CgACAgIAAxkBAAIE7Wm804DyYOvViOUC--9rsXLvJ8ZtAALanwACaxDgSamsbGW6emV7OgQ",
            caption=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.warning(f"Не удалось отправить GIF ({e}), отправляем текстом.")
        await message.answer(text=text, reply_markup=keyboard, parse_mode="HTML")

@router.callback_query(F.data.startswith("duration_"))
async def select_duration(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    """Выбор срока подписки."""
    duration = callback.data.replace("duration_", "")
    period = SUBSCRIPTION_PERIODS.get(duration)

    if not period:
        await callback.answer("❌ Неверный тариф", show_alert=True)
        return

    base_price = await get_db_setting(session, "subscription_price", str(settings.SUBSCRIPTION_PRICE_RUB))
    base_price = float(base_price)

    if "fixed_price" in period:
        price = float(period["fixed_price"])
    else:
        months = period["months"]
        price = await calculate_tariff_price(session, base_price, months)

    await state.update_data(
        duration=duration,
        days=period["days"],
        price=int(price)
    )

    text = (
        "✅ <b>Выбран тариф</b>\n\n"
        f"⏳ Срок: {period['days']} дней\n"
        f"💰 Цена: {int(price)} ₽\n\n"
        "Выберите способ оплаты: 👇"
    )
    keyboard = get_buy_keyboard()

    try:
        # Улучшенная проверка на наличие медиа-контента (видео, анимация, фото)
        if callback.message.video or callback.message.animation or callback.message.photo:
            await callback.message.edit_caption(caption=text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await callback.message.edit_text(text=text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ошибка редактирования меню покупки: {e}")

    await callback.answer()

@router.callback_query(F.data == "pay_crypto")
async def pay_crypto(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    """Оплата через CryptoBot (USDT)."""
    user_id = callback.from_user.id
    
    data = await state.get_data()
    price_rub = data.get("price", settings.SUBSCRIPTION_PRICE_RUB)
    days = data.get("days", settings.SUBSCRIPTION_EXPIRE_DAYS)

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
            payload=f'{{"days": {days}, "amount_usdt": {price_usdt}}}',
            expires_at=datetime.utcnow() + timedelta(hours=1)
        )
        session.add(payment_invoice)
        await session.flush()
        order_id = payment_invoice.id

        result = await crypto_bot_service.create_invoice(
            amount_usdt=price_usdt,
            order_id=order_id,
            description=f"Nemo VPN подписка на {days} дней ({price_rub}₽)",
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
            f"💰 Сумма: <b>{price_usdt} USDT</b>\n"
            f"📝 Заказ: <code>#{order_id}</code>\n\n"
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
        await state.set_state("waiting_for_payment")
        logger.info(f"Создан счет CryptoBot #{order_id} (ID: {real_invoice_id}) для {user_id}: {price_usdt} USDT")

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

        text = (
            "💳 <b>Счет на оплату (Банковская карта)</b>\n\n"
            f"💰 Сумма: <b>{price}₽</b>\n"
            f"⏳ Срок подписки: <b>{days} дней</b>\n\n"
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

    await callback.answer("⏳ Проверяем оплату...", show_alert=False)

    result = await session.execute(
        select(PaymentInvoice).where(PaymentInvoice.invoice_id == invoice_id)
    )
    invoice = result.scalar_one_or_none()

    if not invoice:
        await callback.answer("❌ Счет не найден. Создайте новый счет.", show_alert=True)
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
                        await _process_manual_payment(callback.bot, session, invoice)
                        
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
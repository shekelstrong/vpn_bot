"""
Обработчик оплаты подписки из реферального баланса.
"""
import uuid
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta
from loguru import logger

from database.models import User, Transaction
from keyboards.inline import get_tier_selection_keyboard, get_subscription_duration_keyboard, get_buy_keyboard
from services.marzban_api import marzban_service
from config import settings, get_db_setting, calculate_tariff_price

router = Router(name="referral_buy_router")


@router.callback_query(F.data == "pay_referral")
async def pay_from_referral(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    """Оплата подписки из реферального баланса."""
    data = await state.get_data()
    days = data.get("days", 30)
    price = data.get("price", settings.SUBSCRIPTION_PRICE_RUB)
    tier = data.get("tier", "standard")
    user_id = callback.from_user.id

    result = await session.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    total_balance = user.balance + user.referral_balance
    if total_balance < price:
        shortage = price - total_balance
        await callback.answer(
            f"❌ Недостаточно средств. Баланс: {total_balance:.0f}₽, не хватает: {shortage:.0f}₽",
            show_alert=True
        )
        return

    # Списываем (сначала основной, потом реферальный)
    remaining = price
    if user.balance >= remaining:
        user.balance -= remaining
    else:
        remaining -= user.balance
        user.balance = 0.0
        user.referral_balance -= remaining

    # Продлеваем подписку
    now = datetime.utcnow()
    if user.expire_date and user.expire_date > now:
        user.expire_date = user.expire_date + timedelta(days=days)
    else:
        user.expire_date = now + timedelta(days=days)

    user.tier = tier

    # Marzban
    try:
        gb_limit = user.gb_limit or 0
        if user.marzban_username:
            mz_data = await marzban_service.get_user(user.marzban_username)
            if mz_data:
                await marzban_service.update_user_full(
                    user.marzban_username, extra_days=days, tier=tier,
                    device_count=user.device_count, data_limit_gb=gb_limit
                )
            else:
                new_acc = await marzban_service.create_user(
                    user_id, user.username, days, data_limit_gb=gb_limit, tier=tier, device_count=user.device_count
                )
                user.marzban_username = new_acc.get('username')
        else:
            new_acc = await marzban_service.create_user(
                user_id, user.username, days, data_limit_gb=gb_limit, tier=tier, device_count=user.device_count
            )
            user.marzban_username = new_acc.get('username')
    except Exception as e:
        logger.error(f"Ошибка Marzban при оплате из реферального баланса: {e}")

    tx = Transaction(
        user_id=user_id,
        amount=price,
        currency="RUB",
        payment_method="referral_balance",
        status="paid",
        payment_id=f"ref_sub_{uuid.uuid4().hex[:8]}",
        description=f"Оплата подписки {days} дней ({tier}) из баланса"
    )
    session.add(tx)
    await session.commit()

    tier_name = "🚀 VIP Обход белых списков" if tier == "premium" else "🛡 Обычный VPN"
    await callback.message.edit_text(
        f"✅ <b>Оплата с баланса прошла успешно!</b>\n\n"
        f"💎 Тариф: <b>{tier_name}</b>\n"
        f"⏳ Подписка: <b>{days} дней</b>\n"
        f"💰 Списано: <b>{price:.0f} ₽</b>",
        parse_mode="HTML"
    )
    await callback.answer()
    await state.clear()


@router.callback_query(F.data == "referral_buy")
async def show_referral_buy_menu(callback: types.CallbackQuery, session: AsyncSession):
    """Показать баланс и предложить использовать."""
    user_id = callback.from_user.id
    result = await session.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    total_balance = user.balance + user.referral_balance
    text = (
        f"💳 <b>Оплата из баланса</b>\n\n"
        f"Основной баланс: <b>{user.balance:.2f} ₽</b>\n"
        f"Реферальный баланс: <b>{user.referral_balance:.2f} ₽</b>\n"
        f"Итого доступно: <b>{total_balance:.2f} ₽</b>\n\n"
        f"Для оплаты перейдите в раздел покупки подписки и выберите «💳 Из реферального баланса»."
    )
    await callback.message.edit_text(text=text, reply_markup=get_tier_selection_keyboard(), parse_mode="HTML")
    await callback.answer()

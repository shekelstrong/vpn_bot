"""
Логика реферальной системы и вывода средств.
"""

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import uuid

from database.models import User, Transaction
from handlers.admin.notifications import notify_admin_withdrawal
from config import settings

router = Router(name="referrals_router")

# --- FSM States для вывода ---
class WithdrawStates(StatesGroup):
    waiting_for_amount = State()
    waiting_for_details = State()

# --- Клавиатуры ---
def withdraw_method_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 На баланс VPN (Моментально)", callback_data="withdraw_method:internal")],
        [InlineKeyboardButton(text="💳 На банковскую карту", callback_data="withdraw_method:card")],
        [InlineKeyboardButton(text="🪙 В криптовалюте (USDT/TON)", callback_data="withdraw_method:crypto")],
        [InlineKeyboardButton(text="Отмена ❌", callback_data="cancel_withdraw")]
    ])

def cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отмена ❌", callback_data="cancel_withdraw")]
    ])

# ==================== МЕНЮ РЕФЕРАЛОВ ====================

@router.callback_query(F.data == "referral_stats")
async def show_referral_menu(callback: CallbackQuery, session: AsyncSession):
    user_id = callback.from_user.id
    bot_info = await callback.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user_id}"
    
    # Достаем юзера
    user = await session.scalar(select(User).where(User.user_id == user_id))
    
    if not user:
        await callback.answer("Ошибка: пользователь не найден", show_alert=True)
        return
        
    # Считаем 3 уровня рефералов
    l1_users = await session.scalars(select(User).where(User.referrer_id == user_id))
    l1_ids = [u.user_id for u in l1_users]
    
    l2_ids, l3_ids = [], []
    if l1_ids:
        l2_users = await session.scalars(select(User).where(User.referrer_id.in_(l1_ids)))
        l2_ids = [u.user_id for u in l2_users]
        if l2_ids:
            l3_users = await session.scalars(select(User).where(User.referrer_id.in_(l2_ids)))
            l3_ids = [u.user_id for u in l3_users]

    text = (
        f"👥 <b>Ваша партнерская программа</b>\n\n"
        f"🔗 <b>Ваша ссылка:</b>\n<code>{ref_link}</code>\n\n"
        f"<b>Статистика:</b>\n"
        f"Уровень 1 (15%): <b>{len(l1_ids)} чел.</b>\n"
        f"Уровень 2 (10%): <b>{len(l2_ids)} чел.</b>\n"
        f"Уровень 3 (5%): <b>{len(l3_ids)} чел.</b>\n\n"
        f"💰 <b>Реферальный баланс:</b> {user.referral_balance:.2f}₽\n"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💸 Вывести средства", callback_data="start_withdraw")],
        [InlineKeyboardButton(text="Назад ↩️", callback_data="back_to_main")]
    ])
    
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

# ==================== ПРОЦЕСС ВЫВОДА СРЕДСТВ ====================

@router.callback_query(F.data == "cancel_withdraw")
async def cancel_withdraw(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Вывод средств отменен.")

@router.callback_query(F.data == "start_withdraw")
async def start_withdraw(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    user = await session.scalar(select(User).where(User.user_id == callback.from_user.id))
    
    if user.referral_balance < 50:
        await callback.answer("❌ Минимальная сумма вывода: 50₽", show_alert=True)
        return
        
    await state.set_state(WithdrawStates.waiting_for_amount)
    await callback.message.edit_text(
        f"💰 Ваш реферальный баланс: <b>{user.referral_balance:.2f}₽</b>\n\n"
        f"Введите сумму, которую хотите вывести (числом):",
        reply_markup=cancel_kb(),
        parse_mode="HTML"
    )

@router.message(WithdrawStates.waiting_for_amount)
async def process_withdraw_amount(message: Message, session: AsyncSession, state: FSMContext):
    try:
        amount = float(message.text.replace(',', '.'))
    except ValueError:
        await message.answer("❌ Пожалуйста, введите корректное число.", reply_markup=cancel_kb())
        return

    user = await session.scalar(select(User).where(User.user_id == message.from_user.id))
    
    if amount < 50:
        await message.answer("❌ Минимальная сумма вывода: 50₽", reply_markup=cancel_kb())
        return
    if amount > user.referral_balance:
        await message.answer(f"❌ На вашем реферальном балансе недостаточно средств (максимум {user.referral_balance:.2f}₽).", reply_markup=cancel_kb())
        return

    await state.update_data(withdraw_amount=amount)
    await state.set_state(WithdrawStates.waiting_for_details)
    
    await message.answer(
        f"Выводим: <b>{amount:.2f}₽</b>.\nВыберите куда хотите получить средства:",
        reply_markup=withdraw_method_kb(),
        parse_mode="HTML"
    )

@router.callback_query(WithdrawStates.waiting_for_details, F.data.startswith("withdraw_method:"))
async def process_withdraw_method(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    method = callback.data.split(":")[1]
    data = await state.get_data()
    amount = data['withdraw_amount']
    
    # 1. МОМЕНТАЛЬНЫЙ ПЕРЕВОД НА ВНУТРЕННИЙ БАЛАНС
    if method == "internal":
        user = await session.scalar(select(User).where(User.user_id == callback.from_user.id))
        if user.referral_balance >= amount:
            user.referral_balance -= amount
            user.balance += amount
            await session.commit()
            
            # Тихое уведомление админам для статистики
            for admin_id in settings.admin_ids_list:
                try:
                    await callback.bot.send_message(admin_id, f"ℹ️ Юзер {user.user_id} перевел {amount}₽ с реф. баланса на основной.")
                except: pass
                
            await callback.message.edit_text(f"✅ <b>{amount:.2f}₽</b> успешно переведены на ваш основной баланс для покупки VPN!", parse_mode="HTML")
        await state.clear()
        return

    # 2. ВЫВОД НА КАРТУ ИЛИ КРИПТУ
    await state.update_data(withdraw_method=method)
    text = "💳 Введите номер вашей банковской карты (и название банка):" if method == "card" else "🪙 Введите адрес вашего крипто-кошелька (сеть TRC20/TON):"
    
    await callback.message.edit_text(text, reply_markup=cancel_kb())

@router.message(WithdrawStates.waiting_for_details)
async def finalize_withdraw_request(message: Message, session: AsyncSession, state: FSMContext):
    details = message.text
    data = await state.get_data()
    amount = data['withdraw_amount']
    method_raw = data['withdraw_method']
    method_name = "Банковская карта" if method_raw == "card" else "Криптовалюта"
    
    user = await session.scalar(select(User).where(User.user_id == message.from_user.id))
    
    if user.referral_balance >= amount:
        # Списываем (замораживаем) баланс
        user.referral_balance -= amount
        
        # Создаем транзакцию со статусом PENDING
        tx = Transaction(
            user_id=user.user_id,
            amount=amount,
            currency="RUB",
            payment_method=f"WITHDRAW_{method_raw.upper()}",
            status="PENDING",
            payment_id=str(uuid.uuid4())[:8], # Уникальный ID
            description=details
        )
        session.add(tx)
        await session.commit()
        await session.refresh(tx)
        
        # Отправляем красивое уведомление админу
        await notify_admin_withdrawal(
            bot=message.bot,
            user_id=user.user_id,
            amount=amount,
            method=method_name,
            details=details,
            withdrawal_id=tx.id,
            username=message.from_user.username
        )
        
        await message.answer("✅ <b>Ваша заявка на вывод успешно создана!</b>\nАдминистратор обработает ее в ближайшее время.", parse_mode="HTML")
    else:
        await message.answer("❌ Ошибка: недостаточно средств.")
        
    await state.clear()

# ==================== ДЕЙСТВИЯ АДМИНА (КНОПКИ ПОД ЗАЯВКОЙ) ====================

@router.callback_query(F.data.startswith("withdraw_done:"))
async def admin_withdraw_done(callback: CallbackQuery, session: AsyncSession):
    tx_id = int(callback.data.split(":")[1])
    tx = await session.scalar(select(Transaction).where(Transaction.id == tx_id))
    
    if not tx or tx.status != "PENDING":
        await callback.answer("Заявка уже обработана или не найдена.", show_alert=True)
        return
        
    tx.status = "COMPLETED"
    await session.commit()
    
    await callback.message.edit_text(callback.message.html_text + "\n\n<b>[✅ ВЫПЛАЧЕНО]</b>", parse_mode="HTML")
    try:
        await callback.bot.send_message(tx.user_id, f"💳 <b>Ваша заявка на вывод {tx.amount}₽ успешно исполнена!</b>\nДеньги отправлены на ваши реквизиты.", parse_mode="HTML")
    except: pass

@router.callback_query(F.data.startswith("withdraw_internal:"))
async def admin_withdraw_internal(callback: CallbackQuery, session: AsyncSession):
    tx_id = int(callback.data.split(":")[1])
    tx = await session.scalar(select(Transaction).where(Transaction.id == tx_id))
    
    if not tx or tx.status != "PENDING":
        return await callback.answer("Заявка уже обработана.", show_alert=True)
        
    user = await session.scalar(select(User).where(User.user_id == tx.user_id))
    user.balance += tx.amount # Зачисляем на основной баланс VPN
    tx.status = "COMPLETED"
    tx.description = "Возвращено на внутренний баланс админом: " + (tx.description or "")
    await session.commit()
    
    await callback.message.edit_text(callback.message.html_text + "\n\n<b>[🔄 ПЕРЕВЕДЕНО НА ВНУТР. БАЛАНС]</b>", parse_mode="HTML")
    try:
        await callback.bot.send_message(tx.user_id, f"🔄 Администратор перевел вашу заявку ({tx.amount}₽) на <b>основной баланс VPN</b>. Вы можете потратить их на подписку!", parse_mode="HTML")
    except: pass

@router.callback_query(F.data.startswith("withdraw_reject:"))
async def admin_withdraw_reject(callback: CallbackQuery, session: AsyncSession):
    tx_id = int(callback.data.split(":")[1])
    tx = await session.scalar(select(Transaction).where(Transaction.id == tx_id))
    
    if not tx or tx.status != "PENDING":
        return await callback.answer("Заявка уже обработана.", show_alert=True)
        
    user = await session.scalar(select(User).where(User.user_id == tx.user_id))
    user.referral_balance += tx.amount # Возвращаем деньги обратно на реф. баланс
    tx.status = "REJECTED"
    await session.commit()
    
    await callback.message.edit_text(callback.message.html_text + "\n\n<b>[❌ ОТКЛОНЕНО]</b>", parse_mode="HTML")
    try:
        await callback.bot.send_message(tx.user_id, f"❌ Ваша заявка на вывод {tx.amount}₽ была <b>отклонена</b>.\nСредства возвращены на ваш реферальный баланс.", parse_mode="HTML")
    except: pass
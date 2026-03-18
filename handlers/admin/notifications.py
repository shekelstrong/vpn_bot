"""
Обработчики уведомлений для администраторов и пользователей.
- Новый пользователь (с цепочкой рефералов)
- Пополнение баланса/покупка (с распределением бонусов)
- Запрос на вывод средств
"""

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import List, Dict, Optional

from loguru import logger  # <--- ИСПРАВЛЕНО: используем loguru напрямую
from config import settings


def get_user_link(user_id: int, username: Optional[str] = None) -> str:
    """Формирует кликабельную ссылку на пользователя"""
    if username:
        return f"<a href='tg://user?id={user_id}'>@{username}</a>"
    return f"<a href='tg://user?id={user_id}'>{user_id}</a>"


# ==================== УВЕДОМЛЕНИЯ АДМИНИСТРАТОРАМ ====================

async def notify_admin_new_user(
    bot: Bot,
    user_id: int,
    username: Optional[str] = None,
    referrers_chain: Optional[List[Dict]] = None
):
    """
    Уведомление админам о новом пользователе.
    """
    user_link = get_user_link(user_id, username)
    
    referrer_text = "\n👥 <b>Реферальная цепочка:</b>"
    if referrers_chain:
        for ref in referrers_chain:
            ref_link = get_user_link(ref['id'], ref.get('username'))
            referrer_text += f"\nУровень {ref['level']}: {ref_link}"
    else:
        referrer_text += " Нет рефовода"
    
    message = (
        f"🆕 <b>Новый пользователь!</b>\n\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"👤 Профиль: {user_link}\n"
        f"{referrer_text}"
    )
    
    for admin_id in settings.admin_ids_list:
        try:
            await bot.send_message(admin_id, message, parse_mode="HTML")
        except Exception as e:
            logger.warning(f"Failed to notify admin {admin_id}: {e}")


async def notify_admin_payment(
    bot: Bot,
    user_id: int,
    amount_rub: float,
    username: Optional[str] = None,
    method: str = "CryptoBot",
    referrers_bonuses: Optional[List[Dict]] = None
):
    """
    Уведомление админам о пополнении/покупке.
    """
    user_link = get_user_link(user_id, username)
    
    bonus_text = "\n\n💸 <b>Распределение бонусов:</b>"
    if referrers_bonuses:
        for rb in referrers_bonuses:
            r_link = get_user_link(rb['id'], rb.get('username'))
            bonus_text += f"\nУр.{rb['level']} {r_link}: +{rb['bonus']:.2f}₽"
    else:
        bonus_text += " Никому (нет рефоводов)"
    
    message = (
        f"💰 <b>Новое пополнение! ({method})</b>\n\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"👤 Профиль: {user_link}\n"
        f"💵 Сумма: <b>{amount_rub:.2f}₽</b>"
        f"{bonus_text}"
    )
    
    for admin_id in settings.admin_ids_list:
        try:
            await bot.send_message(admin_id, message, parse_mode="HTML")
        except Exception as e:
            logger.warning(f"Failed to notify admin {admin_id}: {e}")


async def notify_admin_withdrawal(
    bot: Bot,
    user_id: int,
    amount: float,
    method: str,
    details: str,
    withdrawal_id: int,
    username: Optional[str] = None
):
    """
    Уведомление админу о заявке на вывод средств.
    """
    user_link = get_user_link(user_id, username)
    
    message = (
        f"⚠️ <b>Заявка на вывод средств!</b>\n\n"
        f"👤 От: {user_link} (<code>{user_id}</code>)\n"
        f"💰 Сумма: <b>{amount:.2f}₽</b>\n"
        f"💳 Способ: <b>{method}</b>\n"
        f"📝 Реквизиты:\n<code>{details}</code>\n\n"
        f"<i>Выберите действие ниже:</i>"
    )
    
    # Кнопки для быстрой обработки заявки админом
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отметить как выплаченное", callback_data=f"withdraw_done:{withdrawal_id}")],
        [InlineKeyboardButton(text="🔄 Вернуть на внутр. баланс VPN", callback_data=f"withdraw_internal:{withdrawal_id}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"withdraw_reject:{withdrawal_id}")]
    ])
    
    for admin_id in settings.admin_ids_list:
        try:
            await bot.send_message(admin_id, message, reply_markup=kb, parse_mode="HTML")
        except Exception as e:
            logger.warning(f"Failed to notify admin {admin_id}: {e}")


# ==================== УВЕДОМЛЕНИЯ РЕФОВОДАМ ====================

async def notify_referrer_new_referral(
    bot: Bot,
    referrer_id: int,
    new_user_id: int,
    level: int,
    new_user_username: Optional[str] = None
):
    """Уведомление рефоводу о регистрации нового реферала"""
    new_user_link = get_user_link(new_user_id, new_user_username)
    
    level_text = f" (Уровень {level})" if level > 1 else ""
    
    message = (
        f"🎉 <b>У вас новый реферал!</b>{level_text}\n\n"
        f"👤 Профиль: {new_user_link}\n"
        f"Теперь вы будете получать процент с его пополнений!"
    )
    
    try:
        await bot.send_message(referrer_id, message, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logger.warning(f"Failed to notify referrer {referrer_id}: {e}")


async def notify_referrer_payment(
    bot: Bot,
    referrer_id: int,
    referral_id: int,
    bonus_amount: float,
    level: int,
    referral_username: Optional[str] = None
):
    """Уведомление рефоводу о получении бонуса с пополнения"""
    ref_link = get_user_link(referral_id, referral_username)
    
    message = (
        f"💸 <b>Вам начислен реферальный бонус!</b>\n\n"
        f"Ваш реферал {level}-го уровня {ref_link} совершил покупку.\n"
        f"🎁 Зачислено на баланс: <b>+{bonus_amount:.2f}₽</b>"
    )
    
    try:
        await bot.send_message(referrer_id, message, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logger.warning(f"Failed to notify referrer {referrer_id}: {e}")


# ==================== УВЕДОМЛЕНИЯ ПОЛЬЗОВАТЕЛЯМ ====================

async def notify_user_purchase(
    bot: Bot,
    user_id: int,
    amount_rub: float,
    duration_days: int = 30,
    is_extension: bool = False
):
    """Уведомление пользователю об успешной покупке/продлении VPN"""
    action = "продлена" if is_extension else "оформлена"
    
    message = (
        f"✅ <b>Оплата {amount_rub:.2f}₽ прошла успешно!</b>\n\n"
        f"Ваша подписка на VPN {action}.\n"
        f"⏳ Добавлено времени: <b>{duration_days} дней</b>\n\n"
        f"Приятного пользования Nemo VPN! 🌊"
    )
    
    try:
        await bot.send_message(user_id, message, parse_mode="HTML")
    except Exception as e:
        logger.warning(f"Failed to notify user {user_id}: {e}")
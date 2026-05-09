"""
Обработчики уведомлений для администраторов и пользователей.
- Новый пользователь (с цепочкой рефералов)
- Пополнение баланса/покупка (с распределением бонусов)
- Запрос на вывод средств
"""

import io
import qrcode
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from typing import List, Dict, Optional

from loguru import logger
from config import settings
from handlers.profile import append_singbox, ROUTE_HAPP


def get_user_link(user_id: int, username: Optional[str] = None) -> str:
    """Формирует кликабельную ссылку на пользователя (только для админов)"""
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


# ==================== УВЕДОМЛЕНИЯ РЕФОВОДАМ (АНОНИМНЫЕ) ====================

async def notify_referrer_new_referral(
    bot: Bot,
    referrer_id: int,
    new_user_id: int,
    level: int,
    new_user_username: Optional[str] = None
):
    """Уведомление рефоводу о регистрации нового реферала (БЕЗ раскрытия личности)"""
    level_text = f" (Уровень {level})" if level > 1 else ""
    
    message = (
        f"🎉 <b>У вас новый реферал!</b>{level_text}\n\n"
        f"Кто-то зарегистрировался по вашей ссылке.\n"
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
    """Уведомление рефоводу о получении бонуса с пополнения (БЕЗ раскрытия личности)"""
    message = (
        f"💸 <b>Вам начислен реферальный бонус!</b>\n\n"
        f"Ваш реферал {level}-го уровня совершил покупку.\n"
        f"🎁 Зачислено на баланс: <b>+{bonus_amount:.2f}₽</b>"
    )
    
    try:
        await bot.send_message(referrer_id, message, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logger.warning(f"Failed to notify referrer {referrer_id}: {e}")


# ==================== УВЕДОМЛЕНИЯ ПОЛЬЗОВАТЕЛЯМ ====================

def generate_qr(data: str) -> BufferedInputFile:
    """Генерация QR-кода в памяти."""
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    bio = io.BytesIO()
    img.save(bio, "PNG")
    bio.seek(0)
    return BufferedInputFile(bio.read(), filename="qr.png")

async def notify_user_purchase(
    bot: Bot,
    user_id: int,
    amount_rub: float,
    duration_days: int = 30,
    is_extension: bool = False,
    marzban_username: Optional[str] = None,
    tier: str = "standard"
):
    """Уведомление пользователю об успешной покупке/продлении VPN с инструкциями"""
    action = "продлена" if is_extension else "оформлена"
    
    subscription_url = ""
    if marzban_username:
        try:
            from services.marzban_api import marzban_service
            marzban_data = await marzban_service.get_user(marzban_username)
            if marzban_data:
                subscription_url = marzban_data.get("subscription_url", "")
                if subscription_url and subscription_url.startswith("/"):
                    base_url = settings.MARZBAN_URL.rstrip("/")
                    subscription_url = f"{base_url}{subscription_url}"
                subscription_url = append_singbox(subscription_url)
        except Exception as e:
            logger.error(f"Ошибка получения ссылки для {user_id}: {e}")
    
    # Текст основной инструкции (общий для всех)
    instruction_base = (
        f"✅ <b>Оплата {amount_rub:.2f}₽ прошла успешно!</b>\n\n"
        f"Ваша подписка на VPN {action}.\n"
        f"⏳ Добавлено времени: <b>{duration_days} дней</b>\n\n"
    )
    
    if subscription_url:
        instruction_base += (
            f"🔗 <b>Ваша ссылка на подписку:</b>\n"
            f"<code>{subscription_url}</code>\n"
            "<i>(Нажмите на ссылку, чтобы скопировать)</i>\n\n"
        )
        
    instruction_base += (
        "📱 <b>Инструкция по подключению:</b>\n"
        "1. Установите приложение для вашего устройства:\n"
        "• <b>iOS / macOS:</b> <a href='https://apps.apple.com/us/app/happ-proxy-utility/id6504287215'>Happ</a>\n"
        "• <b>Android:</b> <a href='https://play.google.com/store/apps/details?id=com.happproxy'>Happ</a>\n"
        "• <b>Windows:</b> <a href='https://github.com/Happ-proxy/happ-desktop/releases/latest/download/setup-Happ.x64.exe'>Happ</a>\n"
        "2. Скопируйте ссылку на подписку (выше).\n"
        "3. Откройте приложение, нажмите <b>«+»</b> и выберите <b>«Import from Clipboard»</b>.\n"
        "4. Нажмите кнопку подключения на главном экране.\n\n"
    )

    if tier == "premium":
        # Дополнение для VIP тарифа — inline-кнопка для маршрутизации
        premium_note = (
            "🚀 <b>Настройка умной маршрутизации (VIP):</b>\n\n"
            "Российские сайты будут работать напрямую от вашего провайдера, "
            "а заблокированные — через VPN. Нажмите кнопку ниже, чтобы применить ключ маршрутизации:\n\n"
            f"📽 <a href='https://t.me/{settings.CHANNEL_USERNAME.lstrip('@')}/56'><b>Видео-инструкция</b></a>\n\n"
            "На уровне нашего сервера для вас включен жесткий БЛОК на посещение РУ-сервисов через VPN, "
            "поэтому они будут работать только напрямую — это делает ваш серфинг невидимым для проверок!"
        )
        final_message = instruction_base + premium_note
    else:
        final_message = instruction_base + "Приятного пользования Nemo VPN! 🌊"

    try:
        # 1. Отправляем основное текстовое сообщение
        await bot.send_message(
            user_id, 
            final_message, 
            parse_mode="HTML", 
            disable_web_page_preview=True
        )
        
        # 2. Для VIP — отправляем inline-кнопку маршрутизации
        if tier == "premium":
            routing_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔑 Импортировать маршрутизацию в Happ", url=ROUTE_HAPP)]
            ])
            await bot.send_message(
                user_id,
                "👆 Нажмите кнопку выше, чтобы автоматически применить маршрутизацию в Happ.",
                reply_markup=routing_keyboard,
                parse_mode="HTML"
            )
        
        # 3. Если удалось получить ссылку, генерируем и отправляем QR-код отдельно
        if subscription_url:
            qr_file = generate_qr(subscription_url)
            await bot.send_photo(
                user_id,
                photo=qr_file,
                caption="Ваш QR-код для быстрого подключения 👆",
                parse_mode="HTML"
            )

    except Exception as e:
        logger.warning(f"Failed to notify user {user_id}: {e}")
"""
Обработчики уведомлений для администраторов и пользователей.
- Новый пользователь (с цепочкой рефералов)
- Пополнение баланса/покупка (с распределением бонусов)
- Запрос на вывод средств
"""

import os
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, BufferedInputFile
from typing import List, Dict, Optional

from loguru import logger
from config import settings


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

async def notify_user_purchase(
    bot: Bot,
    user_id: int,
    amount_rub: float,
    duration_days: int = 30,
    is_extension: bool = False,
    marzban_username: Optional[str] = None,
    tier: str = "standard"
):
    """Уведомление пользователю об успешной покупке/продлении VPN с инструкциями для V2Box"""
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
        except Exception as e:
            logger.error(f"Ошибка получения ссылки для {user_id}: {e}")
    
    qr_file = None
    if subscription_url:
        try:
            import qrcode
            import io
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(subscription_url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            bio = io.BytesIO()
            img.save(bio, "PNG")
            bio.seek(0)
            qr_file = BufferedInputFile(bio.read(), filename="qr.png")
        except Exception as e:
            logger.error(f"Ошибка генерации QR-кода для {user_id}: {e}")
    
    # Текст основной инструкции (общий для всех)
    instruction_base = (
        f"✅ <b>Оплата {amount_rub:.2f}₽ прошла успешно!</b>\n\n"
        f"Ваша подписка на VPN {action}.\n"
        f"⏳ Добавлено времени: <b>{duration_days} дней</b>\n\n"
        f"🔗 <b>Ваша ссылка на подписку:</b>\n"
        f"<code>{subscription_url}</code>\n"
        "<i>(Нажмите на ссылку, чтобы скопировать)</i>\n\n"
        "📱 <b>Инструкция по подключению (V2Box):</b>\n"
        "1. Установите <b>V2Box</b> (<a href='https://apps.apple.com/us/app/v2box-v2ray-client/id6446814690'>iOS</a> / <a href='https://play.google.com/store/apps/details?id=dev.hexasoftware.v2box'>Android</a>)\n"
        "2. В приложении перейдите во вкладку <b>Configs</b>.\n"
        "3. Нажмите <b>«+»</b> → <b>«Import V2ray URL from Clipboard»</b>.\n"
        "4. На главной (Home) нажмите <b>«Slide to Connect»</b>.\n\n"
    )

    if tier == "premium":
        # Дополнение для VIP тарифа
        premium_note = (
            "🚀 <b>Настройка умной маршрутизации (VIP):</b>\n\n"
            "Мы специально не встраиваем обход блокировок в основной ключ, чтобы максимально скрыть работу VPN от систем РКН. "
            "Для корректной работы российских сервисов (Госуслуги, банки) напрямую, а заблокированных (Instagram, X) через VPN, "
            "вам необходимо применить ключ маршрутизации:\n\n"
            "🔑 <b>Ключ маршрутизации:</b>\n"
            "<code>v2box://routes?multi=W3sibGlzdCI6WyJnZW9zaXRlOnJ1IiwiZG9tYWluOnJ1IiwiZG9tYWluOtGA0YQiXSwiaXNFbmFibGUiOnRydWUsIm1hdGNoTW9kZSI6ImRvbWFpbiIsIm5hbWUiOiJyb3V0ZS4zRjFENTdBOS0xRkZELTQ5MkMtOTY2NS1BRTJDNDU4QzE0QUIiLCJyZW1hcmsiOiJEaXJlY3QgUlUiLCJsaXN0SVAiOlsiZ2VvaXA6cnUiLCJnZW9pcDpwcml2YXRlIl0sInR5cGUiOiJJUCIsInRhZyI6ImRpcmVjdCJ9XQ==</code>\n\n"
            "👇 <b>Ниже мы отправили видео-инструкцию, как это сделать за 10 секунд.</b>\n"
            "На уровне нашего сервера для вас включен жесткий БЛОК на посещение РУ-сервисов через VPN, "
            "поэтому они будут работать только напрямую с вашего провайдера — это делает ваш серфинг невидимым для проверок!"
        )
        final_message = instruction_base + premium_note
    else:
        final_message = instruction_base + "Приятного пользования Nemo VPN! 🌊"

    try:
        # 1. Отправляем основное сообщение (фото QR + текст)
        if subscription_url and qr_file:
            await bot.send_photo(
                user_id,
                photo=qr_file,
                caption=final_message,
                parse_mode="HTML"
            )
        else:
            await bot.send_message(user_id, final_message, parse_mode="HTML")
        
        # 2. Для VIP тарифа отправляем видео-инструкцию
        if tier == "premium":
            video_path = "marshrut.mp4"
            if os.path.exists(video_path):
                await bot.send_video(
                    user_id,
                    video=FSInputFile(video_path),
                    caption="🎬 Видео-инструкция по настройке VIP-маршрутизации",
                    parse_mode="HTML"
                )
            else:
                logger.error(f"Файл видео {video_path} не найден!")

    except Exception as e:
        logger.warning(f"Failed to notify user {user_id}: {e}")
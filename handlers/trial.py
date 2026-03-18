"""
Обработчик бесплатного триала.
Выдача 24-часового доступа с лимитом 1GB.
"""
import io
import qrcode
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.types import BufferedInputFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta
from loguru import logger

from database.models import User
from keyboards.inline import get_trial_keyboard, get_main_menu_keyboard
from services.marzban_api import marzban_service
from config import settings, get_db_setting

router = Router()

def generate_qr(data: str) -> BufferedInputFile:
    """Генерация QR-кода в памяти и возврат в виде файла для Telegram."""
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    bio = io.BytesIO()
    img.save(bio, "PNG")
    bio.seek(0)
    return BufferedInputFile(bio.read(), filename="qr.png")

@router.callback_query(F.data == "trial")
@router.message(Command("trial"))
@router.message(F.text.startswith("Бесплатный триал"))
async def show_trial(callback_or_message: types.CallbackQuery | types.Message, session: AsyncSession):
    """Показать информацию о бесплатном триале."""
    
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

    if user.is_trial_used:
        price = await get_db_setting(session, "subscription_price", str(settings.SUBSCRIPTION_PRICE_RUB))
        text = (
            "🎁 <b>Бесплатный триал</b>\n\n"
            "❌ Вы уже использовали пробный период.\n\n"
            "Но не расстраивайтесь! Вы можете оформить подписку\n"
            "и продолжить пользоваться Nemo VPN без ограничений.\n\n"
            f"💳 <b>Стоимость:</b> {price}₽/месяц"
        )
        await message.answer(
            text=text,
            reply_markup=get_main_menu_keyboard()
        )
    else:
        text = (
            "🎁 <b>Бесплатный триал Nemo VPN</b>\n\n"
            "Попробуйте наш VPN-сервис бесплатно в течение 24 часов!\n\n"
            "✨ <b>Что вы получите:</b>\n"
            "▫️ 24 часа безлимитного доступа\n"
            f"▫️ {settings.TRIAL_DATA_LIMIT_GB} GB трафика\n"
            "▫️ Доступ ко всем серверам\n"
            "▫️ Протокол VLESS Reality\n\n"
            "⚠️ Триал доступен только один раз!\n\n"
            "Готовы попробовать? Нажмите «Активировать триал»"
        )
        await message.answer(
            text=text,
            reply_markup=get_trial_keyboard()
        )

@router.callback_query(F.data == "activate_trial")
async def activate_trial(callback: types.CallbackQuery, session: AsyncSession):
    """Активировать бесплатный триал для пользователя."""
    user_id = callback.from_user.id
    await callback.answer("⏳ Активация триала...")

    result = await session.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        await callback.message.answer("❌ Пользователь не найден")
        return

    if user.is_trial_used:
        await callback.message.answer(
            "❌ Вы уже использовали пробный период.\n\n"
            "Оформите подписку для продолжения работы с VPN."
        )
        return

    if user.expire_date and user.expire_date > datetime.utcnow():
        await callback.message.answer(
            "❌ У вас уже есть активная подписка.\n\n"
            "Сначала дождитесь её окончания."
        )
        return

    try:
        marzban_username = f"trial_{user_id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

        marzban_data = await marzban_service.create_user(
            tg_id=user_id,
            username=user.username,
            expire_days=1,
            data_limit_gb=settings.TRIAL_DATA_LIMIT_GB
        )

        user.marzban_username = marzban_username
        user.is_trial_used = True
        user.expire_date = datetime.utcnow() + timedelta(hours=settings.TRIAL_EXPIRE_HOURS)
        await session.commit()

        # Извлекаем прямую VLESS ссылку
        links = marzban_data.get("links", [])
        vless_link = links[0] if links else ""

        if not vless_link:
            await callback.message.answer("❌ Ошибка генерации ключа сервером.")
            return

        # Генерируем QR-код на основе прямой VLESS ссылки
        qr_file = generate_qr(vless_link)

        success_text = (
            "✅ <b>Триал успешно активирован!</b>\n\n"
            "🔑 <b>Ваш ключ (Прямая ссылка):</b>\n"
            f"<code>{vless_link}</code>\n\n"
            "📱 <b>Инструкция для iOS и Android:</b>\n"
            "1. Установите приложение <b>Hiddify</b> из магазина приложений.\n"
            "2. Откройте приложение, нажмите <b>«+»</b> в правом верхнем углу.\n"
            "3. Выберите <b>«Сканировать QR-код»</b> и наведите камеру на код из этого сообщения.\n"
            "4. Нажмите огромную круглую кнопку для подключения.\n\n"
            "💻 <b>Инструкция для Windows и Mac:</b>\n"
            "1. Скачайте Hiddify и откройте его.\n"
            "2. Нажмите на текст ключа выше, чтобы скопировать его.\n"
            "3. В приложении нажмите <b>«+»</b> -> <b>«Добавить из буфера обмена»</b>."
        )

        # Отправляем фото с QR кодом и текстом-инструкцией
        await callback.message.answer_photo(
            photo=qr_file,
            caption=success_text,
            reply_markup=get_main_menu_keyboard()
        )
        
        logger.info(f"Активирован триал для пользователя {user_id}")

    except Exception as e:
        logger.error(f"Ошибка активации триала для {user_id}: {e}")
        await callback.message.answer(
            "❌ Произошла ошибка при активации триала.\n\n"
            "Пожалуйста, попробуйте позже или обратитесь в поддержку."
        )
        
    await callback.answer()
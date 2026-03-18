import io
import qrcode
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.types import BufferedInputFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
from loguru import logger

from database.models import User
from keyboards.inline import get_profile_keyboard
from services.marzban_api import marzban_service
from config import settings

router = Router()

def format_bytes(bytes_value: int) -> str:
    """Конвертировать байты в человекочитаемый формат."""
    if bytes_value is None:
        return "Безлимитно"
    if bytes_value <= 0:
        return "0 Б"
    
    units = ["Б", "КБ", "МБ", "ГБ", "ТБ"]
    unit_index = 0
    value = float(bytes_value)
    
    while value >= 1024 and unit_index < len(units) - 1:
        value /= 1024
        unit_index += 1
        
    return f"{value:.2f} {units[unit_index]}"

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

@router.callback_query(F.data == "profile")
@router.message(Command("profile"))
@router.message(F.text.startswith("Мой профиль"))
async def show_profile(callback_or_message: types.CallbackQuery | types.Message, session: AsyncSession):
    """Показать профиль пользователя со статистикой."""
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

    marzban_data = None
    if user.marzban_username:
        try:
            marzban_data = await marzban_service.get_user(user.marzban_username)
        except Exception as e:
            logger.error(f"Ошибка получения данных из Marzban: {e}")

    profile_text = f"👤 <b>Профиль пользователя</b>\n\n"
    profile_text += f"<b>ID:</b> <code>{user.user_id}</code>\n"
    if user.username:
        profile_text += f"<b>Username:</b> @{user.username}\n"
        
    profile_text += f"\n💰 <b>Баланс:</b> {user.balance:.2f} ₽\n"

    if user.expire_date:
        now = datetime.utcnow()
        days_left = (user.expire_date - now).days
        
        if days_left > 0:
            profile_text += "\n✅ <b>Подписка активна</b>\n"
            profile_text += f"⏳ <b>Истекает:</b> {user.expire_date.strftime('%d.%m.%Y %H:%M')}\n"
            profile_text += f"🗓 <b>Осталось дней:</b> {days_left}\n"
        else:
            profile_text += "\n❌ <b>Подписка истекла</b>\n"
            profile_text += f"⏳ <b>Истекла:</b> {user.expire_date.strftime('%d.%m.%Y %H:%M')}\n"
    else:
        profile_text += "\n❌ <b>Нет активной подписки</b>\n"
        profile_text += "Воспользуйтесь бесплатным триалом или купите подписку!\n"

    # ИСПРАВЛЕНИЕ: Безопасная обработка отсутствия данных
    if marzban_data:
        used_traffic = marzban_data.get("used_traffic", 0)
        data_limit = marzban_data.get("data_limit", 0)
        
        profile_text += f"\n📊 <b>Трафик:</b>\n"
        profile_text += f"📈 Использовано: {format_bytes(used_traffic)}\n"
        
        if data_limit and data_limit > 0:
            remaining = data_limit - used_traffic
            profile_text += f"📉 Осталось: {format_bytes(max(0, remaining))}\n"
            profile_text += f"📊 Лимит: {format_bytes(data_limit)}\n"
        else:
            profile_text += "♾ Безлимитный трафик\n"
    elif user.marzban_username and user.expire_date and user.expire_date < datetime.utcnow():
        profile_text += f"\n📊 <b>Трафик:</b> Данные недоступны (аккаунт архивирован на сервере)\n"

    result = await session.execute(select(User).where(User.referrer_id == user.user_id))
    referrals = result.scalars().all()
    if referrals:
        profile_text += f"\n👥 <b>Рефералы:</b> {len(referrals)}\n"

    has_subscription = user.expire_date and user.expire_date > datetime.utcnow()
    # ИСПРАВЛЕНИЕ: Кнопка "Получить ссылку" показывается только если аккаунт физически есть на сервере
    show_link = has_subscription and user.marzban_username and (marzban_data is not None)

    await message.answer(
        text=profile_text,
        reply_markup=get_profile_keyboard(
            has_subscription=bool(has_subscription),
            show_link=bool(show_link)
        )
    )

@router.callback_query(F.data == "get_vless_link")
async def get_vless_link(callback: types.CallbackQuery, session: AsyncSession):
    """Получить ссылку VLESS для пользователя."""
    user_id = callback.from_user.id
    
    result = await session.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    
    if not user or not user.marzban_username:
        await callback.answer("❌ У вас нет активной подписки", show_alert=True)
        return
        
    try:
        marzban_data = await marzban_service.get_user(user.marzban_username)
        
        # ИСПРАВЛЕНИЕ: Проверка на случай удаления пользователя с сервера
        if not marzban_data:
            await callback.answer("❌ Ваш VPN-аккаунт был заархивирован на сервере. Пожалуйста, оформите новую подписку для создания нового ключа.", show_alert=True)
            return

        subscription_url = marzban_data.get("subscription_url", "")
        if subscription_url and subscription_url.startswith("/"):
            base_url = settings.MARZBAN_URL.rstrip("/")
            subscription_url = f"{base_url}{subscription_url}"
            
        links = marzban_data.get("links", [])
        vless_link = links[0] if links else ""
        
        if subscription_url or vless_link:
            link_text = (
                f"🔗 <b>Умная ссылка (Подписка):</b>\n"
                f"<code>{subscription_url}</code>\n"
                f"<i>(Рекомендуется! Сама обновится при смене IP)</i>\n\n"
                f"🔑 <b>Прямая VLESS-ссылка:</b>\n"
                f"<code>{vless_link}</code>\n\n"
                f"📱 <b>Инструкция для iOS и Android:</b>\n"
                f"1. Откройте приложение <b>Hiddify</b>\n"
                f"2. Нажмите <b>«+»</b> в правом верхнем углу\n"
                f"3. Выберите <b>«Сканировать QR-код»</b> и наведите камеру на код из этого сообщения\n\n"
                f"💻 <b>Инструкция для Windows и Mac:</b>\n"
                f"1. Откройте Hiddify\n"
                f"2. Скопируйте Умную ссылку (нажатием на нее)\n"
                f"3. Нажмите <b>«+»</b> > <b>«Добавить из буфера обмена»</b>\n\n"
                f"⚠️ Не передавайте ссылку третьим лицам!"
            )
            
            if vless_link:
                qr_file = generate_qr(vless_link)
                await callback.message.answer_photo(
                    photo=qr_file,
                    caption=link_text
                )
            else:
                await callback.message.answer(text=link_text)
                
            logger.info(f"Пользователь {user_id} получил ссылку на подписку")
        else:
            await callback.answer("❌ Не удалось получить ссылку", show_alert=True)
            
    except Exception as e:
        logger.error(f"Ошибка получения ссылки для {user_id}: {e}")
        await callback.answer("❌ Произошла ошибка при получении ссылки", show_alert=True)
        
    await callback.answer()
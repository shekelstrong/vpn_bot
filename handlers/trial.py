"""
Обработчик бесплатного триала.
Выдача доступа с настраиваемым сроком и лимитом.
"""
import io
import qrcode
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta
from loguru import logger

from database.models import User
from keyboards.inline import get_main_menu_keyboard
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


async def send_subscription_info(message: types.Message | types.CallbackQuery, vless_link: str):
    """Отправить QR-код и ключ для действующей подписки."""
    if isinstance(message, types.CallbackQuery):
        message = message.message
    
    qr_file = generate_qr(vless_link)
    
    success_text = (
        "✅ <b>Ваша подписка активна!</b>\n\n"
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
    
    await message.answer_photo(
        photo=qr_file,
        caption=success_text,
        reply_markup=get_main_menu_keyboard()
    )


@router.callback_query(F.data == "sub")
@router.message(Command("sub"))
@router.message(F.text.startswith("Подписка"))
@router.message(F.text.startswith("Действующая подписка"))
async def show_trial(callback_or_message: types.CallbackQuery | types.Message, session: AsyncSession):
    """Показать информацию о подписке или предложить активировать триал."""
    
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
    
    has_subscription = user.expire_date and user.expire_date > datetime.utcnow()
    
    if has_subscription:
        if not user.marzban_username:
            try:
                marzban_data = await marzban_service.create_user(
                    tg_id=user_id,
                    username=user.username,
                    expire_days=30,
                    data_limit_gb=0.0
                )
                user.marzban_username = marzban_data.get("username")
                await session.commit()
                logger.info(f"Создан аккаунт Marzban для пользователя {user_id} с существующей подпиской")
            except Exception as e:
                logger.error(f"Ошибка создания аккаунта Marzban для {user_id}: {e}")
                await message.answer(
                    "❌ Ошибка создания VPN-аккаунта.\n\n"
                    "Пожалуйста, обратитесь в поддержку.",
                    reply_markup=get_main_menu_keyboard()
                )
                return
        
        try:
            marzban_data = await marzban_service.get_user(user.marzban_username)
            if not marzban_data:
                marzban_data = await marzban_service.create_user(
                    tg_id=user_id,
                    username=user.username,
                    expire_days=30,
                    data_limit_gb=0.0
                )
                user.marzban_username = marzban_data.get("username")
                await session.commit()
                logger.info(f"Пересоздан аккаунт Marzban для пользователя {user_id}")
            
            links = marzban_data.get("links", [])
            vless_link = links[0] if links else ""
            
            if vless_link:
                await send_subscription_info(message, vless_link)
            else:
                await message.answer(
                    "❌ Не удалось получить ссылку на подписку.\n\n"
                    "Пожалуйста, обратитесь в поддержку.",
                    reply_markup=get_main_menu_keyboard()
                )
        except Exception as e:
            logger.error(f"Ошибка получения ссылки для {user_id}: {e}")
            await message.answer(
                "❌ Произошла ошибка при получении ссылки.\n\n"
                "Пожалуйста, попробуйте позже или обратитесь в поддержку.",
                reply_markup=get_main_menu_keyboard()
            )
    elif user.is_trial_used:
        price = await get_db_setting(session, "subscription_price", str(settings.SUBSCRIPTION_PRICE_RUB))
        text = (
            "📦 <b>Подписка</b>\n\n"
            "❌ У вас нет активной подписки.\n\n"
            "Вы можете оформить подписку\n"
            "и продолжить пользоваться Nemo VPN без ограничений.\n\n"
            f"💳 <b>Стоимость:</b> {price}₽/месяц"
        )
        await message.answer(
            text=text,
            reply_markup=get_main_menu_keyboard()
        )
    else:
        trial_hours = await get_db_setting(session, "trial_hours", "24")
        trial_limit = await get_db_setting(session, "trial_data_limit", "1")
        text = (
            f"🎁 <b>Бесплатный триал Nemo VPN</b>\n\n"
            f"Попробуйте наш VPN-сервис бесплатно в течение {trial_hours} часов!\n\n"
            "✨ <b>Что вы получите:</b>\n"
            f"▫️ {trial_hours} часов доступа\n"
            f"▫️ {trial_limit} GB трафика\n"
            "▫️ Доступ ко всем серверам\n"
            "▫️ Протокол VLESS Reality\n\n"
            "⚠️ Триал доступен только один раз!\n\n"
            "Готовы попробовать? Нажмите «Активировать триал»"
        )
        await message.answer(
            text=text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Активировать триал", callback_data="activate_trial")],
                [InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main")]
            ])
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
        trial_hours = await get_db_setting(session, "trial_hours", "24")
        trial_limit = await get_db_setting(session, "trial_data_limit", "1")
        
        marzban_data = await marzban_service.create_user(
            tg_id=user_id,
            username=user.username,
            expire_hours=int(trial_hours),
            data_limit_gb=int(trial_limit)
        )
        
        user.marzban_username = marzban_data.get("username")
        user.is_trial_used = True
        user.expire_date = datetime.utcnow() + timedelta(hours=int(trial_hours))
        await session.commit()
        
        links = marzban_data.get("links", [])
        vless_link = links[0] if links else ""
        
        if not vless_link:
            await callback.message.answer("❌ Ошибка генерации ключа сервером.")
            return
        
        await send_subscription_info(callback.message, vless_link)
        
        logger.info(f"Активирован триал для пользователя {user_id}")
    
    except Exception as e:
        logger.error(f"Ошибка активации триала для {user_id}: {e}")
        await callback.message.answer(
            "❌ Произошла ошибка при активации триала.\n\n"
            "Пожалуйста, попробуйте позже или обратитесь в поддержку."
        )

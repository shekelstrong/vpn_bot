"""
Обработчик профиля пользователя.

ИЗМЕНЕНИЯ:
1. Все упоминания V2Box убраны, заменены на Happ
2. Добавлены ссылки на Happ для всех платформ (iOS, Android, Windows, macOS, Linux)
3. Убран ключ маршрутизации V2Box, оставлен только Happ
4. Добавлена кнопка перегенерации ключа (regenerate_key)
5. Перегенерация: старая ссылка перестаёт работать, срок и ГБ сохраняются
"""

import io
import os
import qrcode
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta
from loguru import logger
from database.models import User
from keyboards.inline import get_profile_keyboard, get_main_menu_keyboard
from services.marzban_api import marzban_service
from config import settings, get_db_setting

router = Router()

# Ключ маршрутизации Happ (обход белых списков)
ROUTE_HAPP = "happ://routing/add/eyJEbnNIb3N0cyI6e30sIkRvbWFpblN0cmF0ZWd5IjoiSVBJZk5vbk1hdGNoIiwiQmxvY2tTaXRlcyI6W10sIkxhc3RVcGRhdGVkIjoxNzc1OTYwOTM0LCJEb21lc3RpY0ROU0RvbWFpbiI6Imh0dHBzOlwvXC9kbnMuZ29vZ2xlXC9kbnMtcXVlcnkiLCJEb21lc3RpY0ROU1R5cGUiOiJEb1UiLCJVc2VDaHVua0ZpbGVzIjp0cnVlLCJSb3V0ZU9yZGVyIjoiYmxvY2stZGlyZWN0LXByb3h5IiwiUmVtb3RlRE5TVHlwZSI6IkRvVSIsIk5hbWUiOiLQoNCkIiwiR2xvYmFsUHJveHkiOnRydWUsIlJlbW90ZUROU0lwIjoiMS4xLjEuMSIsIkdlb2lwVXJsIjoiaHR0cHM6XC9cL2dpdGh1Yi5jb21cL0xveWFsc29sZGllclwvdjJyYXktcnVsZXMtZGF0XC9yZWxlYXNlc1wvbGF0ZXN0XC9kb3dubG9hZFwvZ2VvaXAuZGF0IiwiRmFrZURucyI6ZmFsc2UsIkRpcmVjdFNpdGVzIjpbImdlb3NpdGU6Y2F0ZWdvcnktcnUiXSwiQmxvY2tJcCI6W10sIkRpcmVjdElwIjpbIjEwLjAuMC4wXC84IiwiMTcyLjE2LjAuMFwvMTIiLCIxOTIuMTY4LjAuMFwvMTYiLCIxNjkuMjU0LjAuMFwvMTYiLCIyMjQuMC4wLjBcLzQiLCIyNTUuMjU1LjI1NS4yNTUiLCJnZW9pcDpydSJdLCJEb21lc3RpY0ROU0lwIjoiOC44LjguOCIsIlJlbW90ZUROU0RvbWFpbiI6Imh0dHBzOlwvXC9jbG91ZGZsYXJlLWRucy5jb21cL2Rucy1xdWVyeSIsIlByb3h5SXAiOltdLCJQcm94eVNpdGVzIjpbXSwiR2Vvc2l0ZVVybCI6Imh0dHBzOlwvXC9naXRodWIuY29tXC9Mb3lhbHNvbGRpZXJcL3YycmF5LXJ1bGVzLWRhdFwvcmVsZWFzZXNcL2xhdGVzdFwvZG93bmxvYWRcL2dlb3NpdGUuZGF0In0="


def format_bytes(bytes_value: int) -> str:
    if bytes_value is None:
        return "Безлимитно"
    if bytes_value <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_index = 0
    value = float(bytes_value)
    while value >= 1024 and unit_index < len(units) - 1:
        value /= 1024.0
        unit_index += 1
    return f"{value:.2f} {units[unit_index]}"

def generate_qr(data: str) -> BufferedInputFile:
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    bio = io.BytesIO()
    img.save(bio, "PNG")
    bio.seek(0)
    return BufferedInputFile(bio.read(), filename="qr.png")


async def send_subscription_info(message: types.Message | types.CallbackQuery, subscription_url: str, vless_link: str = "", user=None):
    """Отправить ссылку для платной подписки."""
    if isinstance(message, types.CallbackQuery):
        message = message.message

    is_premium = False
    if user:
        if hasattr(user, "tier") and getattr(user, "tier") == "premium":
            is_premium = True

    qr_file = generate_qr(subscription_url or vless_link)

    success_text = (
        f"✅ <b>Ваша подписка активна!</b>\n\n"
        f"🔗 <b>Ваша ссылка на подписку:</b>\n"
        f"<code>{subscription_url}</code>\n"
        f"<i>(Нажмите на ссылку, чтобы скопировать)</i>\n\n"
        f"📱 <b>Инструкция по подключению:</b>\n"
        f"1. Установите приложение <b>Happ</b> для вашего устройства:\n"
        f"• <b>iOS / macOS:</b> <a href='https://apps.apple.com/us/app/happ-proxy-utility/id6504287215'>App Store</a>\n"
        f"• <b>Android:</b> <a href='https://play.google.com/store/apps/details?id=com.happproxy'>Google Play</a>\n"
        f"• <b>Windows:</b> <a href='https://github.com/Happ-proxy/happ-desktop/releases/latest/download/setup-Happ.x64.exe'>Скачать</a>\n"
        f"• <b>Linux:</b> <a href='https://github.com/Happ-proxy/happ-desktop/releases/latest'>GitHub Releases</a>\n"
        f"2. Скопируйте ссылку на подписку (выше).\n"
        f"3. Откройте Happ, нажмите <b>«+»</b> и выберите <b>«Import from Clipboard»</b>.\n"
        f"4. Нажмите кнопку подключения на главном экране.\n\n"
    )

    if is_premium:
        premium_note = (
            "💎 <b>Настройка маршрутизации (VIP):</b>\n\n"
            "Мы специально не встраиваем обход блокировок в основной ключ, чтобы максимально скрыть работу VPN. "
            "Для корректной работы российских сервисов напрямую, а заблокированных через VPN, "
            "примените ключ маршрутизации в приложении Happ:\n\n"
            "🔑 <b>Ключ маршрутизации Happ:</b>\n"
            f"<code>{ROUTE_HAPP}</code>\n"
            "📽 <a href='https://t.me/nemo_vpn_official/56'><b>Видео-инструкция</b></a>\n\n"
            "На уровне нашего сервера для вас включен жесткий БЛОК на посещение RU-сервисов через VPN, "
            "поэтому они будут работать только напрямую — это делает ваш серфинг невидимым для проверок!"
        )
        success_text += premium_note
    else:
        success_text += "⚠️ Не передавайте ссылку третьим лицам! Если возникнут проблемы с подключением, напишите в поддержку."

    await message.answer(
        text=success_text,
        disable_web_page_preview=True,
        reply_markup=get_main_menu_keyboard(show_trial=False),
        parse_mode="HTML"
    )

    await message.answer_photo(
        photo=qr_file,
        caption="Ваш QR-код для подключения 👆"
    )


@router.callback_query(F.data == "profile")
@router.message(Command("profile"))
@router.message(F.text.startswith("Мой профиль"))
async def show_profile(callback_or_message: types.CallbackQuery | types.Message, session: AsyncSession):
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
        await message.answer("Пользователь не найден. Нажмите /start")
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
    profile_text += f"🎁 <b>Реферальный баланс:</b> {user.referral_balance:.2f} ₽\n"

    # Показываем раздельные сроки
    now = datetime.utcnow()
    if user.expire_standard and user.expire_standard > now:
        days_std = (user.expire_standard - now).days
        profile_text += f"\n🛡 <b>Стандартный VPN:</b> активен ({days_std} дн., до {user.expire_standard.strftime('%d.%m.%Y')})\n"
    elif user.expire_standard:
        profile_text += f"\n🛡 <b>Стандартный VPN:</b> истёк\n"
    
    if user.expire_premium and user.expire_premium > now:
        days_vip = (user.expire_premium - now).days
        profile_text += f"🚀 <b>VIP (обход списков):</b> активен ({days_vip} дн., до {user.expire_premium.strftime('%d.%m.%Y')})\n"
    elif user.expire_premium:
        profile_text += f"🚀 <b>VIP (обход списков):</b> истёк\n"

    if not user.expire_standard and not user.expire_premium:
        if user.expire_date and user.expire_date > now:
            days_left = (user.expire_date - now).days
            profile_text += f"\n✅ <b>Подписка активна</b> ({days_left} дн.)\n"
        else:
            profile_text += "\n❌ <b>Нет активной подписки</b>\n"

    if marzban_data:
        used_traffic = marzban_data.get("used_traffic", 0)
        data_limit = marzban_data.get("data_limit", 0)
        profile_text += "\n📊 <b>Трафик:</b>\n"
        profile_text += f"Использовано: {format_bytes(used_traffic)}\n"
        if data_limit and data_limit > 0:
            remaining = data_limit - used_traffic
            profile_text += f"Осталось: {format_bytes(max(0, remaining))}\n"
            profile_text += f"Лимит: {format_bytes(data_limit)}\n"
        else:
            profile_text += "Безлимитный трафик\n"

    result = await session.execute(select(User).where(User.referrer_id == user.user_id))
    referrals = result.scalars().all()
    if referrals:
        profile_text += f"\n👥 <b>Рефералы:</b> {len(referrals)}\n"

    has_subscription = user.expire_date and user.expire_date > datetime.utcnow()
    show_link = has_subscription and user.marzban_username and (marzban_data is not None)

    await message.answer(
        text=profile_text,
        reply_markup=get_profile_keyboard(
            has_subscription=bool(has_subscription),
            show_link=bool(show_link)
        ),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "regenerate_key")
async def regenerate_key(callback: types.CallbackQuery, session: AsyncSession):
    """Перегенерировать VPN ключ. Старая ссылка перестаёт работать, срок и ГБ сохраняются."""
    user_id = callback.from_user.id
    result = await session.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()

    if not user or not user.marzban_username:
        await callback.answer("У вас нет активной подписки", show_alert=True)
        return

    try:
        # Проверяем что аккаунт существует
        marzban_data = await marzban_service.get_user(user.marzban_username)
        if not marzban_data:
            await callback.answer("Аккаунт заархивирован. Оформите новую подписку.", show_alert=True)
            return

        # Сохраняем текущие данные
        current_expire = marzban_data.get("expire")
        current_data_limit = marzban_data.get("data_limit")
        current_ip_limit = marzban_data.get("ip_limit", 1)
        current_inbounds = marzban_data.get("inbounds", {})

        # Отзываем подписку — генерирует новый ключ, старый перестаёт работать
        await marzban_service.revoke_user_subscription(user.marzban_username)

        # Восстанавливаем настройки (revoke может сбросить некоторые поля)
        update_data = {
            "expire": current_expire,
            "status": "active",
        }
        if current_data_limit:
            update_data["data_limit"] = current_data_limit
        if current_ip_limit:
            update_data["ip_limit"] = current_ip_limit
        if current_inbounds:
            update_data["inbounds"] = current_inbounds

        await marzban_service._request("PUT", f"/user/{user.marzban_username}", json=update_data)

        # Получаем новую ссылку
        new_data = await marzban_service.get_user(user.marzban_username)
        new_sub_url = new_data.get("subscription_url", "")
        if new_sub_url and new_sub_url.startswith("/"):
            base_url = settings.MARZBAN_URL.rstrip("/")
            new_sub_url = f"{base_url}{new_sub_url}"

        await callback.answer("✅ Ключ перегенерирован!", show_alert=False)

        await callback.message.answer(
            f"🔄 <b>Ключ перегенерирован!</b>\n\n"
            f"Старая ссылка больше не работает.\n\n"
            f"🔗 <b>Новый ключ подписки:</b>\n"
            f"<code>{new_sub_url}</code>\n\n"
            f"Обновите подписку в Happ — старый ключ исчезнет автоматически.\n"
            f"Срок подписки и лимит ГБ сохранены.",
            parse_mode="HTML"
        )
        logger.info(f"Пользователь {user_id} перегенерировал ключ")

    except Exception as e:
        logger.error(f"Ошибка перегенерации ключа для {user_id}: {e}")
        await callback.answer("❌ Ошибка. Попробуйте позже.", show_alert=True)


@router.callback_query(F.data == "get_vless_link")
async def get_vless_link(callback: types.CallbackQuery, session: AsyncSession):
    user_id = callback.from_user.id
    result = await session.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()

    if not user or not user.marzban_username:
        await callback.answer("У вас нет активной подписки", show_alert=True)
        return

    try:
        marzban_data = await marzban_service.get_user(user.marzban_username)
        if not marzban_data:
            await callback.answer("Аккаунт заархивирован. Оформите новую подписку.", show_alert=True)
            return

        subscription_url = marzban_data.get("subscription_url", "")
        if subscription_url and subscription_url.startswith("/"):
            base_url = settings.MARZBAN_URL.rstrip("/")
            subscription_url = f"{base_url}{subscription_url}"

        links = marzban_data.get("links", [])
        vless_link = links[0] if links else ""

        is_premium = hasattr(user, "tier") and getattr(user, "tier") == "premium"

        if subscription_url or vless_link:
            link_text = (
                f"🔗 <b>Ваша ссылка на подписку:</b>\n"
                f"<code>{subscription_url}</code>\n\n"
                f"📱 <b>Инструкция по подключению:</b>\n"
                f"1. Установите <b>Happ</b>:\n"
                f"• <a href='https://apps.apple.com/us/app/happ-proxy-utility/id6504287215'>iOS / macOS</a>\n"
                f"• <a href='https://play.google.com/store/apps/details?id=com.happproxy'>Android</a>\n"
                f"• <a href='https://github.com/Happ-proxy/happ-desktop/releases/latest/download/setup-Happ.x64.exe'>Windows</a>\n"
                f"• <a href='https://github.com/Happ-proxy/happ-desktop/releases/latest'>Linux</a>\n"
                f"2. Скопируйте ссылку выше.\n"
                f"3. Откройте Happ → «+» → <b>Import from Clipboard</b>.\n"
                f"4. Выберите сервер и подключитесь!\n\n"
            )
            if is_premium:
                link_text += (
                    "💎 <b>VIP: Ключ маршрутизации:</b>\n"
                    f"<code>{ROUTE_HAPP}</code>\n\n"
                    "📽 <a href='https://t.me/nemo_vpn_official/56'><b>Видео-инструкция</b></a>"
                )
            else:
                link_text += "⚠️ Не передавайте ссылку третьим лицам!"

            await callback.message.answer(
                text=link_text,
                disable_web_page_preview=True,
                parse_mode="HTML"
            )

            # QR
            qr_file = generate_qr(subscription_url or vless_link)
            await callback.message.answer_photo(
                photo=qr_file,
                caption="QR-код для быстрого подключения 👆"
            )
        else:
            await callback.message.answer("❌ Не удалось получить ссылку. Обратитесь в поддержку.")
    except Exception as e:
        logger.error(f"Ошибка получения ссылки для {user_id}: {e}")
        await callback.message.answer("❌ Ошибка. Попробуйте позже.")

    await callback.answer()


@router.callback_query(F.data == "subscription")
async def show_subscription_callback(callback: types.CallbackQuery, session: AsyncSession):
    await show_subscription(callback, session)


async def show_subscription(callback_or_message, session: AsyncSession):
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
        await message.answer("Пользователь не найден. Нажмите /start")
        return

    has_subscription = user.expire_date and user.expire_date > datetime.utcnow()

    if has_subscription:
        if not user.marzban_username:
            try:
                marzban_data = await marzban_service.create_user(
                    tg_id=user_id, username=user.username, expire_days=30, data_limit_gb=0.0
                )
                user.marzban_username = marzban_data.get("username")
                await session.commit()
            except Exception as e:
                logger.error(f"Ошибка создания аккаунта Marzban для {user_id}: {e}")
                await message.answer("❌ Ошибка создания VPN-аккаунта. Обратитесь в поддержку.")
                return

        try:
            marzban_data = await marzban_service.get_user(user.marzban_username)
            if not marzban_data:
                marzban_data = await marzban_service.create_user(
                    tg_id=user_id, username=user.username, expire_days=30, data_limit_gb=0.0
                )
                user.marzban_username = marzban_data.get("username")
                await session.commit()

            subscription_url = marzban_data.get("subscription_url", "")
            if subscription_url and subscription_url.startswith("/"):
                subscription_url = f"{settings.MARZBAN_URL.rstrip('/')}{subscription_url}"

            links = marzban_data.get("links", [])
            vless_link = links[0] if links else ""

            if subscription_url or vless_link:
                await send_subscription_info(message, subscription_url, vless_link, user)
            else:
                await message.answer("❌ Не удалось получить ссылку. Обратитесь в поддержку.")
        except Exception as e:
            logger.error(f"Ошибка получения ссылки для {user_id}: {e}")
            await message.answer("❌ Ошибка. Попробуйте позже.")
    else:
        price = await get_db_setting(session, "subscription_price", str(settings.SUBSCRIPTION_PRICE_RUB))
        text = (
            "📦 <b>Подписка</b>\n\n"
            "❌ У вас нет активной подписки.\n\n"
            f"💰 <b>Стоимость:</b> от {price} ₽/месяц"
        )
        from keyboards.inline import get_back_keyboard
        await message.answer(text=text, reply_markup=get_back_keyboard(callback_data="buy"), parse_mode="HTML")

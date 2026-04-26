"""
Обработчик команды /start и главного меню.

ИЗМЕНЕНИЯ:
1. Убраны упоминания V2Box
2. Добавлена проверка подписки на канал @nemo_vpn_official при /start
3. Если не подписан — показывается требование подписаться с объяснением бонуса +3 дня
4. Каждый час при нажатии /start — повторная проверка подписки на канал
"""
from aiogram import Router, F, Bot
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, ChatMemberMember, ChatMemberAdministrator, ChatMemberOwner, ChatMemberRestricted
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger
import uuid
from datetime import datetime, timedelta
from database.models import User, PaymentInvoice, GiftCode
from keyboards.inline import get_main_menu_keyboard
from handlers.admin.notifications import notify_admin_new_user, notify_referrer_new_referral

router = Router(name="start_router")

CHANNEL_USERNAME = "@nemo_vpn_official"
CHANNEL_LINK = "https://t.me/nemo_vpn_official"

# Проверка подписки каждый час (для не-подписчиков)
CHECK_INTERVAL = timedelta(hours=1)


async def edit_message_content(
    message_or_callback: Message | CallbackQuery,
    text: str = None,
    caption: str = None,
    reply_markup = None,
    parse_mode: str = None
):
    msg = message_or_callback if isinstance(message_or_callback, Message) else message_or_callback.message
    final_text = text if text is not None else caption
    try:
        has_media = bool(msg.video or msg.animation or msg.photo or msg.document)
        if has_media:
            await msg.edit_caption(caption=final_text, reply_markup=reply_markup, parse_mode=parse_mode)
        else:
            await msg.edit_text(text=final_text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        logger.error(f"Ошибка редактирования сообщения: {e}")

async def generate_marzban_username(user_id: int) -> str:
    return f"tg_{user_id}_{str(uuid.uuid4())[:6]}"


async def check_channel_subscription(bot: Bot, user_id: int) -> bool:
    """Проверить, подписан ли пользователь на канал @nemo_vpn_official."""
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        # Подписан = Member, Administrator, Owner (не Left и не Banned)
        return isinstance(member, (ChatMemberMember, ChatMemberAdministrator, ChatMemberOwner, ChatMemberRestricted))
    except Exception as e:
        logger.warning(f"Не удалось проверить подписку на канал для {user_id}: {e}")
        return False  # Если не удалось проверить — не блокируем


def should_check_subscription(user: User) -> bool:
    """Нужно ли проверять подписку на канал (каждый час для не-подписчиков)."""
    if user.task_channel_sub:
        return False  # Уже подписан, не проверяем
    # Проверяем раз в час
    if user.updated_at and (datetime.utcnow() - user.updated_at) < CHECK_INTERVAL:
        return False  # Проверяли недавно
    return True


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession, bot: Bot):
    user_id = message.from_user.id
    username = message.from_user.username
    command_args = message.text.split()[1] if len(message.text.split()) > 1 else None
    referrer_id = None

    # === ОБРАБОТКА ПОДАРОЧНОГО КОДА ===
    if command_args and command_args.startswith("gift_"):
        gift_code = command_args[5:]
        await process_gift_activation(message, session, bot, user_id, gift_code)
        return

    if command_args and command_args.isdigit():
        ref_id_candidate = int(command_args)
        if ref_id_candidate != user_id:
            referrer_id = ref_id_candidate

    result = await session.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        marzban_username = await generate_marzban_username(user_id)
        actual_referrer = None
        if referrer_id:
            actual_referrer = await session.execute(select(User).where(User.user_id == referrer_id))
            actual_referrer = actual_referrer.scalar_one_or_none()
            if not actual_referrer:
                referrer_id = None

        user = User(
            user_id=user_id,
            username=username,
            marzban_username=marzban_username,
            referrer_id=referrer_id
        )
        session.add(user)
        try:
            await session.commit()
            await session.refresh(user)
            logger.info(f"Создан новый пользователь: {user_id}")
        except IntegrityError:
            await session.rollback()
            result = await session.execute(select(User).where(User.user_id == user_id))
            user = result.scalar_one_or_none()

        # Уведомления админу и рефералу
        if actual_referrer:
            await notify_referrer_new_referral(bot=bot, referrer_id=actual_referrer.user_id, new_user_id=user_id, level=1, new_user_username=username)
            referrers_chain = [{'level': 1, 'id': actual_referrer.user_id, 'username': actual_referrer.username}]
            if actual_referrer.referrer_id:
                ref2 = await session.scalar(select(User).where(User.user_id == actual_referrer.referrer_id))
                if ref2:
                    referrers_chain.append({'level': 2, 'id': ref2.user_id, 'username': ref2.username})
                    if ref2.referrer_id:
                        ref3 = await session.scalar(select(User).where(User.user_id == ref2.referrer_id))
                        if ref3:
                            referrers_chain.append({'level': 3, 'id': ref3.user_id, 'username': ref3.username})
            await notify_admin_new_user(bot=bot, user_id=user_id, username=username, referrers_chain=referrers_chain)
    else:
        needs_commit = False
        if username and user.username != username:
            user.username = username
            needs_commit = True
        if needs_commit:
            await session.commit()

    # === ПРОВЕРКА ПОДПИСКИ НА КАНАЛ ===
    if should_check_subscription(user):
        is_subscribed = await check_channel_subscription(bot, user_id)
        if is_subscribed and not user.task_channel_sub:
            user.task_channel_sub = True
            await session.commit()
        elif not is_subscribed and not user.task_channel_sub:
            # Показываем требование подписки
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            sub_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📢 Подписаться на канал", url=CHANNEL_LINK)],
                [InlineKeyboardButton(text="✅ Я подписался", callback_data="check_channel_sub")]
            ])
            await message.answer(
                "📢 <b>Подпишитесь на наш канал NEMO VPN!</b>\n\n"
                "Будьте в курсе последних событий, обновлений и новостей.\n\n"
                "🎁 <b>Бонус:</b> после первой покупки подписки — "
                "автоматически начислим <b>+3 дня</b> к вашему тарифу!\n\n"
                "Подпишитесь и нажмите «Я подписался» 👇",
                reply_markup=sub_keyboard,
                parse_mode="HTML"
            )
            return

    has_active_subscription = user.expire_date and user.expire_date > datetime.utcnow()
    show_trial = not has_active_subscription and not user.is_trial_used

    welcome_text = (
        f"Привет, <b>{message.from_user.first_name}</b>!\n\n"
        "Добро пожаловать в <b>Nemo VPN</b> — твой надежный VPN-сервис!\n\n"
        "<b>Что я умею:</b>\n"
        "• Выдавать бесплатный триал на 24 часа\n"
        "• Оформлять подписку от 100₽/месяц\n"
        "• Обход белых списков (VIP тариф)\n"
        "• Работать с протоколом VLESS Reality\n"
        "• Реферальная программа — заработок на приглашении друзей\n\n"
        "Выберите действие в меню ниже:"
    )

    try:
        await message.answer_animation(
            animation="CgACAgIAAxkBAAIKvWm-5XOyiFR1PtV-Eg1hVPlkZHY-AAJSnwACcLPwSU27XjIjJrFMOgQ",
            caption=welcome_text,
            reply_markup=get_main_menu_keyboard(show_trial=show_trial),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка при отправке анимации: {e}")
        await message.answer(text=welcome_text, reply_markup=get_main_menu_keyboard(show_trial=show_trial), parse_mode="HTML")

    logger.info(f"Пользователь {user_id} запустил бота")


@router.callback_query(F.data == "check_channel_sub")
async def check_channel_sub_callback(callback: CallbackQuery, session: AsyncSession, bot: Bot):
    """Проверка подписки на канал после нажатия 'Я подписался'."""
    user_id = callback.from_user.id
    is_subscribed = await check_channel_subscription(bot, user_id)

    if is_subscribed:
        result = await session.execute(select(User).where(User.user_id == user_id))
        user = result.scalar_one_or_none()
        if user:
            user.task_channel_sub = True
            await session.commit()

        await callback.answer("✅ Спасибо за подписку! Бонус +3 дня будет начислен после первой покупки.", show_alert=True)

        # Показываем главное меню
        has_active_subscription = user.expire_date and user.expire_date > datetime.utcnow() if user else False
        show_trial = not has_active_subscription and not user.is_trial_used if user else True

        await edit_message_content(
            callback,
            text=f"<b>Главное меню Nemo VPN</b>\n\n"
                 f"✅ Вы подписаны на канал!\n\n"
                 f"Выберите действие:",
            reply_markup=get_main_menu_keyboard(show_trial=show_trial),
            parse_mode="HTML"
        )
    else:
        await callback.answer("❌ Вы ещё не подписались на канал. Подпишитесь и попробуйте снова.", show_alert=True)


async def process_gift_activation(message: Message, session: AsyncSession, bot: Bot, user_id: int, code: str):
    """Активация подарочного кода."""
    from services.marzban_api import marzban_service
    from datetime import timedelta

    result = await session.execute(select(GiftCode).where(GiftCode.code == code))
    gift = result.scalar_one_or_none()

    if not gift:
        await message.answer("❌ Подарочный код не найден.")
        return

    if gift.is_used:
        await message.answer("❌ Этот подарочный код уже был использован.")
        return

    if gift.expires_at and gift.expires_at < datetime.utcnow():
        await message.answer("❌ Срок действия подарочного кода истёк.")
        return

    # Защита от подарка самому себе
    if gift.creator_id == user_id:
        await message.answer("❌ Вы не можете активировать свой собственный подарочный код.")
        return

    # Получаем или создаём пользователя
    result = await session.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        user = User(
            user_id=user_id,
            username=message.from_user.username,
            marzban_username=await generate_marzban_username(user_id)
        )
        session.add(user)
        await session.flush()

    # Активируем подарок
    gift.is_used = True
    gift.used_by = user_id
    gift.used_at = datetime.utcnow()

    now = datetime.utcnow()
    if gift.tier == "premium":
        if user.expire_premium and user.expire_premium > now:
            user.expire_premium = user.expire_premium + timedelta(days=gift.days)
        else:
            user.expire_premium = now + timedelta(days=gift.days)
    else:
        if user.expire_standard and user.expire_standard > now:
            user.expire_standard = user.expire_standard + timedelta(days=gift.days)
        else:
            user.expire_standard = now + timedelta(days=gift.days)
    user.recalculate_expire_date()
    user.tier = gift.tier
    if gift.gb_limit > 0:
        current_gb = user.gb_limit or 0
        user.gb_limit = current_gb + gift.gb_limit

    # Marzban
    try:
        if user.marzban_username:
            mz_data = await marzban_service.get_user(user.marzban_username)
            if mz_data:
                await marzban_service.update_user_full(
                    user.marzban_username, extra_days=gift.days, tier=gift.tier,
                    data_limit_gb=gift.gb_limit
                )
            else:
                new_acc = await marzban_service.create_user(
                    user_id, user.username, gift.days, data_limit_gb=gift.gb_limit, tier=gift.tier
                )
                user.marzban_username = new_acc.get('username')
        else:
            new_acc = await marzban_service.create_user(
                user_id, user.username, gift.days, data_limit_gb=gift.gb_limit, tier=gift.tier
            )
            user.marzban_username = new_acc.get('username')
    except Exception as e:
        logger.error(f"Ошибка Marzban при активации подарка: {e}")

    await session.commit()

    tier_name = "🚀 VIP Обход белых списков" if gift.tier == "premium" else "🛡 Обычный VPN"
    await message.answer(
        f"🎁 <b>Подарочный код активирован!</b>\n\n"
        f"💎 Тариф: <b>{tier_name}</b>\n"
        f"⏳ Добавлено: <b>{gift.days} дней</b>\n"
        f"📶 Трафик: <b>{gift.gb_limit} ГБ</b>\n\n"
        f"Приятного пользования! 🎉",
        parse_mode="HTML"
    )
    
    # Уведомляем дарителя
    try:
        activator_name = message.from_user.username or f"ID: {user_id}"
        await bot.send_message(gift.creator_id,
            f"🎁 <b>Ваш подарок активирован!</b>\n\n"
            f"Пользователь активировал подарочную подписку.\n"
            f"Тариф: {tier_name}\n"
            f"Срок: {gift.days} дней",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.warning(f"Не удалось уведомить дарителя {gift.creator_id}: {e}")
    
    logger.info(f"Подарочный код {code} активирован пользователем {user_id}")


@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery, session: AsyncSession):
    user_id = callback.from_user.id
    result = await session.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    has_active_subscription = user.expire_date and user.expire_date > datetime.utcnow() if user else False
    show_trial = not has_active_subscription and not user.is_trial_used if user else True
    await edit_message_content(
        callback,
        text="<b>Главное меню Nemo VPN</b>\n\nВыберите действие:",
        caption="<b>Главное меню Nemo VPN</b>\n\nВыберите действие:",
        reply_markup=get_main_menu_keyboard(show_trial=show_trial),
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(F.text.startswith("Мой профиль"))
async def show_profile_menu(message: Message, session: AsyncSession):
    user_id = message.from_user.id
    result = await session.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    has_active_subscription = user.expire_date and user.expire_date > datetime.utcnow() if user else False
    show_trial = not has_active_subscription and not user.is_trial_used if user else True
    await message.answer(text="Профиль пользователя\n\nВыберите действие:", reply_markup=get_main_menu_keyboard(show_trial=show_trial))

@router.message(F.text.startswith("Пробная подписка"))
async def show_trial_menu(message: Message, session: AsyncSession):
    user_id = message.from_user.id
    result = await session.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    has_active_subscription = user.expire_date and user.expire_date > datetime.utcnow() if user else False
    show_trial = not has_active_subscription and not user.is_trial_used if user else True
    await message.answer(text="Пробная подписка", reply_markup=get_main_menu_keyboard(show_trial=show_trial))

@router.message(F.text.startswith("Подписка"))
async def show_subscription_menu(message: Message, session: AsyncSession):
    user_id = message.from_user.id
    result = await session.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    has_active_subscription = user.expire_date and user.expire_date > datetime.utcnow() if user else False
    show_trial = not has_active_subscription and not user.is_trial_used if user else True
    await message.answer(text="Подписка", reply_markup=get_main_menu_keyboard(show_trial=show_trial))

@router.message(F.text.startswith("Помощь"))
async def show_help_menu(message: Message, session: AsyncSession):
    user_id = message.from_user.id
    result = await session.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    has_active_subscription = user.expire_date and user.expire_date > datetime.utcnow() if user else False
    show_trial = not has_active_subscription and not user.is_trial_used if user else True
    help_text = "Помощь и поддержка\n\nЕсли у вас возникли вопросы — напишите в техподдержку."
    await message.answer(text=help_text, reply_markup=get_main_menu_keyboard(show_trial=show_trial))

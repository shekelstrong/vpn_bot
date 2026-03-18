"""
Модуль состояний FSM для бота.
"""

from aiogram.fsm.state import State, StatesGroup


class BuySubscription(StatesGroup):
    """Состояния для процесса покупки подписки."""
    selecting_duration = State()
    selecting_payment_method = State()
    waiting_for_payment = State()


class AdminPanel(StatesGroup):
    """Состояния для админ-панели."""
    waiting_for_user_search = State()
    waiting_for_gift_days = State()
    waiting_for_broadcast_message = State()
    waiting_for_reset_trial = State()


class AdminSettings(StatesGroup):
    """Состояния для настроек бота."""
    waiting_for_tariff_value = State()
    waiting_for_referral_value = State()
    waiting_for_trial_value = State()


class Support(StatesGroup):
    """Состояния для техподдержки."""
    waiting_for_message = State()

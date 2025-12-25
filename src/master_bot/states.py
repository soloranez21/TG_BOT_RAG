"""
FSM States for the Master Bot onboarding flow.
"""
from aiogram.fsm.state import State, StatesGroup


class BotSetup(StatesGroup):
    """States for setting up a new personal bot."""

    waiting_for_token = State()
    waiting_for_openai_key = State()

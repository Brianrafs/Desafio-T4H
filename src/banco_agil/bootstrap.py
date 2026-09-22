from pathlib import Path

from banco_agil.config import Settings
from banco_agil.conversation import Conversation
from banco_agil.flow.banking_flow import BankingFlow
from banco_agil.providers.groq import GroqProvider
from banco_agil.repositories.bootstrap import initialize_demo_data
from banco_agil.services.exchange_service import ExchangeService


def create_conversation(settings: Settings) -> Conversation:
    initialize_demo_data(Path(__file__).resolve().parents[2] / "data", settings.data_dir)
    flow = BankingFlow(
        settings.data_dir, ExchangeService(settings.awesome_api_key.get_secret_value())
    )
    provider = GroqProvider(settings.groq_api_key.get_secret_value(), settings.groq_model)
    return Conversation(flow, provider)

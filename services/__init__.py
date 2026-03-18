# Services package
from services.marzban_api import MarzbanService, marzban_service
from services.payment_crypto import CryptoBotService, crypto_bot_service
from services.payment_platega import PlategaService, platega_service

__all__ = [
    "MarzbanService",
    "marzban_service",
    "CryptoBotService",
    "crypto_bot_service",
    "PlategaService",
    "platega_service",
]
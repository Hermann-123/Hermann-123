import logging
import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    TELEGRAM_BOT_TOKEN: str = "7432405570:AAEWO1NdWvFuFTUG_bOwLHWcIi_w0_ssymk"
    ADMIN_ID: int = 5968288964
    API_KEY_ODDS: str = "55a670c7b44c3dcc3c9750e9f5c51da1"
    
    # ⚠️ REMETTEZ LE VRAI ID DE VOTRE CANAL ICI :
    ARCHIVE_CHANNEL_ID: str = "-1003982738017" 
    
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("WallStreet_OS")

CACHE_PORTFOLIO = {}

# NOUVEAU : Mémoire pour sauvegarder votre Bankroll
USER_BANKROLLS = {}

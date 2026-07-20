import logging
import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    TELEGRAM_BOT_TOKEN: str = "8658287331:AAGFmhAcBSoNHw7OvcNT0jaS3t6OsLpTzAw"
    ADMIN_ID: int = 5968288964
    API_KEY_ODDS: str = "55a670c7b44c3dcc3c9750e9f5c51da1"
    
    # REMPLACEZ LE NUMÉRO CI-DESSOUS PAR L'ID DE VOTRE CANAL (N'oubliez pas le -100 au début)
    ARCHIVE_CHANNEL_ID: str = "-1003982738017" 
    
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("WallStreet_OS")

CACHE_PORTFOLIO = {}

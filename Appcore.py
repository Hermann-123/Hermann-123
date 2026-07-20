import logging
import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "7432405570:AAGTHmIi7sfO-xvA58yXksQ7pNCkcH1-sUc")
    ADMIN_ID: int = 5968288964
    API_KEY_ODDS: str = "55a670c7b44c3dcc3c9750e9f5c51da1"
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    SUPABASE_URL: str = "https://wrzikajiigowxnwcvxzu.supabase.co"
    SUPABASE_KEY: str = "sb_publishable_7R5FoErDURQtXRVQL17cEg_ddi1X0UR"

    class Config:
        env_file = ".env"

settings = Settings()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("WallStreet_OS")

CACHE_PORTFOLIO = {}

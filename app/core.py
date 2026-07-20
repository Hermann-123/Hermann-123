import logging
import os
from pydantic_settings import BaseSettings
from supabase import create_client, Client

class Settings(BaseSettings):
    TELEGRAM_BOT_TOKEN: str = "7432405570:AAHS1Kax5wVzccvg4gq-U8yMKQPY8lufyVA"
    ADMIN_ID: int = 5968288964
    API_KEY_ODDS: str = "55a670c7b44c3dcc3c9750e9f5c51da1"
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    SUPABASE_URL: str = "https://wrzikajiigowxnwcvxzu.supabase.co"
    SUPABASE_KEY: str = "sb_publishable_7R5FoErDURQtXRVQL17cEg_ddi1X0UR"

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("WallStreet_OS")

CACHE_PORTFOLIO = {}

# INITIALISATION DE LA BASE DE DONNÉES
try:
    supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    logger.info("✅ Connexion à Supabase établie avec succès.")
except Exception as e:
    supabase = None
    logger.error(f"❌ Impossible de se connecter à Supabase : {e}")

import logging
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Telegram
    TELEGRAM_BOT_TOKEN: str
    ADMIN_ID: int = 5968288964
    
    # API Externes
    API_KEY_ODDS: str
    GROQ_API_KEY: str
    
    # Base de données
    SUPABASE_URL: str
    SUPABASE_KEY: str

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

# Instanciation unique pour toute l'application
settings = Settings()

# Configuration globale des logs professionnels
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("WallStreet_OS")

import os
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("WallStreet_OS")

class Settings:
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "7432405570:AAE7n5uHHju2--gpsFKOCc45UyvltdW8oTU")
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    API_KEY_FOOTBALL: str = os.getenv("API_KEY_FOOTBALL", "99f9731b68429ed4aaf0383cd7ca8cd4")
    ARCHIVE_CHANNEL_ID: str = os.getenv("ARCHIVE_CHANNEL_ID", "-1003982738017")

settings = Settings()

# Mémoire globale
CACHE_PORTFOLIO = {}
SENT_ALERTS = set()

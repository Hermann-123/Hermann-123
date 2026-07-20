from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from app.core import settings, CACHE_PORTFOLIO
from app.models import TicketCategory

bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
dp = Dispatcher()
router = Router()

# LE NOUVEAU CLAVIER PERSISTANT (REPLY KEYBOARD)
def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Top Opportunités"), KeyboardButton(text="⚽ Football")],
            [KeyboardButton(text="🏀 Basket"), KeyboardButton(text="🎾 Tennis")],
            [KeyboardButton(text="💼 Ma Bankroll"), KeyboardButton(text="⚙️ Paramètres")]
        ],
        resize_keyboard=True, persistent=True
    )

def football_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛡️ Ultra Safe (Foot)"), KeyboardButton(text="💎 VIP (Foot)")],
            [KeyboardButton(text="🔥 Value Bets"), KeyboardButton(text="🔙 Retour Principal")]
        ],
        resize_keyboard=True
    )

@router.message(CommandStart())
async def start_cmd(message: Message):
    if message.from_user.id != settings.ADMIN_ID: return
    text = "🏛 **WallStreet OS v8.0**\n\nL'interface Institutionnelle est prête. Utilisez le clavier ci-dessous."
    await message.answer(text, reply_markup=main_menu(), parse_mode="Markdown")

@router.message(F.text == "🔙 Retour Principal")
async def back_main(message: Message):
    await message.answer("Menu principal :", reply_markup=main_menu())

@router.message(F.text == "⚽ Football")
async def open_football(message: Message):
    await message.answer("Catégories Football :", reply_markup=football_menu())

@router.message(F.text == "🛡️ Ultra Safe (Foot)")
async def get_ultra_safe(message: Message):
    tickets = CACHE_PORTFOLIO.get(TicketCategory.ULTRA_SAFE, [])
    if not tickets:
        await message.answer("📭 Aucun ticket Ultra Safe validé par l'IA aujourd'hui.")
        return

    res = "🛡️ **PORTFEUILLE ULTRA SAFE**\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    for t in tickets[:3]:
        res += f"⚽ **{t.match_title}**\n🎯 Pari: `{t.bet_type}` | Cote: `{t.odds}`\n🤖 IA ({t.ai_confidence}%): {t.ai_justification}\n\n"
    await message.answer(res, parse_mode="Markdown")

dp.include_router(router)

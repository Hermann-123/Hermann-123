from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import CommandStart

from app.core import settings, CACHE_PORTFOLIO
from app.models import TicketCategory, SportType

bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
dp = Dispatcher()
router = Router()

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
    text = "🏛 **WallStreet OS v8.0**\n\nBienvenue dans votre Hedge Fund sportif. Le scan de la NBA et du Football est en cours..."
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
    # Filtrer uniquement le football
    soccer_tickets = [t for t in tickets if t.sport == SportType.SOCCER]
    
    if not soccer_tickets:
        await message.answer("📭 Aucun ticket Foot Ultra Safe validé par l'IA aujourd'hui.")
        return

    res = "🛡️ **FOOTBALL : ULTRA SAFE**\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    for t in soccer_tickets[:3]:
        res += f"⚽ **{t.match_title}**\n🎯 Pari: `{t.bet_type}` | Cote: `{t.odds}`\n🤖 IA ({t.ai_confidence}%): {t.ai_justification}\n\n"
    await message.answer(res, parse_mode="Markdown")

@router.message(F.text == "🏀 Basket")
async def get_basket_safe(message: Message):
    # Pour le basket, nous avons classé les opportunités dans SAFE
    tickets = CACHE_PORTFOLIO.get(TicketCategory.SAFE, [])
    basket_tickets = [t for t in tickets if t.sport == SportType.BASKETBALL]
    
    if not basket_tickets:
        await message.answer("📭 Aucun ticket Basket validé par l'IA aujourd'hui.")
        return

    res = "🏀 **BASKETBALL : TICKETS SAFE**\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    for t in basket_tickets[:3]:
        res += f"🇺🇸 **{t.match_title}**\n🎯 Pari: `{t.bet_type}` | Cote: `{t.odds}`\n🤖 IA ({t.ai_confidence}%): {t.ai_justification}\n\n"
    await message.answer(res, parse_mode="Markdown")

dp.include_router(router)

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import CommandStart

from app.core import settings, CACHE_PORTFOLIO
from app.models import TicketCategory

bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
dp = Dispatcher()
router = Router()

def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛡️ Ultra Safe (Foot)"), KeyboardButton(text="💎 VIP (Foot)")],
            [KeyboardButton(text="🔥 Value Bets"), KeyboardButton(text="📊 Top Opportunités")],
            [KeyboardButton(text="🏀 Basket"), KeyboardButton(text="🎾 Tennis")]
        ],
        resize_keyboard=True
    )

@router.message(CommandStart())
async def command_start(message: Message):
    await message.answer("🏛 **WALLSTREET OS** est prêt.\nSélectionnez une catégorie ci-dessous :", reply_markup=main_keyboard())

@router.message(F.text.in_(["🛡️ Ultra Safe (Foot)", "💎 VIP (Foot)", "🔥 Value Bets", "🏀 Basket", "🎾 Tennis", "📊 Top Opportunités"]))
async def handle_keyboard_buttons(message: Message):
    target_cat = TicketCategory(message.text)
    tickets = CACHE_PORTFOLIO.get(target_cat, [])

    if not tickets:  
        await message.answer(f"📭 Aucun ticket disponible pour le moment dans **{message.text}**. L'IA analyse les prochains matchs.")  
        return  

    response = f"🏛 **PORTFEUILLE : {message.text}**\n━━━━━━━━━━━━━━━━━━━━━━\n\n"  
    for t in tickets[:3]:  
        response += f"⚽ **{t.match_title}**\n🎯 Pari : `{t.bet_type}`\n📈 Cote estimée : `{t.odds}`\n🤖 IA ({t.ai_confidence}%) : *{t.ai_justification}*\n\n"  
      
    await message.answer(response, parse_mode="Markdown")

dp.include_router(router)

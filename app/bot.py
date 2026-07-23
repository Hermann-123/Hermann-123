import os
import asyncio
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from app.core import settings
import app.core as core_module
from app.models import TicketCategory

bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
dp = Dispatcher()
router = Router()

class Form(StatesGroup):
    waiting_for_manual_match = State()

def main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌟 Combiné du Jour (Cote 2.2 à 3.5)", callback_data="get_ULTRA_SAFE")],
        [InlineKeyboardButton(text="💎 Combiné VIP (Cote 3.0 à 5.5)", callback_data="get_VIP")],
        [InlineKeyboardButton(text="🚀 Value Bet (Cote 8.0+)", callback_data="get_VALUE")],
        [InlineKeyboardButton(text="📊 Analyse Manuelle", callback_data="manual_analysis")]
    ])

@router.message(CommandStart())
async def command_start(message: Message):
    # 🧹 ÉTAPE 1 : ON DÉTRUIT LE VIEUX CLAVIER COINCÉ EN BAS
    nettoyage = await message.answer("🔄 Mise à jour de l'interface...", reply_markup=ReplyKeyboardRemove())
    await asyncio.sleep(1)
    await nettoyage.delete()

    # 📲 ÉTAPE 2 : ON AFFICHE LE BEAU MENU INLINE
    text = (
        "🏛 **WALLSTREET OS - TRADING SPORTIF**\n\n"
        "⚡️ Flux The Odds API : Connecté\n"
        "⚙️ Moteur Combinatoire : Actif\n"
        "🤖 IA Groq : Connectée\n\n"
        "Sélectionnez le type de combiné que vous souhaitez consulter :"
    )
    await message.answer(text, reply_markup=main_keyboard(), parse_mode="Markdown")

@router.callback_query(F.data.startswith("get_"))
async def fetch_tickets(callback: CallbackQuery):
    category_name = callback.data.replace("get_", "")
    # Correction : "VALUE" au lieu de "VALUE_BET" pour correspondre à ton modèle
    if category_name == "VALUE":
        category_name = "VALUE_BET" if hasattr(TicketCategory, 'VALUE_BET') else "VALUE"
        
    try:
        category = TicketCategory[category_name]
    except KeyError:
        # Tente l'autre nommage au cas où
        category = TicketCategory.VALUE if category_name == "VALUE_BET" else TicketCategory[category_name]

    tickets = core_module.CACHE_PORTFOLIO.get(category, [])

    if not tickets:
        await callback.message.answer(f"📭 Aucun ticket validé pour le moment. L'IA analyse les matchs...")
        await callback.answer()
        return

    t = tickets[-1] 
    
    response = f"🏛 **{t.match_title}**\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    response += f"{t.bet_type}\n\n"
    response += f"📈 **COTE TOTALE : {t.odds}**\n\n"
    response += f"{t.ai_justification}\n"
        
    await callback.message.answer(response, parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data == "manual_analysis")
async def ask_manual(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("📝 Entrez le nom du match à analyser (ex: Real Madrid vs Milan) :")
    await state.set_state(Form.waiting_for_manual_match)
    await callback.answer()

@router.message(Form.waiting_for_manual_match)
async def process_manual(message: Message, state: FSMContext):
    await message.answer("⚙️ Analyse manuelle désactivée temporairement.")
    await state.clear()

dp.include_router(router)

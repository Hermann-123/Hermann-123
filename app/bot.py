import os
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from app.core import settings
import app.core as core_module
from app.models import TicketCategory

# Initialisation du bot Telegram
bot = Bot(token=settings.TELEGRAM_TOKEN)
dp = Dispatcher()
router = Router()

class Form(StatesGroup):
    waiting_for_manual_match = State()

# 🎛️ LE NOUVEAU CLAVIER AVEC LES BONS NOMS (COMBINÉS)
def main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌟 Combiné du Jour (Cote 2.2 à 3.5)", callback_data="get_ULTRA_SAFE")],
        [InlineKeyboardButton(text="💎 Combiné VIP (Cote 3.0 à 5.5)", callback_data="get_VIP")],
        [InlineKeyboardButton(text="🚀 Value Bet (Cote 8.0+)", callback_data="get_VALUE")],
        [InlineKeyboardButton(text="📊 Analyse Manuelle", callback_data="manual_analysis")]
    ])

@router.message(CommandStart())
async def command_start(message: Message):
    text = (
        "🏛 **WALLSTREET OS - TRADING SPORTIF**\n\n"
        "⚡️ Flux The Odds API : Connecté\n"
        "⚙️ Moteur Combinatoire : Actif\n"
        "🤖 IA Groq : Connectée\n\n"
        "Sélectionnez le type de combiné que vous souhaitez consulter aujourd'hui :"
    )
    await message.answer(text, reply_markup=main_keyboard(), parse_mode="Markdown")

@router.callback_query(F.data.startswith("get_"))
async def fetch_tickets(callback: CallbackQuery):
    # Récupération de la catégorie cliquée (ex: ULTRA_SAFE)
    category_name = callback.data.replace("get_", "")
    
    try:
        category = TicketCategory[category_name]
    except KeyError:
        await callback.message.answer("Catégorie introuvable.")
        await callback.answer()
        return

    # On va chercher les combinés dans le cache du serveur
    tickets = core_module.CACHE_PORTFOLIO.get(category, [])

    if not tickets:
        await callback.message.answer(f"📭 Aucun ticket validé pour le moment. L'IA cherche encore la meilleure combinaison.")
        await callback.answer()
        return

    # Affichage du combiné (on prend le plus récent)
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
    await message.answer("⚙️ Analyse manuelle désactivée temporairement pendant le calibrage des combinés automatiques.")
    await state.clear()

dp.include_router(router)

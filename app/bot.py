from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from app.core import settings, CACHE_PORTFOLIO, USER_BANKROLLS
from app.models import TicketCategory, SportType

bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
dp = Dispatcher()
router = Router()

# Création du statut d'attente pour que le bot vous écoute taper votre capital
class BankrollState(StatesGroup):
    waiting_for_amount = State()

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

# ALGORITHME : Formule de Kelly Sécurisée
def calculate_kelly(bankroll: float, odds: float, confidence: float) -> float:
    if bankroll <= 0: return 0.0
    p = confidence / 100.0
    q = 1.0 - p
    b = odds - 1.0
    if b <= 0: return 0.0
    f = (b * p - q) / b
    if f <= 0: return 0.0 # Pari trop risqué, on annule
    
    # Sécurité supplémentaire : On ne mise jamais plus de 5% du capital d'un coup
    f_secure = min(f, 0.05)
    return round(bankroll * f_secure, 2)

def format_ticket(t, bankroll: float) -> str:
    res = f"🏟 **{t.match_title}**\n🎯 Pari: `{t.bet_type}` | Cote: `{t.odds}`\n🤖 IA ({t.ai_confidence}%): {t.ai_justification}\n"
    if bankroll > 0:
        mise = calculate_kelly(bankroll, t.odds, t.ai_confidence)
        if mise > 0:
            res += f"💰 **Mise recommandée:** `{mise}€` *(Kelly)*\n"
        else:
            res += f"⚠️ **Mise:** `0€` *(Risque mathématique trop élevé)*\n"
    res += "\n"
    return res

@router.message(CommandStart())
async def start_cmd(message: Message):
    if message.from_user.id != settings.ADMIN_ID: return
    await message.answer("🏛 **WallStreet OS v10.0**\n\nLe module de Gestion de Bankroll est activé.", reply_markup=main_menu(), parse_mode="Markdown")

@router.message(F.text == "🔙 Retour Principal")
async def back_main(message: Message):
    await message.answer("Menu principal :", reply_markup=main_menu())

@router.message(F.text == "⚽ Football")
async def open_football(message: Message):
    await message.answer("Catégories Football :", reply_markup=football_menu())

# --- GESTION DE LA BANKROLL ---
@router.message(F.text == "💼 Ma Bankroll")
async def bankroll_menu(message: Message, state: FSMContext):
    bk = USER_BANKROLLS.get(message.from_user.id, 0.0)
    await message.answer(
        f"💼 **GESTION DE BANKROLL**\n━━━━━━━━━━━━━━━━━━\n\n"
        f"Votre capital actuel est de : **{bk} €**\n\n"
        f"👉 *Envoyez-moi simplement un montant (ex: 500) par message pour définir votre nouveau capital.*",
        parse_mode="Markdown"
    )
    await state.set_state(BankrollState.waiting_for_amount)

@router.message(BankrollState.waiting_for_amount)
async def update_bankroll(message: Message, state: FSMContext):
    try:
        # On remplace la virgule par un point au cas où
        amount = float(message.text.replace(',', '.'))
        USER_BANKROLLS[message.from_user.id] = amount
        await state.clear()
        await message.answer(f"✅ **Capital mis à jour à {amount} € !**\nMes algorithmes calculeront désormais les mises idéales sur cette base.", parse_mode="Markdown")
    except ValueError:
        await message.answer("❌ Erreur. Veuillez envoyer uniquement un nombre (ex: 150 ou 200.50).")

# --- AFFICHAGE DES TICKETS ---
@router.message(F.text == "🛡️ Ultra Safe (Foot)")
async def get_ultra_safe(message: Message):
    tickets = [t for t in CACHE_PORTFOLIO.get(TicketCategory.ULTRA_SAFE, []) if t.sport == SportType.SOCCER]
    if not tickets: return await message.answer("📭 Aucun ticket Foot Ultra Safe aujourd'hui.")
    bk = USER_BANKROLLS.get(message.from_user.id, 0.0)
    res = f"🛡️ **FOOTBALL : ULTRA SAFE** (Bankroll: {bk}€)\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    for t in tickets[:3]: res += format_ticket(t, bk)
    await message.answer(res, parse_mode="Markdown")

@router.message(F.text == "🏀 Basket")
async def get_basket_safe(message: Message):
    tickets = [t for t in CACHE_PORTFOLIO.get(TicketCategory.SAFE, []) if t.sport == SportType.BASKETBALL]
    if not tickets: return await message.answer("📭 Aucun ticket Basket aujourd'hui.")
    bk = USER_BANKROLLS.get(message.from_user.id, 0.0)
    res = f"🏀 **BASKETBALL : SAFE** (Bankroll: {bk}€)\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    for t in tickets[:3]: res += format_ticket(t, bk)
    await message.answer(res, parse_mode="Markdown")

@router.message(F.text == "🎾 Tennis")
async def get_tennis_safe(message: Message):
    tickets = [t for t in CACHE_PORTFOLIO.get(TicketCategory.SAFE, []) if t.sport == SportType.TENNIS]
    if not tickets: return await message.answer("📭 Aucun ticket Tennis aujourd'hui.")
    bk = USER_BANKROLLS.get(message.from_user.id, 0.0)
    res = f"🎾 **TENNIS : SAFE** (Bankroll: {bk}€)\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    for t in tickets[:3]: res += format_ticket(t, bk)
    await message.answer(res, parse_mode="Markdown")

dp.include_router(router)

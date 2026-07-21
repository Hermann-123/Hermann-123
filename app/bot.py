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

def calculate_kelly(bankroll: float, odds: float, confidence: float) -> float:
    if bankroll <= 0: return 0.0
    p = confidence / 100.0
    q = 1.0 - p
    b = odds - 1.0
    if b <= 0: return 0.0
    f = (b * p - q) / b
    if f <= 0: return 0.0 
    f_secure = min(f, 0.05)
    return round(bankroll * f_secure, 2)

def format_ticket(t, bankroll: float) -> str:
    res = f"🏟 **{t.match_title}**\n🎯 Pari: `{t.bet_type}` | Cote: `{t.odds}`\n🤖 IA ({t.ai_confidence}%): {t.ai_justification}\n"
    if bankroll > 0:
        mise = calculate_kelly(bankroll, t.odds, t.ai_confidence)
        if mise > 0: res += f"💰 **Mise recommandée:** `{mise}€` *(Kelly)*\n"
        else: res += f"⚠️ **Mise:** `0€` *(Risque élevé)*\n"
    res += "\n"
    return res

@router.message(CommandStart())
async def start_cmd(message: Message):
    if message.from_user.id != settings.ADMIN_ID: return
    await message.answer("🏛 **WallStreet OS v11.1 - Unlocked**\n\nLe radar est débridé et tous les boutons sont opérationnels.", reply_markup=main_menu(), parse_mode="Markdown")

@router.message(F.text == "🔙 Retour Principal")
async def back_main(message: Message):
    await message.answer("Menu principal :", reply_markup=main_menu())

@router.message(F.text == "⚽ Football")
async def open_football(message: Message):
    await message.answer("Catégories Football :", reply_markup=football_menu())

@router.message(F.text == "💼 Ma Bankroll")
async def bankroll_menu(message: Message, state: FSMContext):
    bk = USER_BANKROLLS.get(message.from_user.id, 0.0)
    await message.answer(f"💼 **GESTION DE BANKROLL**\nCapital actuel: **{bk} €**\n👉 *Envoyez un montant :*", parse_mode="Markdown")
    await state.set_state(BankrollState.waiting_for_amount)

@router.message(BankrollState.waiting_for_amount)
async def update_bankroll(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(',', '.'))
        USER_BANKROLLS[message.from_user.id] = amount
        await state.clear()
        await message.answer(f"✅ **Capital mis à jour à {amount} € !**", parse_mode="Markdown")
    except ValueError:
        await message.answer("❌ Erreur. Chiffre uniquement.")

# ⚠️ NOUVEAU : CONNEXION DU BOUTON TOP OPPORTUNITÉS
@router.message(F.text == "📊 Top Opportunités")
async def get_top_opps(message: Message):
    bk = USER_BANKROLLS.get(message.from_user.id, 0.0)
    
    foot_tickets = [t for t in CACHE_PORTFOLIO.get(TicketCategory.ULTRA_SAFE, []) if t.sport == SportType.SOCCER]
    basket_tickets = [t for t in CACHE_PORTFOLIO.get(TicketCategory.SAFE, []) if t.sport == SportType.BASKETBALL]
    tennis_tickets = [t for t in CACHE_PORTFOLIO.get(TicketCategory.SAFE, []) if t.sport == SportType.TENNIS]
    
    top_tickets = []
    if foot_tickets: top_tickets.append(foot_tickets[0]) # Prend le meilleur du Foot
    if basket_tickets: top_tickets.append(basket_tickets[0]) # Prend le meilleur du Basket
    if tennis_tickets: top_tickets.append(tennis_tickets[0]) # Prend le meilleur du Tennis
    
    if not top_tickets:
        return await message.answer("📭 Le radar n'a pas encore trouvé de très grandes opportunités pour le moment. Laissez-le scanner !")
        
    res = f"🌟 **TOP OPPORTUNITÉS DU MOMENT**\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    for t in top_tickets:
        res += format_ticket(t, bk)
        
    await message.answer(res, parse_mode="Markdown")

@router.message(F.text == "🛡️ Ultra Safe (Foot)")
async def get_ultra_safe(message: Message):
    tickets = [t for t in CACHE_PORTFOLIO.get(TicketCategory.ULTRA_SAFE, []) if t.sport == SportType.SOCCER]
    if not tickets: return await message.answer("📭 Aucun ticket Foot Ultra Safe.")
    bk = USER_BANKROLLS.get(message.from_user.id, 0.0)
    res = f"🛡️ **FOOTBALL : ULTRA SAFE**\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    for t in tickets[:3]: res += format_ticket(t, bk)
    await message.answer(res, parse_mode="Markdown")

@router.message(F.text == "💎 VIP (Foot)")
async def get_vip(message: Message):
    tickets = [t for t in CACHE_PORTFOLIO.get(TicketCategory.VIP, []) if t.sport == SportType.SOCCER]
    if not tickets: return await message.answer("📭 Aucun ticket Foot VIP aujourd'hui.")
    bk = USER_BANKROLLS.get(message.from_user.id, 0.0)
    res = f"💎 **FOOTBALL : VIP**\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    for t in tickets[:5]: res += format_ticket(t, bk)
    await message.answer(res, parse_mode="Markdown")

@router.message(F.text == "🔥 Value Bets")
async def get_value(message: Message):
    tickets = [t for t in CACHE_PORTFOLIO.get(TicketCategory.VALUE, []) if t.sport == SportType.SOCCER]
    if not tickets: return await message.answer("📭 Aucun ticket Value Bet aujourd'hui.")
    bk = USER_BANKROLLS.get(message.from_user.id, 0.0)
    res = f"🔥 **FOOTBALL : VALUE BETS**\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    for t in tickets[:5]: res += format_ticket(t, bk)
    await message.answer(res, parse_mode="Markdown")

@router.message(F.text == "🏀 Basket")
async def get_basket_safe(message: Message):
    tickets = [t for t in CACHE_PORTFOLIO.get(TicketCategory.SAFE, []) if t.sport == SportType.BASKETBALL]
    if not tickets: return await message.answer("📭 Aucun ticket Basket.")
    bk = USER_BANKROLLS.get(message.from_user.id, 0.0)
    res = f"🏀 **BASKETBALL : SAFE**\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    for t in tickets[:3]: res += format_ticket(t, bk)
    await message.answer(res, parse_mode="Markdown")

@router.message(F.text == "🎾 Tennis")
async def get_tennis_safe(message: Message):
    tickets = [t for t in CACHE_PORTFOLIO.get(TicketCategory.SAFE, []) if t.sport == SportType.TENNIS]
    if not tickets: return await message.answer("📭 Aucun ticket Tennis.")
    bk = USER_BANKROLLS.get(message.from_user.id, 0.0)
    res = f"🎾 **TENNIS : SAFE**\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    for t in tickets[:3]: res += format_ticket(t, bk)
    await message.answer(res, parse_mode="Markdown")

dp.include_router(router)

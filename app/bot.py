from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import app.core as core_module

from app.core import settings, CACHE_PORTFOLIO, USER_BANKROLLS
from app.models import TicketCategory, SportType

bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
dp = Dispatcher()
router = Router()

class BankrollState(StatesGroup): waiting_for_amount = State()

def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Top Opportunités"), KeyboardButton(text="⚽ Football")],
            [KeyboardButton(text="🏀 Basket"), KeyboardButton(text="🎾 Tennis")],
            [KeyboardButton(text="💼 Ma Bankroll"), KeyboardButton(text="⚙️ Paramètres")]
        ], resize_keyboard=True, persistent=True
    )

def football_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛡️ Ultra Safe (Foot)"), KeyboardButton(text="💎 VIP (Foot)")],
            [KeyboardButton(text="🔥 Value Bets"), KeyboardButton(text="🔙 Retour Principal")]
        ], resize_keyboard=True
    )

def calculate_kelly(bankroll: float, odds: float, confidence: float) -> float:
    if bankroll <= 0: return 0.0
    p = confidence / 100.0
    q = 1.0 - p
    b = odds - 1.0
    if b <= 0: return 0.0
    f = (b * p - q) / b
    if f <= 0: return 0.0 
    return round(bankroll * min(f, 0.05), 2)

def format_ticket(t, bankroll: float) -> str:
    res = f"🏟 **{t.match_title}**\n🎯 Pari: `{t.bet_type}` | Cote: `{t.odds}`\n🤖 IA ({t.ai_confidence}%): {t.ai_justification}\n"
    if bankroll > 0:
        mise = calculate_kelly(bankroll, t.odds, t.ai_confidence)
        if mise > 0: res += f"💰 **Mise recommandée:** `{mise}€`\n"
    res += "\n"
    return res

# 🗄️ LA FONCTION PUBLICATION & JUGEMENT
async def archive_ticket_officially(t, bk):
    if not settings.ARCHIVE_CHANNEL_ID or settings.ARCHIVE_CHANNEL_ID == "-100VOTRE_ID_ICI": return
    
    # On ne publie un ticket qu'une seule fois
    if t.match_id in core_module.PENDING_TICKETS: return
    
    mise = 0.0
    if bk > 0: mise = calculate_kelly(bk, t.odds, t.ai_confidence)
    t.recommended_stake = mise

    msg = f"🗄️ **TICKET OFFICIEL | {t.category.value}**\n🏅 Sport: {t.sport.value.upper()}\n🏟️ Match: {t.match_title}\n🎯 Pari: `{t.bet_type}`\n📈 Cote: `{t.odds}`\n"
    if mise > 0: msg += f"💰 Mise Validée: `{mise}€`\n"
    msg += "\n⏳ *En attente du résultat final...*"
    
    try:
        # 1. On envoie le message dans le canal
        sent_msg = await bot.send_message(chat_id=settings.ARCHIVE_CHANNEL_ID, text=msg)
        
        # 2. On retient l'ID de ce message Telegram précis
        t.telegram_msg_id = sent_msg.message_id
        
        # 3. On met le ticket dans la "Salle d'Attente du Juge"
        core_module.PENDING_TICKETS[t.match_id] = t
    except: pass

@router.message(CommandStart())
async def start_cmd(message: Message):
    if message.from_user.id != settings.ADMIN_ID: return
    await message.answer("🏛 **WallStreet OS v13.0**\n\nPlateforme complète déployée : Radar -> Signaux -> Bot -> Registre -> Auto-Vérification des Scores.", reply_markup=main_menu())

@router.message(F.text == "🔙 Retour Principal")
async def back_main(message: Message): await message.answer("Menu principal :", reply_markup=main_menu())

@router.message(F.text == "⚽ Football")
async def open_football(message: Message): await message.answer("Catégories Football :", reply_markup=football_menu())

@router.message(F.text == "💼 Ma Bankroll")
async def bankroll_menu(message: Message, state: FSMContext):
    bk = USER_BANKROLLS.get(message.from_user.id, 0.0)
    await message.answer(f"💼 **BANKROLL**\nCapital: **{bk} €**\n👉 *Envoyez un montant :*", parse_mode="Markdown")
    await state.set_state(BankrollState.waiting_for_amount)

@router.message(BankrollState.waiting_for_amount)
async def update_bankroll(message: Message, state: FSMContext):
    try:
        USER_BANKROLLS[message.from_user.id] = float(message.text.replace(',', '.'))
        await state.clear()
        await message.answer("✅ **Capital mis à jour !**", parse_mode="Markdown")
    except: await message.answer("❌ Chiffre uniquement.")

@router.message(F.text == "📊 Top Opportunités")
async def get_top_opps(message: Message):
    bk = USER_BANKROLLS.get(message.from_user.id, 0.0)
    tickets = []
    if CACHE_PORTFOLIO.get(TicketCategory.ULTRA_SAFE): tickets.append(CACHE_PORTFOLIO[TicketCategory.ULTRA_SAFE][0])
    if CACHE_PORTFOLIO.get(TicketCategory.SAFE): tickets.append(CACHE_PORTFOLIO[TicketCategory.SAFE][0])
    if not tickets: return await message.answer("📭 Pas de top opportunité.")
    res = f"🌟 **TOP OPPORTUNITÉS**\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    for t in tickets:
        res += format_ticket(t, bk)
        await archive_ticket_officially(t, bk)
    await message.answer(res, parse_mode="Markdown")

@router.message(F.text == "🛡️ Ultra Safe (Foot)")
async def get_ultra_safe(message: Message):
    tickets = [t for t in CACHE_PORTFOLIO.get(TicketCategory.ULTRA_SAFE, []) if t.sport == SportType.SOCCER]
    if not tickets: return await message.answer("📭 Aucun ticket Foot Ultra Safe.")
    bk, res = USER_BANKROLLS.get(message.from_user.id, 0.0), f"🛡️ **FOOTBALL : ULTRA SAFE**\n\n"
    for t in tickets[:3]:
        res += format_ticket(t, bk)
        await archive_ticket_officially(t, bk)
    await message.answer(res, parse_mode="Markdown")

@router.message(F.text == "💎 VIP (Foot)")
async def get_vip(message: Message):
    tickets = [t for t in CACHE_PORTFOLIO.get(TicketCategory.VIP, []) if t.sport == SportType.SOCCER]
    if not tickets: return await message.answer("📭 Aucun ticket VIP.")
    bk, res = USER_BANKROLLS.get(message.from_user.id, 0.0), f"💎 **FOOTBALL : VIP**\n\n"
    for t in tickets[:5]:
        res += format_ticket(t, bk)
        await archive_ticket_officially(t, bk)
    await message.answer(res, parse_mode="Markdown")

@router.message(F.text == "🔥 Value Bets")
async def get_value(message: Message):
    tickets = [t for t in CACHE_PORTFOLIO.get(TicketCategory.VALUE, []) if t.sport == SportType.SOCCER]
    if not tickets: return await message.answer("📭 Aucun ticket Value Bet.")
    bk, res = USER_BANKROLLS.get(message.from_user.id, 0.0), f"🔥 **FOOTBALL : VALUE BETS**\n\n"
    for t in tickets[:5]:
        res += format_ticket(t, bk)
        await archive_ticket_officially(t, bk)
    await message.answer(res, parse_mode="Markdown")

@router.message(F.text == "🏀 Basket")
async def get_basket_safe(message: Message):
    tickets = [t for t in CACHE_PORTFOLIO.get(TicketCategory.SAFE, []) if t.sport == SportType.BASKETBALL]
    if not tickets: return await message.answer("📭 Aucun ticket Basket.")
    bk, res = USER_BANKROLLS.get(message.from_user.id, 0.0), f"🏀 **BASKETBALL : SAFE**\n\n"
    for t in tickets[:3]:
        res += format_ticket(t, bk)
        await archive_ticket_officially(t, bk)
    await message.answer(res, parse_mode="Markdown")

@router.message(F.text == "🎾 Tennis")
async def get_tennis_safe(message: Message):
    tickets = [t for t in CACHE_PORTFOLIO.get(TicketCategory.SAFE, []) if t.sport == SportType.TENNIS]
    if not tickets: return await message.answer("📭 Aucun ticket Tennis.")
    bk, res = USER_BANKROLLS.get(message.from_user.id, 0.0), f"🎾 **TENNIS : SAFE**\n\n"
    for t in tickets[:3]:
        res += format_ticket(t, bk)
        await archive_ticket_officially(t, bk)
    await message.answer(res, parse_mode="Markdown")

dp.include_router(router)

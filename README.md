import logging import requests from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

=== CONFIGURATION ===

API_FOOTBALL_KEY = "6f994e4f607eafaaa173859839aefded" TELEGRAM_BOT_TOKEN = "7432405570:AAGqkeFs72lzzVuW_Ea_N8kKLBXBCIc7bc4"

=== LOGGING ===

logging.basicConfig(level=logging.INFO) logger = logging.getLogger(name)

=== GET PRONOSTICS ===

def get_pronostics(sport): pronostics_surs = [f"✅ {sport} sûr #{i+1}" for i in range(3)] pronostics_risques = [f"⚠️ {sport} risqué #{i+1}" for i in range(3)] return pronostics_surs + pronostics_risques

=== HANDLERS ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE): keyboard = [ [InlineKeyboardButton("📅 Pronostics du jour", callback_data="day")], [InlineKeyboardButton("⚽ Football", callback_data="football")], [InlineKeyboardButton("🎾 Tennis", callback_data="tennis")], [InlineKeyboardButton("⚾ Baseball", callback_data="baseball")] ] reply_markup = InlineKeyboardMarkup(keyboard) await update.message.reply_text("Bienvenue dans ton bot de pronostics !", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE): query = update.callback_query await query.answer()

sport_map = {
    "football": "Football",
    "tennis": "Tennis",
    "baseball": "Baseball"
}

if query.data == "day":
    await query.edit_message_text("Choisis un sport:", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("⚽ Football", callback_data="football")],
        [InlineKeyboardButton("🎾 Tennis", callback_data="tennis")],
        [InlineKeyboardButton("⚾ Baseball", callback_data="baseball")]
    ]))
elif query.data in sport_map:
    sport = sport_map[query.data]
    tips = get_pronostics(sport)
    text = f"🎯 *Pronostics du jour - {sport}*\n\n"
    for t in tips[:3]:
        text += f"✅ {t}\n"
    text += "\n"
    for t in tips[3:]:
        text += f"⚠️ {t}\n"
    await query.edit_message_text(text=text, parse_mode="Markdown")

=== MAIN ===

if name == 'main': app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button_handler))

print("✅ Bot en cours d'exécution...")
app.run_polling()


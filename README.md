import logging
import requests
import ccxt
import pandas as pd
import ta  # Pour les indicateurs techniques
from telegram import Bot
from time import sleep

# Configurations
TELEGRAM_TOKEN = "TON_TOKEN_TELEGRAM"
CHAT_ID = "TON_CHAT_ID"
EXCHANGE = ccxt.binance()

PAIR = "BTC/USDT"
TIMEFRAME = "15m"  # Analyse sur 15 minutes
RSI_OVERBOUGHT = 70  # Seuil de surachat
RSI_OVERSOLD = 30  # Seuil de survente

bot = Bot(token=TELEGRAM_TOKEN)

def get_rsi(symbol, timeframe):
    candles = EXCHANGE.fetch_ohlcv(symbol, timeframe)
    df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['rsi'] = ta.momentum.RSIIndicator(df['close']).rsi()
    return df['rsi'].iloc[-1]  # Dernière valeur du RSI

def send_alert(message):
    bot.send_message(chat_id=CHAT_ID, text=message)

def check_trading_signals():
    rsi = get_rsi(PAIR, TIMEFRAME)
    if rsi < RSI_OVERSOLD:
        send_alert(f"🔹 ACHAT RECOMMANDÉ : RSI = {rsi:.2f} (survendu)")
    elif rsi > RSI_OVERBOUGHT:
        send_alert(f"🔻 VENTE RECOMMANDÉE : RSI = {rsi:.2f} (suracheté)")

# Boucle pour vérifier en continu
while True:
    try:
        check_trading_signals()
        sleep(900)  # Vérification toutes les 15 minutes
    except Exception as e:
        logging.error(f"Erreur : {e}")
        sleep(60)

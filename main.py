from keep_alive import keep_alive
keep_alive()

import os
import time
import threading
import requests
from flask import Flask
from random import randint
from telegram.ext import Updater, CommandHandler

# ========== CONFIG ==========
capital = 25.0
risk_percent = 0.05
stop_loss_percent = 0.05
trailing_stop_percent = 0.15

telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
chat_id = os.getenv("TELEGRAM_CHAT_ID")
wallet_address = os.getenv("WALLET_ADDRESS")

print(f"[DEBUG] Token: {telegram_token}")
print(f"[DEBUG] Chat ID: {chat_id}")
print(f"[DEBUG] Wallet: {wallet_address}")

# ========== STATE ==========
active_trade = None
highest_price = 0
paused = False

# ========== SAFETY + SIGNALS ==========
def check_hype_signals(pair):
    return randint(0, 10) > 6

def is_honeypot(address):
    return "rug" in address.lower() or "scam" in address.lower()

def is_whale_confirmation(price_change, liquidity):
    return price_change > 90 and liquidity > 5000

def ai_sentiment_check(title, description):
    bad_words = ["scam", "rug", "exploit", "hack"]
    content = f"{title} {description}".lower()
    return not any(bad in content for bad in bad_words)

# ========== MARKET FUNCTIONS ==========
def scan_market():
    try:
        res = requests.get("https://api.dexscreener.com/latest/dex/pairs", timeout=10)
        return res.json().get("pairs", [])
    except:
        return []

def is_safe_token(pair):
    try:
        if is_honeypot(pair['pairAddress']):
            return False
        if float(pair.get('liquidity', {}).get('usd', 0)) < 5000:
            return False
        return True
    except:
        return False

def buy_token(pair):
    global capital, active_trade, highest_price
    entry_price = float(pair['priceUsd'])
    tokens = (capital * risk_percent) / entry_price
    capital -= tokens * entry_price
    active_trade = {
        'symbol': pair['baseToken']['symbol'],
        'pair': pair['pairAddress'],
        'entry': entry_price,
        'tokens': tokens
    }
    highest_price = entry_price
    send_telegram(f"✅ Bought {tokens:.2f} {active_trade['symbol']} at ${entry_price:.4f}")

def sell_token(price, reason):
    global capital, active_trade
    proceeds = active_trade['tokens'] * price
    capital += proceeds
    send_telegram(f"💰 Sold {active_trade['symbol']} at ${price:.4f} | Reason: {reason} | Capital: ${capital:.2f}")
    active_trade = None

# ========== CORE BOT LOOP ==========
def bot_loop():
    global highest_price, paused, risk_percent
    send_telegram("🤖 Bot is live and scanning...")

    while True:
        if paused:
            time.sleep(10)
            continue

        if not active_trade:
            pairs = scan_market()
            for pair in pairs:
                try:
                    price_change = float(pair['priceChange']['m5'])
                    liquidity = float(pair.get('liquidity', {}).get('usd', 0))
                    title = pair.get('baseToken', {}).get('name', "")
                    desc = pair.get('baseToken', {}).get('symbol', "")

                    if price_change >= 100 or check_hype_signals(pair):
                        if is_safe_token(pair) and is_whale_confirmation(price_change, liquidity):
                            if ai_sentiment_check(title, desc):
                                try:
                                    buy_token(pair)
                                    break
                                except:
                                    send_telegram("⚠️ Trade failed, trying next coin...")
                                    continue
                except:
                    continue
        else:
            try:
                url = f"https://api.dexscreener.com/latest/dex/pairs/{active_trade['pair']}"
                price = float(requests.get(url).json()['pair']['priceUsd'])
            except:
                time.sleep(10)
                continue

            if price > highest_price:
                highest_price = price

            drop = (highest_price - price) / highest_price
            loss = (active_trade['entry'] - price) / active_trade['entry']

            if drop >= trailing_stop_percent:
                sell_token(price, "Trailing Stop Hit")
                risk_percent = max(0.02, risk_percent * 0.95)
            elif loss >= stop_loss_percent:
                sell_token(price, "Stop-Loss Hit")
                risk_percent = max(0.02, risk_percent * 0.95)
            elif price > active_trade['entry'] * 1.5:
                risk_percent = min(0.10, risk_percent * 1.1)

        time.sleep(15)

# ========== TELEGRAM ==========
def send_telegram(message):
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    try:
        requests.post(url, data={"chat_id": chat_id, "text": message})
    except Exception as e:
        print("Telegram Error:", e)

# ========== TELEGRAM COMMANDS ==========
def status(update, context):
    if active_trade:
        update.message.reply_text(f"📈 Trading {active_trade['symbol']} | Entry: ${active_trade['entry']:.4f}")
    else:
        update.message.reply_text("📉 No active trade.")

def capital_status(update, context):
    update.message.reply_text(f"💼 Capital: ${capital:.2f}")

def pause(update, context):
    global paused
    paused = True
    update.message.reply_text("⏸️ Bot Paused.")

def resume(update, context):
    global paused
    paused = False
    update.message.reply_text("▶️ Bot Resumed.")

def last_trade(update, context):
    if active_trade:
        update.message.reply_text(f"🧾 Last trade: {active_trade['symbol']} @ ${active_trade['entry']:.4f}")
    else:
        update.message.reply_text("📜 No recent trade.")

# ========== START ==========
if __name__ == "__main__":
    threading.Thread(target=bot_loop, daemon=True).start()

    updater = Updater(token=telegram_token, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("status", status))
    dp.add_handler(CommandHandler("capital", capital_status))
    dp.add_handler(CommandHandler("pause", pause))
    dp.add_handler(CommandHandler("resume", resume))
    dp.add_handler(CommandHandler("last_trade", last_trade))
    updater.start_polling()
    updater.idle()

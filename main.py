import os
import sqlite3
from datetime import datetime
from flask import Flask, request, jsonify
import requests
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)

# Telegram Konfigürasyonu
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_TELEGRAM_CHAT_ID")

def init_db():
    conn = sqlite3.connect("transactions.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS flow_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT,
            amount REAL,
            usd_value REAL,
            flow_type TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram mesaj hatası: {e}")

@app.route('/arkham-webhook', methods=['POST'])
def arkham_webhook():
    data = request.json
    if not data:
        return jsonify({"status": "no data"}), 400

    try:
        transfers = data.get('transfers', [data]) if isinstance(data, dict) else data
        conn = sqlite3.connect("transactions.db")
        cursor = conn.cursor()
        
        for tx in transfers:
            token = tx.get('tokenSymbol', 'UNKNOWN')
            amount = float(tx.get('unitValue', 0))
            usd_value = float(tx.get('historicalUSD', 0))
            flow_type = tx.get('flowType', 'UNKNOWN').upper()
            
            cursor.execute('''
                INSERT INTO flow_data (token, amount, usd_value, flow_type)
                VALUES (?, ?, ?, ?)
            ''', (token, amount, usd_value, flow_type))

        conn.commit()
        conn.close()
        return jsonify({"status": "success"}), 200
    except Exception as e:
        print(f"Webhook hatası: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def send_hourly_summary():
    conn = sqlite3.connect("transactions.db")
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT token, flow_type, SUM(amount), SUM(usd_value)
        FROM flow_data
        WHERE timestamp >= datetime('now', '-1 hour')
        GROUP BY token, flow_type
    ''')
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        print("Son 1 saatte hareket yaşanmadı, mesaj atılmadı.")
        return

    summary_msg = "⏱️ *Saatlik Borsa Akış Raporu*\n\n"
    tokens = {}
    
    for row in rows:
        token, flow_type, total_amount, total_usd = row
        if token not in tokens:
            tokens[token] = {"INFLOW": 0, "OUTFLOW": 0, "INFLOW_USD": 0, "OUTFLOW_USD": 0}
        tokens[token][flow_type] = total_amount
        tokens[token][f"{flow_type}_USD"] = total_usd

    for t_symbol, data in tokens.items():
        inflow = data.get("INFLOW", 0)
        outflow = data.get("OUTFLOW", 0)
        net_flow = outflow - inflow
        
        summary_msg += f"🔹 *Token:* {t_symbol}\n"
        summary_msg += f"📥 *Giriş (Inflow):* {inflow:,.2f} {t_symbol} (${data.get('INFLOW_USD', 0):,.2f})\n"
        summary_msg += f"📤 *Çıkış (Outflow):* {outflow:,.2f} {t_symbol} (${data.get('OUTFLOW_USD', 0):,.2f})\n"
        
        if net_flow > 0:
            summary_msg += f"📈 *Net Durum:* +{net_flow:,.2f} {t_symbol} Borsadan Çekildi (Net Toplama 🟢)\n\n"
        elif net_flow < 0:
            summary_msg += f"📉 *Net Durum:* {net_flow:,.2f} {t_symbol} Borsaya Yatırıldı (Satış Baskısı 🔴)\n\n"
        else:
            summary_msg += f"⚖️ *Net Durum:* Dengede\n\n"

    send_telegram_message(summary_msg)

scheduler = BackgroundScheduler()
scheduler.add_job(func=send_hourly_summary, trigger="interval", hours=1)
scheduler.start()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

import os
import sqlite3
import requests
from flask import Flask, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

def init_db():
    conn = sqlite3.connect('transactions.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS flow_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT,
            amount REAL,
            flow_type TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def send_hourly_report():
    conn = sqlite3.connect('transactions.db')
    cursor = conn.cursor()
    cursor.execute("SELECT flow_type, SUM(amount) FROM flow_data GROUP BY flow_type")
    results = cursor.fetchall()
    
    inflow = 0.0
    outflow = 0.0
    for flow_type, total in results:
        if flow_type == 'INFLOW':
            inflow = total
        elif flow_type == 'OUTFLOW':
            outflow = total
            
    cursor.execute("DELETE FROM flow_data")
    conn.commit()
    conn.close()
    
    if inflow > 0 or outflow > 0:
        net = outflow - inflow
        msg = (
            f"⏱️ **Saatlik Borsa Akış Raporu**\n\n"
            f"📥 **Giriş (Inflow):** {inflow:,.2f}\n"
            f"📤 **Çıkış (Outflow):** {outflow:,.2f}\n"
            f"📉 **Net Akış:** {net:,.2f}"
        )
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        try:
            requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
        except Exception as e:
            print(f"Telegram mesaj hatası: {e}")

scheduler = BackgroundScheduler()
scheduler.add_job(send_hourly_report, 'interval', hours=1)
scheduler.start()

@app.route('/', methods=['GET'])
def home():
    return "Bot Running", 200

@app.route('/arkham-webhook', methods=['GET', 'POST'])
def arkham_webhook():
    if request.method == 'GET':
        return "OK", 200
        
    data = request.json
    if not data:
        return jsonify({"status": "no data"}), 400

    try:
        transfers = data.get('transfers', [data]) if isinstance(data, dict) else []
        conn = sqlite3.connect("transactions.db")
        cursor = conn.cursor()

        for tx in transfers:
            token = tx.get('tokenSymbol', 'UNKNOWN')
            amount = float(tx.get('unitValue', 0) or 0)
            to_address = str(tx.get('toAddress', '')).lower()
            
            flow_type = 'INFLOW' if any(b in to_address for b in ['exchange', 'binance', 'coinbase', 'kraken']) else 'OUTFLOW'
            
            cursor.execute("INSERT INTO flow_data (token, amount, flow_type) VALUES (?, ?, ?)", 
                           (token, amount, flow_type))
            
        conn.commit()
        conn.close()
        return jsonify({"status": "success"}), 200
    except Exception as e:
        print(f"Webhook hata: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

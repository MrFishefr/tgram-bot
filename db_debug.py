import sqlite3

def check_db():
    conn = sqlite3.connect('trade1_bot.db')
    cur = conn.cursor()
    # Берем 3 случайных скина
    cur.execute("SELECT id, name, url FROM items ORDER BY RANDOM() LIMIT 3")
    rows = cur.fetchall()
    for row in rows:
        print(f"🆔 ID: {row[0]} | 📦 Скин: {row[1]}")
        print(f"🔗 Ссылка в базе: {row[2]}")
        print("-" * 50)
    conn.close()

if __name__ == "__main__":
    check_db()

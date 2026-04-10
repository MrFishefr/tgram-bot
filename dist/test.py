import sqlite3
conn = sqlite3.connect('trade1_bot.db')
cur = conn.cursor()
cur.execute("SELECT name, url FROM items LIMIT 5")
for row in cur.fetchall():
    print(f"📦 {row[0]} | 🔗 {row[1]}")
conn.close()
import sqlite3

def check_real_count():
    conn = sqlite3.connect('trade1_bot.db')
    cur = conn.cursor()
    
    # 1. Получаем общее количество
    cur.execute("SELECT COUNT(*) FROM items")
    total = cur.fetchone()[0]
    
    # 2. Получаем все названия
    cur.execute("SELECT name FROM items ORDER BY id")
    all_items = cur.fetchall()
    
    print(f" Итого в базе: {total} предметов")
    print("-" * 30)
    for i, item in enumerate(all_items, 1):
        print(f"{i}. {item[0]}")
    
    conn.close()

if __name__ == "__main__":
    check_real_count()

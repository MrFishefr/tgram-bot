import sqlite3
conn = sqlite3.connect('trade1_bot.db')
cur = conn.cursor()
# Удаляем тебя из списка юзеров, чтобы ты стал "чистым"
cur.execute("DELETE FROM users WHERE user_id = 7639303686") # Вставь свой ID из бота
conn.commit()
conn.close()
print("🧹 Твой профиль удален. Теперь ты для бота - новый юзер без подписки.")


cur.execute("UPDATE promo_keys SET is_used = 0 WHERE key_code = 'sigmakillerlegenda1227'")
conn.commit()

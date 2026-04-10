import aiosqlite
import asyncio
import random
import string
from datetime import datetime, timedelta
from cachetools import TTLCache


import os

# Получаем путь к текущей папке бота (универсально для всех систем)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "trade1_bot.db")


# 1. КОНСТАНТЫ И КЭШ (в самом верху)
DB_NAME = "trade1_bot.db"
sub_cache = TTLCache(maxsize=1000, ttl=600)
days_cache = TTLCache(maxsize=1000, ttl=300) # Кэш дней на 5 минут
db_conn = None
items_cache = {}

async def get_db():
    global db_conn
    if db_conn is None:
        import aiosqlite
        # Используем DB_PATH, который ты определил через os.path.join (это надежнее для Linux)
        db_conn = await aiosqlite.connect(DB_PATH)
        
        # ВКЛЮЧАЕМ WAL: Чтение не мешает записи
        await db_conn.execute("PRAGMA journal_mode=WAL")
        await db_conn.execute("PRAGMA synchronous=NORMAL")
        
        # ИСПРАВЛЕНО: Было await db.execute, стало await db_conn.execute
        await db_conn.execute("PRAGMA cache_size=-10000;")
        
        # Ждать 5 секунд, если база занята
        await db_conn.execute("PRAGMA busy_timeout=5000")
        print("🚀 БАЗА В ТУРБО-РЕЖИМЕ (WAL)")
    return db_conn


async def migrate_db():
    db = await get_db()
    # Проверяем, есть ли уже новые колонки, чтобы не вылетала ошибка
    try:
        await db.execute("ALTER TABLE promo_keys ADD COLUMN max_activations INTEGER DEFAULT 1")
        await db.execute("ALTER TABLE promo_keys ADD COLUMN current_activations INTEGER DEFAULT 0")
        # Удаляем старую колонку is_used, если она не нужна (опционально)
        # await db.execute("ALTER TABLE promo_keys DROP COLUMN is_used") 
        await db.commit()
        print("✅ База данных успешно обновлена")
    except:
        # Если колонки уже есть, sqlite выдаст ошибку, просто игнорируем её
        pass

async def init_db():
    """Создаем таблицы через общее соединение"""
    db = await get_db() 
    
    try:
        # Стартуем транзакцию вручную
        await db.execute("BEGIN") 
        
        # 1. ТАБЛИЦА ЮЗЕРОВ
        await db.execute('''CREATE TABLE IF NOT EXISTS users 
            (user_id INTEGER PRIMARY KEY, 
             sub_end_date TEXT, 
             is_active INTEGER DEFAULT 0)''')

        # 2. ТАБЛИЦА СКИДОК
        await db.execute('''CREATE TABLE IF NOT EXISTS discount_codes 
            (code TEXT PRIMARY KEY, percent INTEGER)''')
        
        # 3. ТАБЛИЦА ИСТОРИИ ЦЕН
        await db.execute('''CREATE TABLE IF NOT EXISTS price_history 
            (item_id INTEGER, price REAL, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        await db.execute("CREATE INDEX IF NOT EXISTS idx_price_history ON price_history (item_id, timestamp)")

        # 4. ТАБЛИЦА СКИНОВ
        await db.execute('''CREATE TABLE IF NOT EXISTS items 
            (id INTEGER PRIMARY KEY AUTOINCREMENT, 
             name TEXT UNIQUE, 
             url TEXT)''')
        await db.execute("CREATE INDEX IF NOT EXISTS idx_items_name ON items (name)")


        await db.execute('''CREATE TABLE IF NOT EXISTS activated_log 
                    (user_id INTEGER, key_code TEXT, PRIMARY KEY(user_id, key_code))''')
                
        # 5. ТАБЛИЦА МОНИТОРИНГА
        await db.execute('''CREATE TABLE IF NOT EXISTS monitoring 
            (id INTEGER PRIMARY KEY AUTOINCREMENT, 
             user_id INTEGER, 
             item_id INTEGER, 
             item_name TEXT,
             threshold_down REAL, 
             threshold_up REAL, 
             last_price REAL,
             interval_min INTEGER DEFAULT 0,
             next_check TEXT)''')    
        
        # Индекс для мониторинга (теперь внутри блока try с правильным отступом)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_monitoring_check ON monitoring (next_check)")

        # 6. ТАБЛИЦА ПРОМОКОДОВ (КЛЮЧЕЙ)
        await db.execute('''CREATE TABLE IF NOT EXISTS promo_keys 
            (key_code TEXT PRIMARY KEY, 
             days INTEGER,
             max_activations INTEGER DEFAULT 1,
             current_activations INTEGER DEFAULT 0)''')
        
        # Фиксируем изменения
        await db.commit() 
        print("✅ База проинициализирована и готова к работе")
        
    except Exception as e:
        await db.rollback() 
        print(f"❌ Критическая ошибка при инициализации БД: {e}")
        raise e

# --- ОПТИМИЗИРОВАННЫЕ ФУНКЦИИ ---

async def get_discount(code):
    db = await get_db()
    # Используем fetchone() напрямую для экономии ресурсов
    async with db.execute("SELECT percent FROM discount_codes WHERE code = ?", (code,)) as cursor:
        row = await cursor.fetchone()
        return row[0] if row else 0
    
async def add_discount_code(code, percent):
    db = await get_db()
    await db.execute("INSERT OR REPLACE INTO discount_codes (code, percent) VALUES (?, ?)", (code, percent))
    await db.commit()

async def add_item_to_base(name, url):
    db = await get_db()
    # Добавляем try, чтобы except заработал
    try:
        # Используем INSERT OR IGNORE для избежания ошибок UNIQUE
        await db.execute("INSERT OR IGNORE INTO items (name, url) VALUES (?, ?)", (name, url))
        await db.commit()
    except Exception as e:
        print(f"❌ Ошибка добавления скина '{name}': {e}")


async def clear_old_history(days=7):
    db = await get_db()
    # Удаляем историю цен старше 7 дней, чтобы база не раздувалась
    await db.execute("DELETE FROM price_history WHERE timestamp <= datetime('now', ?)", (f'-{days} days',))
    await db.commit()
    await db.execute("VACUUM") # Сжимает файл базы после удаления


async def get_market_tops(limit=5):
    db = await get_db()
    # SQL-запрос для вычисления лидеров роста и падения
    sql = """
        SELECT i.name, h1.price as current_p, h2.price as old_p, 
        ((h1.price - h2.price) / h2.price * 100) as percent
        FROM price_history h1
        JOIN items i ON h1.item_id = i.id
        JOIN price_history h2 ON h1.item_id = h2.item_id
        WHERE h1.timestamp >= datetime('now', '-5 minutes')
        AND h2.timestamp <= datetime('now', '-1 hour')
        AND h2.timestamp >= datetime('now', '-70 minutes')
        GROUP BY i.id
        ORDER BY percent DESC
    """
    async with db.execute(sql) as cursor:
        all_data = await cursor.fetchall()
        
        # Лидеры роста (первые 5) и лидеры падения (последние 5)
        gainers = all_data[:limit]
        losers = all_data[-limit:][::-1] # Переворачиваем, чтобы самые упавшие были сверху
        
        return gainers, losers

async def get_user_monitoring(user_id):
    db = await get_db()
    # Берем ID записи, имя, пороги и интервал
    sql = "SELECT id, item_name, threshold_down, threshold_up, interval_min FROM monitoring WHERE user_id = ?"
    async with db.execute(sql, (user_id,)) as cursor:
        return await cursor.fetchall()


# --- СИСТЕМА ПОДПИСОК (ПРОДОЛЖЕНИЕ) ---

async def check_subscription(user_id):
    """Умная проверка подписки (Кэш + Единая БД)"""
    now = datetime.now()

    if user_id in sub_cache:
        return sub_cache[user_id] > now

    db = await get_db()
    async with db.execute("SELECT sub_end_date, is_active FROM users WHERE user_id = ?", (user_id,)) as cursor:
        row = await cursor.fetchone()
        
        if row and row[1] == 1:
            try:
                end_date = datetime.fromisoformat(row[0])
                if end_date > now:
                    sub_cache[user_id] = end_date
                    return True
            except Exception:
                return False
        return False

async def get_user_sub_days(user_id):
    """Сверхбыстрый возврат дней из кэша или базы"""
    now = datetime.now()
    
    # 1. СМОТРИМ В ПАМЯТЬ (Это мгновенно)
    if user_id in days_cache:
        return days_cache[user_id]

    # 2. ИДЕМ В БАЗУ (Если в памяти нет)
    db = await get_db()
    async with db.execute("SELECT sub_end_date FROM users WHERE user_id = ?", (user_id,)) as cursor:
        row = await cursor.fetchone()
        days = 0
        if row and row[0]:
            try:
                end_date = datetime.fromisoformat(row[0])
                if end_date > now:
                    delta = end_date - now
                    days = delta.days + 1
            except: pass
        
        # ЗАПОМИНАЕМ В КЭШ
        days_cache[user_id] = days
        return days

# --- СИСТЕМА ПРОМОКОДОВ (ЗАВЕРШЕННАЯ) ---

async def use_promo_key(user_id, key_code):
    """Проверяет ключ и ДОБАВЛЯЕТ время к подписке (многоразовые ключи)"""
    db = await get_db()
    
    # 1. Получаем данные ключа
    async with db.execute(
        "SELECT days, max_activations, current_activations FROM promo_keys WHERE key_code = ?", 
        (key_code,)
    ) as cursor:
        row = await cursor.fetchone()
        
    if not row:
        return None  # Ключ не существует
    
    days_to_add, max_act, curr_act = row
    
    # 2. Проверяем, остались ли свободные активации
    if curr_act >= max_act:
        return "limit_exceeded" 

    # 3. Увеличиваем счетчик активаций
    await db.execute(
        "UPDATE promo_keys SET current_activations = current_activations + 1 WHERE key_code = ?", 
        (key_code,)
    )

    # 4. Рассчитываем время (твоя логика из PDF)
    async with db.execute("SELECT sub_end_date FROM users WHERE user_id = ?", (user_id,)) as cursor:
        user_row = await cursor.fetchone()
    
    now = datetime.now()
    if user_row and user_row[0]:
        try:
            current_end = datetime.fromisoformat(user_row[0])
            start_from = current_end if current_end > now else now
        except:
            start_from = now
    else:
        start_from = now
        
    new_date = start_from + timedelta(days=days_to_add)

    # 5. Обновляем пользователя
    await db.execute('''INSERT OR REPLACE INTO users (user_id, sub_end_date, is_active) 
                        VALUES (?, ?, 1)''', (user_id, new_date.isoformat()))
    
    await db.commit()

    # Очистка кэша (чтобы бот сразу увидел новую дату)
    sub_cache.pop(user_id, None)
    days_cache.pop(user_id, None)
        
    return days_to_add

    # 4. СОХРАНЯЕМ В БАЗУ (Вот этого не хватало!)
    await db.execute('''INSERT OR REPLACE INTO users (user_id, sub_end_date, is_active) 
                        VALUES (?, ?, 1)''', (user_id, new_date.isoformat()))
    await db.commit()

    # 🔥 Очищаем кэш, чтобы бот увидел новую дату сразу
    if user_id in sub_cache:
        del sub_cache[user_id]
        
    return days_to_add

# --- АНАЛИТИКА ЦЕН (ТУРБО-ВЕРСИЯ) ---

async def save_price(item_id, price):
    """Сохраняет цену через глобальное соединение"""
    db = await get_db()
    await db.execute("INSERT INTO price_history (item_id, price) VALUES (?, ?)", (item_id, price))
    await db.commit()

async def get_price_hour_ago(item_id):
    """Ищет цену час назад мгновенно"""
    db = await get_db()
    query = """SELECT price FROM price_history 
               WHERE item_id = ? AND timestamp <= datetime('now', '-1 hour') 
               ORDER BY timestamp DESC LIMIT 1"""
    async with db.execute(query, (item_id,)) as cursor:
        row = await cursor.fetchone()
        return row[0] if row else None


    await db.execute('''INSERT OR REPLACE INTO users (user_id, sub_end_date, is_active) 
                        VALUES (?, ?, 1)''', (user_id, new_date.isoformat()))
    await db.commit()

    # 🔥 Сбрасываем кэш, чтобы профиль обновился МГНОВЕННО
    if user_id in sub_cache:
        del sub_cache[user_id]
        
    return days_to_add

# --- ГЕНЕРАЦИЯ КЛЮЧЕЙ ---

async def create_random_key(days, max_act=1):
    """Генерирует ключ с заданным количеством активаций"""
    chars = string.ascii_uppercase + string.digits
    key_code = '-'.join(''.join(random.choice(chars) for _ in range(4)) for _ in range(4))
    
    db = await get_db()
    await db.execute(
        "INSERT INTO promo_keys (key_code, days, max_activations, current_activations) VALUES (?, ?, ?, 0)", 
        (key_code, days, max_act)
    )
    await db.commit()
    return key_code

# --- СУПЕР-БЫСТРАЯ АНАЛИТИКА ЦЕН ---

async def save_price(item_id, price):
    """Пишет цену без лишних задержек"""
    db = await get_db()
    await db.execute("INSERT INTO price_history (item_id, price) VALUES (?, ?)", (item_id, price))
    await db.commit()

async def get_price_hour_ago(item_id):
    """Ищет историю мгновенно по индексу"""
    db = await get_db()
    # Оптимизированный запрос: ищем самую свежую цену, которая старше 1 часа
    query = """SELECT price FROM price_history 
               WHERE item_id = ? AND timestamp <= datetime('now', '-1 hour') 
               ORDER BY timestamp DESC LIMIT 1"""
    async with db.execute(query, (item_id,)) as cursor:
        row = await cursor.fetchone()
        # ИСПРАВЛЕНО: row — это кортеж (8.15,), поэтому берем row[0]
        # Если цен нет, возвращаем None без ошибки
        return row[0] if row else None

async def get_price_history_24h(item_id):
    db = await get_db()
    # Берем цену и время за последние 24 часа (с учетом МСК +3 часа)
    sql = """
        SELECT price, timestamp FROM price_history 
        WHERE item_id = ? AND timestamp >= datetime('now', '+3 hours', '-24 hours')
        ORDER BY timestamp ASC
    """
    async with db.execute(sql, (item_id,)) as cursor:
        rows = await cursor.fetchall()
        # Возвращаем список кортежей (цена, время)
        return rows
    

async def load_items_to_cache():
    """Выгружает все скины из БД в оперативную память для мгновенного поиска"""
    global items_cache
    db = await get_db()
    
    # Берем ID, оригинальное имя и URL
    async with db.execute("SELECT id, name, url FROM items") as cursor:
        rows = await cursor.fetchall()
        # Сохраняем в словарь: ключ — имя в нижнем регистре (для поиска), значение — кортеж данных
        items_cache = {row[1].lower().replace('"', ''): (row[0], row[1], row[2]) for row in rows}
    
    print(f"🧠 КЭШ ЗАПОЛНЕН: {len(items_cache)} скинов загружено в память.")

    
    

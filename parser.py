import aiohttp
import asyncio
import orjson  # Импортируем сверхбыстрый парсер
from urllib.parse import quote
from cachetools import TTLCache

# Хранилище в памяти (КЭШ) на 30 секунд
price_cache = TTLCache(maxsize=1000, ttl=30)

_session = None

async def get_session():
    global _session
    if _session is None or _session.closed:
        import aiohttp
        import orjson
        
        # 1. Настройка коннектора (Ускоряем сеть)
        # limit=100 — позволяет делать много запросов сразу
        # ssl=False — не тратим время на проверку сертификатов (дает +30% к скорости)
        connector = aiohttp.TCPConnector(limit=100, ttl_dns_cache=300, ssl=False)
        
        # 2. Настройка тайм-аутов (Чтобы бот не "висел" на плохих запросах)
        timeout = aiohttp.ClientTimeout(total=15, connect=5, sock_read=10)
        
        # 3. Заголовки (Чтобы сайт не забанил как бота)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://standoff-2.com'
        }
        
        # 4. Создаем сессию с поддержкой orjson
        _session = aiohttp.ClientSession(
            connector=connector, 
            timeout=timeout, 
            headers=headers,
            json_serialize=orjson.dumps # Глобально ускоряет работу с JSON
        )
        
    return _session

async def get_actual_price(skin_name):
    if skin_name in price_cache:
        return price_cache[skin_name]

    try:
        session = await get_session()
        encoded_name = quote(skin_name)
        api_url = f"https://standoff-2.com/skins-new.php?command=getStat&name={encoded_name}"
        
        async with session.get(api_url) as response:
            if response.status == 200:
                # Читаем "сырые" данные и парсим их через orjson
                # Это в 5-10 раз быстрее стандартного .json()
                raw_data = await response.read()
                data = orjson.loads(raw_data)
                
                if isinstance(data, list) and len(data) > 0:
                    latest_sale = data[-1]
                    price_str = latest_sale.get("purchase_price")
                    if price_str:
                        current_price = float(price_str.replace(' ', '').replace(',', '.'))
                        price_cache[skin_name] = current_price
                        return current_price
            return None
    except Exception as e:
        print(f"❌ Ошибка (orjson): {e}")
        return None

async def close_session():
    global _session
    if _session and not _session.closed:
        await _session.close()
        # Даем Windows время разорвать TCP-соединения
        await asyncio.sleep(0.2) 
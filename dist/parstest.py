import requests
from urllib.parse import quote

def get_actual_price(skin_name):
    # 1. Формируем URL для истории продаж (getStatSale)
    # Используем кавычки внутри названия для точности
    encoded_name = quote(skin_name) 
    api_url = f"https://standoff-2.com/skins-new.php?command=getStat&name={encoded_name}"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://standoff-2.com'
    }

    try:
        response = requests.get(api_url, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            
            # На скрине видно, что это список объектов
            if isinstance(data, list) and len(data) > 0:
                # Берем ПОСЛЕДНИЙ элемент (самая свежая дата)
                latest_sale = data[-1]
                
                # Забираем цену из поля "purchase_price"
                price_raw = latest_sale.get("purchase_price")
                
                if price_raw:
                    # Убираем пробелы и превращаем в число
                    # На скрине цена 8.17, точка уже есть, но подстрахуемся
                    return float(str(price_raw).replace(' ', '').replace(',', '.'))
            
    except Exception as e:
        print(f"❌ Ошибка парсера: {e}")
    return None

# --- ТЕСТ ---
if __name__ == "__main__":
    # Проверь на том самом M60 из скриншота
    test_name = 'M60 "Y-20 R.A.I.J.I.N."'
    price = get_actual_price(test_name)
    if price:
        print(f"✅ УСПЕХ! Последняя цена продажи: {price}G")
    else:
        print("❌ Не удалось получить цену. Проверь API еще раз.")
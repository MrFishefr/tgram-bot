from DrissionPage import ChromiumPage, ChromiumOptions
import asyncio
import os
from database import add_item_to_base
from urllib.parse import quote

async def fill_catalog_final():
    co = ChromiumOptions()
    path = os.path.join(os.getcwd(), 'filler_profile')
    co.set_user_data_path(path)
    
    page = ChromiumPage(co)
    # Твоя "золотая" ссылка
    url = 'https://standoff-2.com/shop/?skin=%22ALPHA7+ESPORTS%22+Major+2024+Sticker+Pack&type=all&rare=all&category=all&collection=all'
    
    try:
        print(f"🌐 Захожу по ссылке: {url}")
        page.get(url)
        await asyncio.sleep(10)

        print("🔎 Ожидаю появления списка результатов...")
        print("👉 ПОМОГИ БОТУ: Кликни на поле выбора скина в открытом окне браузера!")
        
        # ИСПРАВЛЕННАЯ СТРОКА: ждем появления списка #select2-skin-name-results
        # В DrissionPage ожидание встроено прямо в поиск элемента .ele()
        res_list = page.ele('#select2-skin-name-results', timeout=60)
        
        if res_list:
            print("🎉 Список обнаружен! Начинаю прокрутку и сбор данных...")
            
            last_count = 0
            while True:
                # Крутим колесико внутри списка через JS
                page.run_js('document.querySelector("#select2-skin-name-results").scrollTop += 10000')
                await asyncio.sleep(0.8)
                
                items = res_list.eles('tag:li')
                current_count = len(items)
                
                if current_count == last_count:
                    # Если за 2 секунды новых не прибавилось — значит всё
                    break
                
                last_count = current_count
                print(f"📦 Подгружено: {last_count} предметов...")

            # Сохраняем всё в базу
            count = 0
            for item in items:
                name = item.text.strip()
                
                if name and "Выберите" not in name:
                    # РЕШЕНИЕ: Оборачиваем имя в кавычки и используем quote_plus
                    # Это сделает ссылку вида: shop/?skin=%22USP-S+Genesis%22
                    formatted_name = f'"{name}"'
                    encoded_name = quote_plus(formatted_name)
                    
                    link = f"https://standoff-2.com/shop/?skin={encoded_name}&type=all"
                    
                    await add_item_to_base(name, link)
                    count += 1
            
            print(f"✅ ГОТОВО! В базу занесено {count} реальных скинов.")
        else:
            print("❌ Список так и не появился за 60 секунд.")

    finally:
        # 🚀 ВОТ ЭТО СПАСЕТ ТВОЙ ТЕРМИНАЛ:
        from database import db_conn
        if db_conn:
            print("📁 Закрываю соединение с базой данных...")
            await db_conn.close() 
        
        print("⌛ Закрываю браузер и выхожу...")
        page.quit()
        await asyncio.sleep(2)
        print("👋 Процесс завершен. Терминал свободен!")

if __name__ == "__main__":
    try:
        asyncio.run(fill_catalog_final())
    except KeyboardInterrupt:
        print("\nПрервано пользователем.")

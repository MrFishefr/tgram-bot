import asyncio
from database import add_item_to_base
from urllib.parse import quote

# Основные оружия и скины (пример расширенного списка)
GUNS = ["AKR", "AKR12", "M4", "M4A1", "AWM", "M40", "G22", "USP", "P350", "Desert Eagle", "Fabm", "SM1014", "MP7", "MP5", "UMP45", "P90"]
SKINS = ["Carbon", "Necromancer", "Genesis", "Tiger", "Sport", "2 Years Red", "Graffiti", "Nano", "Aurora", "Magma", "Year of the Horse"]
KNIVES = ["Karambit", "Butterfly", "M9 Bayonet", "Kunai", "jKommando", "Flip Knife", "Scorpion", "Dual Daggers", "Tanto", "Kukri"]
KNIFE_SKINS = ["Gold", "Dragon Glass", "Universe", "Scratch", "Ancient", "Luxury", "Reaper", "Starfall"]

async def fill_massive_catalog():
    print("🚀 Начинаю массовое заполнение базы всеми скинами...")
    count = 0
    
    # 1. Генерируем обычные скины
    for gun in GUNS:
        for skin in SKINS:
            name = f'{gun} "{skin}"'
            await add_item_to_base(name, f"https://standoff-2.com{quote(name)}&type=all")
            # Добавляем StatTrack версию
            st_name = f'{gun} StatTrack "{skin}"'
            await add_item_to_base(st_name, f"https://standoff-2.com{quote(st_name)}&type=all")
            count += 2

    # 2. Генерируем ножи
    for knife in KNIVES:
        for skin in KNIFE_SKINS:
            name = f'{knife} "{skin}"'
            await add_item_to_base(name, f"https://standoff-2.com{quote(name)}&type=all")
            count += 1

    print(f"✅ Готово! В базу занесено {count} предметов.")

if __name__ == "__main__":
    asyncio.run(fill_massive_catalog())

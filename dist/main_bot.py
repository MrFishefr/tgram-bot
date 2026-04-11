import asyncio
import html
import logging
import aiosqlite
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.redis import RedisStorage
import os
redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")


import aiohttp
from aiohttp_socks import ProxyConnector
import socket
import orjson
import database
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramBadRequest
from redis.asyncio import Redis
from database import (
    init_db, 
    get_db, 
    check_subscription, 
    get_user_sub_days, 
    use_promo_key,   # <-- ДОБАВЬ ЭТО
    save_price,      # <-- И ЭТО
    get_price_hour_ago,
    create_random_key,
    get_discount,
    get_market_tops,
    backup_to_github,
    get_user_monitoring # <-- И ЭТО ТОЖЕ
)


import re




import orjson
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.default import DefaultBotProperties

logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# import psutil, os
# p = psutil.Process(os.getpid())
# p.nice(psutil.HIGH_PRIORITY_CLASS)

ADMIN_IDS = [7639303686, 6559797682]

parse_limit = asyncio.Semaphore(100)


# Создаем одну глобальную переменную для базы
db_conn = None

async def get_db():
    global db_conn
    if db_conn is None:
        # Импортируем внутри, чтобы не было конфликтов
        import aiosqlite
        from database import DB_NAME
        db_conn = await aiosqlite.connect(DB_NAME)
        await db_conn.execute("PRAGMA journal_mode=WAL")
        await db_conn.execute("PRAGMA synchronous=NORMAL")
    return db_conn
# Твои модули
import database as db
from parser import get_actual_price

active_monitoring = {}

TOKEN = "8679759760:AAFO6ctei0iyknzlQZuaPyNGpNCeaCQXgV0"

import enum

class OrjsonProxySession(AiohttpSession):
    def __init__(self, google_url, **kwargs):
        self.google_url = google_url
        super().__init__(**kwargs)

    # ЭТОТ МЕТОД РЕШИТ ПРОБЛЕМУ Response[User]
    def check_response(self, bot, method, status_code, content):
        # Сначала даем библиотеке штатно проверить ответ (на ошибки 401, 404 и т.д.)
        result = super().check_response(bot, method, status_code, content)
        
        # Если это объект Response (в нем есть поле result), вынимаем данные
        if hasattr(result, 'result'):
            return result.result
        return result

    async def make_request(self, bot, method, timeout=None):
        if self._session is None or self._session.closed:
            self._session = await self.create_session()

        method_name = getattr(method, 'method', method.__class__.__name__)
        if method_name[0].isupper():
            method_name = method_name[0].lower() + method_name[1:]

        def prepare_data(obj):
            # Базовые типы
            if isinstance(obj, (str, int, float, bool, type(None))):
                return obj
            # Словари
            if isinstance(obj, dict):
                return {k: prepare_data(v) for k, v in obj.items() if v is not None}
            # Списки
            if isinstance(obj, list):
                return [prepare_data(v) for v in obj]
            # Перечисления (Enum)
            if hasattr(obj, 'value'):
                return obj.value
            # Модели aiogram
            if hasattr(obj, 'model_dump'):
                return prepare_data(obj.model_dump(exclude_none=True))
            # ВСЁ ОСТАЛЬНОЕ (включая Default и прочее) — либо в строку, либо удаляем
            # Если это объект Default от aiogram, он просто не пройдет проверку выше
            return None

        # Собираем финальный пакет
        cleaned_data = prepare_data(method)
        
        if isinstance(cleaned_data, dict):
            # 1. Если parse_mode не задан в команде, принудительно ставим HTML
            # Это заставит Telegram обрабатывать теги <b> и <i>
            if cleaned_data.get('parse_mode') is None:
                cleaned_data['parse_mode'] = "HTML"
            
            # 2. Удаляем link_preview_options только если они реально None
            if 'link_preview_options' in cleaned_data and cleaned_data['link_preview_options'] is None:
                del cleaned_data['link_preview_options']

        full_payload = {
            "method": method_name,
            "data": cleaned_data
        }
        
        async with self._session.post(
            self.google_url, 
            data=orjson.dumps(full_payload), 
            headers={"Content-Type": "application/json"},
            timeout=timeout
        ) as response:
            content = await response.read()
            return self.check_response(
                bot=bot,
                method=method,
                status_code=response.status,
                content=content.decode('utf-8')
            )




# Принудительно отключаем проверку DNS и SSL для связи с Telegram
# session = AiohttpSession(
#    connector=aiohttp.TCPConnector(use_dns_cache=False, ssl=False)
#bot = Bot(token=TOKEN, session=session)
bot = None
from aiogram import Router
router = Router() 

class BotStates(StatesGroup):
    waiting_for_key = State()
    waiting_for_skin = State()
    waiting_for_screenshot = State() # <-- ДОБАВИТЬ ЭТО
    waiting_for_promo = State() # Новое состояние
    waiting_for_adm_promo = State() # Для создания промокодов админом
    waiting_for_track_threshold = State()
    waiting_for_track_interval = State() 


def plural_days(n):
    """Функция для правильного склонения слова 'день'"""
    days_list = ['день', 'дня', 'дней']
    if n % 10 == 1 and n % 100 != 11:
        return days_list[0]
    elif 2 <= n % 10 <= 4 and (n % 100 < 10 or n % 100 >= 20):
        return days_list[1]
    return days_list[2]

import matplotlib.pyplot as plt
import io
from aiogram.types import BufferedInputFile

def create_price_chart(history, item_name):
    # Разделяем данные: history это список кортежей (цена, время)
    prices = [row[0] for row in history]
    # Форматируем время в часы:минуты
    times = [datetime.fromisoformat(row[1]).strftime('%H:%M') for row in history]

    plt.style.use('dark_background') # Темная тема
    fig, ax = plt.subplots(figsize=(10, 5))
    
    # Рисуем линию (голубой цвет #00aff0 как у Telegram)
    ax.plot(times, prices, color='#00aff0', linewidth=2, marker='o', markersize=3, label='Цена (G)')
    
    # Заливка под графиком (для эффекта объема)
    ax.fill_between(times, prices, color='#00aff0', alpha=0.1)

    # Настройка сетки и осей
    ax.grid(True, linestyle='--', alpha=0.2)
    ax.set_title(f"График {item_name} (24ч)", color='white', fontsize=14, pad=20)
    
    # Чтобы подписи на оси X не слипались
    if len(times) > 8:
        step = len(times) // 6
        ax.set_xticks(times[::step])
    
    plt.xticks(rotation=0, color='#aaaaaa')
    plt.yticks(color='#aaaaaa')
    
    # Убираем рамки для чистоты
    for spine in ax.spines.values():
        spine.set_visible(False)

    # Сохраняем в буфер памяти
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', dpi=100)
    plt.close(fig)
    buf.seek(0)
    return buf.read()

def main_kb():
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="👤 Профиль", callback_data="profile"))
    builder.row(types.InlineKeyboardButton(text="🎯 Выбор лота", callback_data="search_item"))
    builder.row(types.InlineKeyboardButton(text="🔑 Активировать ключ", callback_data="activate_key"))
    builder.row(types.InlineKeyboardButton(text="💎 Купить подписку", callback_data="buy_sub"))
    builder.row(types.InlineKeyboardButton(text="📡 Активные Отслеживания", callback_data="my_monitoring"))
    return builder.as_markup()
    

@router.message(Command("test"))
async def test_msg(message: types.Message):
    print("!!! ТЕСТОВАЯ КОМАНДА ПОЛУЧЕНА !!!")
    await message.answer("СВЯЗЬ ЕСТЬ! БОТ ЖИВОЙ!")

@router.message(Command("add_promo"))
async def adm_promo_start(message: types.Message, state: FSMContext):
    # ПРОВЕРКА: Если ID отправителя нет в списке ADMIN_IDS — бот игнорит
    if message.from_user.id not in ADMIN_IDS:
        return 

    await message.answer(
        "📝 <b>Создание промокода на скидку</b>\n\n"
        "Введите название и процент скидки через пробел.\n"
        "Пример: <code>TURBO 25</code>", 
        parse_mode="HTML"
    )
    await state.set_state(BotStates.waiting_for_adm_promo)

# 2. Сохранение промокода в базу
@router.message(BotStates.waiting_for_adm_promo)
async def adm_promo_save(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return

    try:
        # Разбиваем сообщение "PROMO 20" на части
        parts = message.text.split()
        code = parts[0].upper()      # Название промокода
        percent = int(parts[1])    # Процент скидки

        # Вызываем функцию из database.py
        from database import add_discount_code
        await add_discount_code(code, percent)

        await message.answer(
     f"✅ Промокод <b>{html.escape(code)}</b> на скидку <b>{percent}%</b> создан!", 

)
    except Exception as e:
        await message.answer("❌ Ошибка! Введите данные по шаблону: <code>КОД ПРОЦЕНТ</code>")
    
    await state.clear()

@router.message(Command("get_key"))
async def adm_get_key(message: types.Message):
    # Проверка на админа
    if message.from_user.id not in ADMIN_IDS: 
        return

    try:
        # Разбираем команду: /get_key дни [активации]
        args = message.text.split()
        days = int(args[1])
        
        # Если второй аргумент не ввели, ставим 1 активацию по умолчанию
        acts = int(args[2]) if len(args) > 2 else 1
        
        from database import create_random_key
        # Передаем оба параметра в функцию
        new_key = await create_random_key(days, acts)
        
        await message.answer(
            f"🔑 <b>Ключ сгенерирован:</b>\n\n"
            f"🎫 Код: <code>{html.escape(new_key)}</code>\n"
            f"⏳ Срок: <b>{days}</b> дн.\n"
            f"👥 Лимит: <b>{acts}</b> акт.",
            parse_mode="HTML"
        )
    except (IndexError, ValueError):
        await message.answer(
            "❌ <b>Ошибка!</b>\n"
            "Используйте: <code>/get_key дни [активации]</code>\n"
            "Пример: <code>/get_key 30 5</code>"
        )


@router.callback_query(F.data == "start_menu")
async def return_to_main_menu(callback: types.CallbackQuery, state: FSMContext):
    # 1. Сразу отвечаем на кнопку, чтобы убрать "часики"
    await callback.answer()
    
    # 2. Сбрасываем стейты
    await state.clear() 
    
    # Подготавливаем безопасный текст
    text = (
        f"Йоу, <b>{html.escape(callback.from_user.first_name)}</b>! 👋\n"
        "Я твой умный помощник по отслеживанию цен на скины в Standoff2.\n"
        "<b>Нажми на кнопки ниже чтобы начать работу со мной!)).</b>"
    )
    
    # 3. Безопасно редактируем сообщение
    try:
        await callback.message.edit_text(text, reply_markup=main_kb())
    except TelegramBadRequest as e:
        if "message is not modified" in e.message:
            # Если текст тот же самый — просто игнорируем ошибку
            pass
        else:
            # Если ошибка другая (например, битый HTML) — выводим в консоль
            print(f"🚨 Ошибка в меню: {e}")

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
    f"Йоу, <b>{html.escape(message.from_user.first_name)}</b>! 👋\n"
    "Я твой умный помощник по отслеживанию цен на скины в Standoff2.\n"
    "<b>Нажми на кнопки ниже чтобы начать работу со мной!)).</b>",
    reply_markup=main_kb()
    # parse_mode="HTML" убираем, так как он в DefaultBotProperties
)

# --- ПРОФИЛЬ ---
@router.callback_query(F.data == "profile")
async def show_profile(callback: types.CallbackQuery, state: FSMContext):
    # 1. ЗАЩИТА: Мгновенный ответ с перехватом ошибки "query is too old"
    try:
        await callback.answer()
    except Exception:
        # Если кнопка устарела, просто игнорируем ошибку и идем дальше
        pass

    # Сбрасываем любые активные состояния
    await state.clear()

    try:
        user_id = callback.from_user.id
        days = await get_user_sub_days(user_id)
        is_active = days > 0
        
        status_text = "✅ Активна" if is_active else "❌ Неактивна"
        
        text = (
            f"👤 <b>Ваш профиль</b>\n\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"💎 Подписка: {status_text}\n"
            f"📅 Истекает через: <b>{days} {plural_days(days)}</b>"
        )
        
        kb = InlineKeyboardBuilder()
        kb.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="start_menu"))
        markup = kb.as_markup()

        # 2. БРОНЕБОЙНОЕ обновление интерфейса
        try:
            # Если это обычное текстовое сообщение - редактируем
            if callback.message.content_type == types.ContentType.TEXT:
                await callback.message.edit_text(text, reply_markup=markup)
            else:
                # Если в сообщении было фото/файл - шлем новое и удаляем старое
                await callback.message.answer(text, reply_markup=markup)
                try:
                    await callback.message.delete()
                except Exception:
                    pass
        except TelegramBadRequest as e:
            # Если "message is not modified" (юзер спамит кнопку) - игнорим
            if "message is not modified" in e.message:
                pass
            else:
                # В любой другой непонятной ситуации просто шлем новое сообщение
                await callback.message.answer(text, reply_markup=markup)

    except Exception as e:
        logging.error(f"Ошибка профиля {callback.from_user.id}: {e}")
        # Если всё совсем плохо - шлем новое сообщение текстом
        await callback.message.answer("🛠 Ошибка загрузки данных. Попробуйте позже.")


# --- АКТИВАЦИЯ КЛЮЧА (ИЗ БАЗЫ) ---
@router.callback_query(F.data == "activate_key")
async def start_activate(callback: types.CallbackQuery, state: FSMContext):
    # 1. ЗАЩИТА: Мгновенный ответ (убираем "часики") с перехватом устаревших запросов
    try:
        await callback.answer()
    except Exception:
        pass # Если запрос устарел, просто идем дальше к отправке нового сообщения

    logging.info(f"User {callback.from_user.id} начал активацию ключа")
    
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="🔙 Отмена", callback_data="start_menu"))
    
    text = "🔑 <b>Введите ваш ключ активации:</b>\n\n<i>Просто пришлите его ответным сообщением.</i>"
    
    # 2. БРОНЕБОЙНОЕ переключение интерфейса
    try:
        # Проверяем, можно ли редактировать старое сообщение
        if callback.message.content_type == types.ContentType.TEXT:
            await callback.message.edit_text(text, reply_markup=kb.as_markup())
        else:
            # Если в сообщении было медиа (скриншот или скин) - шлем новое
            await callback.message.answer(text, reply_markup=kb.as_markup())
            try:
                await callback.message.delete()
            except Exception:
                pass
    except TelegramBadRequest as e:
        # Если сообщение нельзя изменить или оно удалено - просто шлем новое
        if "message is not modified" not in e.message:
            await callback.message.answer(text, reply_markup=kb.as_markup())
        else:
            pass # Если текст тот же, ничего не делаем

    # 3. Устанавливаем состояние
    await state.set_state(BotStates.waiting_for_key)

@router.message(BotStates.waiting_for_key)
async def process_key(message: types.Message, state: FSMContext):
    if not message.text:
        return await message.answer("❌ Отправьте ключ текстом.")

    key = message.text.strip()
    
    try:
        # Вызываем обновленную функцию
        result = await use_promo_key(message.from_user.id, key)
    except Exception as e:
        logging.error(f"Ошибка активации ключа для {message.from_user.id}: {e}")
        return await message.answer("🛠 Произошла ошибка. Попробуйте позже.")
    
    # 1. СЛУЧАЙ: Лимит исчерпан
    if result == "limit_exceeded":
        return await message.answer(
            "❌ <b>Ошибка!</b>\nЛимит активаций этого ключа уже исчерпан другими пользователями."
        )

    # 2. СЛУЧАЙ: Успех (вернулось количество дней)
    elif result:
        await message.answer(
            f"✅ <b>Красавчик!</b>\n"
            f"Подписка успешно активирована на <b>{result}</b> {plural_days(result)}.\n\n"
            f"Теперь ты можешь запустить <b>отслеживание</b> скинов в реальном времени! 🔥",
            reply_markup=main_kb() 
        )
        await state.clear()

    # 3. СЛУЧАЙ: Ключ не найден (None)
    else:
        kb = InlineKeyboardBuilder()
        kb.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="start_menu"))
        
        await message.answer(
            "❌ <b>Ошибка!</b>\nКлюч недействителен или введен неверно.",
            reply_markup=kb.as_markup()
        )
        # Стейт НЕ очищаем, чтобы юзер мог попробовать ввести другой ключ или исправить опечатку

# --- ПОИСК И ВЫДАЧА ЦЕНЫ ---

@router.callback_query(F.data == "search_item")
async def search_check(callback: types.CallbackQuery, state: FSMContext):
    # 1. ЗАЩИТА: Мгновенный ответ с перехватом "query is too old"
    try:
        await callback.answer()
    except Exception:
        pass # Если кнопка устарела, просто продолжаем логику

    # 2. Быстрая проверка подписки
    days = await get_user_sub_days(callback.from_user.id)
    
    kb = InlineKeyboardBuilder()
    
    if days <= 0:
        text = (
            "🚨 <b>Доступ запрещен!</b>\n"
            "Для использования поиска необходима активная подписка.\n\n"
            "💎 Нажми кнопку ниже, чтобы выбрать тариф!"
        )
        kb.row(types.InlineKeyboardButton(text="💎 Купить подписку", callback_data="buy_sub"))
        kb.row(types.InlineKeyboardButton(text="🔙 В меню", callback_data="start_menu"))
        await state.clear()
    else:
        text = (
            "🎯 <b>Введите название скина:</b>\n"
            "(Например: <code>M16 Naga</code> или <code>Karambit Gold</code>)\n\n"
            "<i>Я найду актуальную цену на рынке прямо сейчас.</i>"
        )
        kb.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="start_menu"))
        await state.set_state(BotStates.waiting_for_skin)

    # 3. БРОНЕБОЙНОЕ обновление интерфейса
    markup = kb.as_markup()
    try:
        # Проверяем, можно ли редактировать старое сообщение
        if callback.message.content_type == types.ContentType.TEXT:
            try:
                await callback.message.edit_text(text, reply_markup=markup)
            except TelegramBadRequest as e:
                # Если "message is not modified" (юзер кликнул дважды) - игнорим
                if "message is not modified" in e.message:
                    pass
                else:
                    # В любой другой ситуации (сообщение удалено и т.д.) - шлем новое
                    await callback.message.answer(text, reply_markup=markup)
        else:
            # Если в сообщении было фото - шлем новое и пытаемся удалить старое
            await callback.message.answer(text, reply_markup=markup)
            try:
                await callback.message.delete()
            except Exception:
                pass
                
    except Exception as e:
        logging.error(f"🚨 Критическая ошибка в переходе к поиску: {e}")
        # Запасной выход на случай полного сбоя
        await callback.message.answer(text, reply_markup=markup)

@router.message(BotStates.waiting_for_skin)
async def perform_search(message: types.Message, state: FSMContext):
    # 1. Защита от пустых сообщений (медиа/стикеры)
    if not message.text:
        return await message.answer("❌ Пожалуйста, введите название скина текстом.")

    # Чистим запрос
    query = message.text.strip().lower().replace('"', '')
    
    # Сбрасываем стейт СРАЗУ (защита от повторных срабатываний во время парсинга)
    await state.clear()

    try:
        db_conn = await get_db()
        
        # 2. Поиск в БД
        sql_query = "SELECT id, name FROM items WHERE LOWER(REPLACE(name, '\"', '')) LIKE ? LIMIT 5"
        async with db_conn.execute(sql_query, (f"%{query}%",)) as cursor:
            items = await cursor.fetchall()
            
            back_kb = InlineKeyboardBuilder()
            back_kb.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="start_menu"))

            if not items:
                return await message.answer("❌ <b>Такого скина нет в игре!</b>", reply_markup=back_kb.as_markup())

            # 3. Если найдено несколько вариантов
            if len(items) > 1:
                kb = InlineKeyboardBuilder()
                for item in items:
                    # Безопасная распаковка (поддерживает и Row, и кортеж)
                    i_id, i_name = item[0], item[1]
                    kb.row(types.InlineKeyboardButton(text=i_name, callback_data=f"select_skin_{i_id}"))
                kb.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="start_menu"))
                
                return await message.answer(
                    f"🤔 Нашел несколько вариантов. Какой именно <b>{html.escape(message.text)}</b> тебя интересует?",
                    reply_markup=kb.as_markup()
                )

            # 4. Если найден ровно один
            item_id, name = items[0][0], items[0][1]
            
            # Информируем о начале парсинга (создаем объект сообщения)
            msg = await message.answer(f"⏳ Чекаю цену <b>{html.escape(name)}</b>...")
            
            # Ограничиваем нагрузку на парсер семафором
            async with parse_limit:
                price = await get_actual_price(name)
            
            if price:
                # Сохраняем цену в историю
                await save_price(item_id, price)
                old_data = await get_price_hour_ago(item_id)
                
                # Логика расчета разницы
                history_text = ""
                # Безопасно вытаскиваем цену (проверка на None и тип)
                if old_data:
                    old_price = old_data[0] if isinstance(old_data, (tuple, list, aiosqlite.Row)) else old_data
                else:
                    old_price = None
                
                if old_price and isinstance(old_price, (int, float)) and old_price > 0:
                    diff = price - old_price
                    perc = (diff / old_price) * 100
                    sign = "📈 +" if diff > 0 else "📉 "
                    history_text = f"\n📊 <b>За 1 час:</b> {sign}{diff:.2f}G ({perc:.2f}%)"
                else:
                    history_text = "\nℹ️ <i>История цен еще не сформирована...</i>"

                kb = InlineKeyboardBuilder()
                kb.row(types.InlineKeyboardButton(text="📊 Начать Отслеживание!", callback_data=f"track_{item_id}"))
                kb.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="start_menu"))
                
                text = (
                    f"📦 <b>{html.escape(name)}</b>\n"
                    f"💰 Цена сейчас: <code>{price}G</code>"
                    f"{history_text}\n\n"
                    f"🕒 Время: {datetime.now().strftime('%H:%M')}"
                )
                
                # БРОНЕБОЙНОЕ редактирование "Чекаю..." на финальный результат
                try:
                    await msg.edit_text(text, reply_markup=kb.as_markup())
                except TelegramBadRequest as e:
                    if "message is not modified" not in e.message:
                        # Если сообщение удалено пользователем, шлем новое
                        await message.answer(text, reply_markup=kb.as_markup())
            else:
                # Если парсер вернул None
                await msg.edit_text("❌ Ошибка получения цены. Попробуйте позже.", reply_markup=back_kb.as_markup())

    except Exception as e:
        logging.error(f"🚨 Критическая ошибка в perform_search: {e}")
        await message.answer("🛠 Произошла техническая ошибка. Попробуйте еще раз.")

# --- ОБРАБОТЧИК ДЛЯ ВЫБОРА ИЗ СПИСКА ---
@router.callback_query(F.data.startswith("select_skin_"))
async def select_skin_callback(callback: types.CallbackQuery):
    # 1. ЗАЩИТА: Мгновенный ответ с перехватом ошибки "query is too old"
    try:
        await callback.answer()
    except Exception:
        pass # Если кнопка устарела, бот просто продолжит работу

    # Извлекаем ID (через split безопаснее)
    item_id = callback.data.split("_")[-1]
    
    try:
        db_conn = await get_db()
        
        # 2. Получаем данные из базы
        async with db_conn.execute("SELECT name FROM items WHERE id = ?", (item_id,)) as cursor:
            item = await cursor.fetchone()
            if not item:
                return await callback.message.answer("❌ Скин не найден в базе данных.")
            
            # Универсальная распаковка (для aiosqlite.Row или обычного кортежа)
            name = item[0] if not isinstance(item, dict) else item['name']

        # Сообщение-заглушка (сохраняем объект для редактирования)
        msg = await callback.message.answer(
            f"⏳ Чекаю цену <b>{html.escape(name)}</b>, секунду..."
        )
        
        # 3. Парсинг цены (через семафор)
        async with parse_limit:
            price = await get_actual_price(name)

        # Дефолтная кнопка назад
        back_kb = InlineKeyboardBuilder()
        back_kb.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="start_menu"))

        if price:
            # Сохраняем актуальную цену в историю
            await save_price(item_id, price)
            old_price_data = await get_price_hour_ago(item_id)
            
            history_text = ""
            # Безопасная распаковка цены из истории (через проверку типов)
            if old_price_data:
                old_price = old_price_data[0] if isinstance(old_price_data, (tuple, list, aiosqlite.Row)) else old_price_data
            else:
                old_price = None
            
            if old_price and isinstance(old_price, (int, float)) and old_price > 0:
                diff = price - old_price
                perc = (diff / old_price) * 100
                sign = "📈 +" if diff > 0 else "📉 "
                history_text = f"\n📊 <b>За 1 час:</b> {sign}{diff:.2f}G ({perc:.2f}%)"
            else:
                history_text = "\nℹ️ <i>История цен еще не сформирована...</i>"

            kb = InlineKeyboardBuilder()
            kb.row(types.InlineKeyboardButton(text="📊 Начать Отслеживание", callback_data=f"track_{item_id}"))
            kb.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="start_menu"))
            
            text = (
                f"📦 <b>{html.escape(name)}</b>\n"
                f"💰 Цена сейчас: <code>{price}G</code>"
                f"{history_text}\n\n"
                f"🕒 Время: {datetime.now().strftime('%H:%M')}"
            )
            
            # БРОНЕБОЙНОЕ редактирование "Чекаю..." на результат
            try:
                await msg.edit_text(text, reply_markup=kb.as_markup())
            except TelegramBadRequest as e:
                # Если сообщение было удалено юзером пока шел парсинг - шлем новое
                if "message is not modified" not in e.message:
                    await callback.message.answer(text, reply_markup=kb.as_markup())
        else:
            # Если парсер не вернул цену (ошибка API или сайта)
            await msg.edit_text("❌ Ошибка получения цены. Попробуйте позже.", reply_markup=back_kb.as_markup())

    except Exception as e:
        logging.error(f"🚨 Ошибка в select_skin_callback: {e}")
        # Если все упало, даем юзеру знать
        await callback.message.answer("🛠 Произошла ошибка. Попробуйте найти скин еще раз.")

@router.callback_query(F.data.startswith("track_"))
async def start_tracking_step_1(callback: types.CallbackQuery, state: FSMContext):
    # 1. ЗАЩИТА: Мгновенный ответ кнопке с перехватом ошибки "query is too old"
    try:
        await callback.answer()
    except Exception:
        pass # Если кнопка устарела, бот просто продолжит выполнение

    try:
        # Извлекаем ID (через split безопаснее)
        parts = callback.data.split("_")
        if len(parts) < 2:
            return
        item_id = parts[1]
        
        # 2. Достаем имя скина из БД
        conn = await get_db()
        async with conn.execute("SELECT name FROM items WHERE id = ?", (item_id,)) as cursor:
            res = await cursor.fetchone()
            if not res:
                return await callback.message.answer("❌ Ошибка: Скин не найден в базе данных.")
            
            # Универсальная распаковка (для aiosqlite.Row или обычного кортежа)
            name = res[0] if isinstance(res, (tuple, list)) else res['name']

        # 3. Сохраняем в state СРАЗУ
        await state.update_data(track_item_id=item_id, track_item_name=name)
        
        # 4. Устанавливаем стейт ДО редактирования текста
        await state.set_state(BotStates.waiting_for_track_threshold)
        
        kb = InlineKeyboardBuilder()
        kb.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="start_menu"))

        text = (
            f"📝 <b>Настройка уведомлений для {html.escape(name)}</b>\n\n"
            "Напишите, при каком падении или росте цены присылать уведомление.\n"
            "Формат: <code>-25 +40 (Проценты)</code>\n\n"
            "<i>Я буду проверять актуальную цену на рынке, пока вы не остановите процесс.</i>"
        )

        # 5. БРОНЕБОЙНОЕ обновление интерфейса
        markup = kb.as_markup()
        try:
            if callback.message.content_type == types.ContentType.TEXT:
                await callback.message.edit_text(text, reply_markup=markup)
            else:
                # Если в сообщении было медиа (фото/файл) - шлем новое и удаляем старое
                await callback.message.answer(text, reply_markup=markup)
                try:
                    await callback.message.delete()
                except Exception:
                    pass
        except TelegramBadRequest as e:
            if "message is not modified" not in e.message:
                # Если сообщение удалено пользователем, просто шлем новое
                await callback.message.answer(text, reply_markup=markup)
            else:
                pass # Если текст тот же, ничего не делаем

    except Exception as e:
        logging.error(f"🚨 Критическая ошибка в start_tracking_step_1: {e}")
        await callback.message.answer("🛠 Произошла ошибка. Попробуйте найти скин заново.")

# --- ШАГ 2: ОБРАБОТКА ВВОДА И ЦИКЛ ---
@router.message(BotStates.waiting_for_track_threshold)
async def track_step_1_get_percents(message: types.Message, state: FSMContext):
    # Парсим пороги
    numbers = re.findall(r'[-+]?\d*\.?\d+', message.text)
    
    if len(numbers) < 2:
        await message.answer("❌ <b>Ошибка!</b> Введите два числа (например: <code>-10 +20</code>)")
        return

    # Сохраняем проценты временно в стейт
    await state.update_data(
        down=abs(float(numbers[0])), 
        up=float(numbers[1])
    )
    
    # Спрашиваем про интервал (минуты)
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="⏱ Только при скачке", callback_data="set_interval_0"))
    kb.row(types.InlineKeyboardButton(text="15 мин", callback_data="set_interval_15"),
           types.InlineKeyboardButton(text="60 мин", callback_data="set_interval_60"))
    kb.row(types.InlineKeyboardButton(text="🔙 Отмена", callback_data="start_menu"))
    
    await message.answer(
        "⏳ <b>Как часто присылать отчет о цене?</b>\n\n"
        "Выберите вариант или <b>напишите количество минут</b> (1–99999) вручную:",
        reply_markup=kb.as_markup()
    )
    await state.set_state(BotStates.waiting_for_track_interval)


@router.callback_query(F.data.startswith("set_interval_"))
@router.message(BotStates.waiting_for_track_interval)
async def track_step_2_save_to_db(event: types.Union[types.Message, types.CallbackQuery], state: FSMContext):
    # 1. ЗАЩИТА: Мгновенный ответ для Callback
    if isinstance(event, types.CallbackQuery):
        try:
            await event.answer()
        except Exception:
            pass
        interval_str = event.data.split("_")[-1]
    else:
        if not event.text or not event.text.isdigit():
            return await event.answer("❌ Введите число минут цифрами (например: 30)!")
        interval_str = event.text

    interval = int(interval_str)

    # 2. Безопасное получение данных из стейта
    data = await state.get_data()
    name = data.get("track_item_name")
    item_id = data.get("track_item_id")
    down = data.get("down")
    up = data.get("up")

    # Если данные "протухли" в /памяти
    if not name or down is None:
        await state.clear()
        msg = "❌ Ошибка: сессия истекла. Пожалуйста, найдите скин заново."
        return await (event.message.answer(msg) if isinstance(event, types.CallbackQuery) else event.answer(msg))

    # 3. Расчет времени и работа с БД
    try:
        next_time = (datetime.now() + timedelta(minutes=interval)).isoformat() if interval > 0 else None

        db_conn = await get_db()
        async with parse_limit:
            current_price = await get_actual_price(name) or 0

        # Атомарная запись в БД
        # Атомарная запись в БД (ЯВНО УКАЗЫВАЕМ КОЛОНКИ)
        print(f"DEBUG: Пытаюсь сохранить: User:{event.from_user.id}, Item:{name}, Price:{current_price}")

        db_conn = await get_db()
        
        # Используем ЯВНЫЙ список колонок (это решит проблему 8 vs 9 колонок)
        await db_conn.execute(
            """INSERT INTO monitoring 
            (user_id, item_id, item_name, threshold_down, threshold_up, last_price, interval_min, next_check) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (int(event.from_user.id), item_id, name, down, up, current_price, interval, next_time)
        )
        
        await db_conn.commit()
        database.db_changed = True
        print("✅ DEBUG: Запись успешно закомичена в БД!")
        await state.clear()

        # 4. Формируем финальный ответ
        msg_text = (
            f"✅ <b>Мониторинг запущен: {html.escape(name)}</b>\n"
            f"📊 Пороги: -{down}% / +{up}%\n"
            f"🕒 Отчеты: {'только при скачке' if interval == 0 else f'каждые {interval} мин.'}"
        )
        
        stop_kb = InlineKeyboardBuilder().button(text="🛑 Стоп", callback_data=f"stop_track_{event.from_user.id}").as_markup()
        
        if isinstance(event, types.CallbackQuery):
            await event.message.answer(msg_text, reply_markup=stop_kb)
        else:
            await event.answer(msg_text, reply_markup=stop_kb)

    except Exception as e:
        import traceback
        logging.error(f"🚨 Ошибка сохранения мониторинга: {e}\n{traceback.format_exc()}")
        
        # Выводим конкретный текст ошибки в чат, чтобы понять, чего не хватает базе
        error_details = f"🛠 Ошибка БД: {e}"
        if isinstance(event, types.CallbackQuery):
            await event.message.answer(error_details)
        else:
            await event.answer(error_details)
            
        await state.clear()

# --- ОБРАБОТЧИК КНОПКИ СТОП (ОСТАВЛЯЕМ КАК ЕСТЬ) ---
@router.callback_query(F.data.startswith("stop_track_"))
async def stop_tracking_handler(callback: types.CallbackQuery):
    # 1. ЗАЩИТА: Мгновенный ответ с перехватом "query is too old"
    try:
        await callback.answer()
    except Exception:
        pass 

    try:
        # Извлекаем ID пользователя из кнопки
        parts = callback.data.split("_")
        if len(parts) < 3:
            return
        target_user_id = int(parts[2])
        
        # 2. БЕЗОПАСНОСТЬ: проверка прав
        if callback.from_user.id != target_user_id and callback.from_user.id not in ADMIN_IDS:
            try:
                await callback.answer("⚠️ У вас нет прав для этого действия.", show_alert=True)
            except Exception:
                await callback.message.answer("⚠️ У вас нет прав для этого действия.")
            return

        # 3. УДАЛЕНИЕ ИЗ БАЗЫ (для нового фонового мониторинга)
        db_conn = await get_db()
        # Удаляем все активные отслеживания этого пользователя для этого скина
        # (Если нужно удалять конкретный скин, в callback_data стоит добавить item_id)
        await db_conn.execute("DELETE FROM monitoring WHERE user_id = ?", (target_user_id,))
        await db_conn.commit()
        database.db_changed = True

        # Также сбрасываем флаг в старом словаре для совместимости
        if target_user_id in active_monitoring:
            active_monitoring[target_user_id] = False

        try:
            await callback.answer("🛑 Мониторинг полностью остановлен!")
        except Exception:
            await callback.message.answer("🛑 Мониторинг полностью остановлен!")

        # 4. БРОНЕБОЙНОЕ удаление кнопок
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest as e:
            if "message is not modified" not in e.message:
                logging.error(f"Ошибка при скрытии кнопок STOP: {e}")

    except (ValueError, IndexError) as e:
        logging.error(f"Ошибка парсинга stop_track: {e}")
        try:
            await callback.answer("❌ Ошибка обработки запроса.")
        except Exception:
            pass

# --- 1. МЕНЮ ВЫБОРА ТАРИФА (ВХОДНАЯ ТОЧКА) ---
# --- 1. ВЫБОР ПЛАНА ---
@router.callback_query(F.data == "buy_sub")
async def ask_promo(callback: types.CallbackQuery, state: FSMContext):
    # 1. ЗАЩИТА: Мгновенный ответ с перехватом ошибки устаревшего запроса
    try:
        await callback.answer()
    except Exception:
        pass # Если кнопка "протухла", просто продолжаем логику отправки нового сообщения

    # 2. СБРОС старых данных (на случай, если юзер зашел повторно из другого меню)
    await state.clear()
    
    # Готовим кнопки
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="❌ У меня нет промокода", callback_data="no_promo"))
    builder.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="start_menu"))
    
    text = (
        "🎟 <b>У вас есть промокод на скидку?</b>\n\n"
        "Отправьте его сообщением прямо в этот чат.\n\n"
        "<i>Если промокода нет — просто нажмите кнопку ниже.</i>"
    )
    
    # 3. БРОНЕБОЙНОЕ обновление интерфейса
    markup = builder.as_markup()
    try:
        # Проверка типа контента: если в сообщении был текст - редактируем
        if callback.message.content_type == types.ContentType.TEXT:
            try:
                await callback.message.edit_text(text, reply_markup=markup)
            except TelegramBadRequest as e:
                # Если "message is not modified" (юзер кликнул дважды) - игнорим
                if "message is not modified" in e.message:
                    pass
                else:
                    # В любой другой ситуации (сообщение удалено и т.д.) - шлем новое
                    await callback.message.answer(text, reply_markup=markup)
        else:
            # Если в сообщении было фото (например, старый чек или скин) - шлем новое и удаляем старое
            await callback.message.answer(text, reply_markup=markup)
            try:
                await callback.message.delete()
            except Exception:
                pass
            
    except Exception as e:
        logging.error(f"🚨 Ошибка в ask_promo: {e}")
        # Запасной вариант: всегда шлем новое сообщение, если редактирование упало
        await callback.message.answer(text, reply_markup=markup)

    # 4. Включаем режим ожидания промокода
    await state.set_state(BotStates.waiting_for_promo)

# --- ШАГ 2: ОБРАБОТКА ПРОМОКОДА ---
@router.callback_query(F.data == "no_promo")
async def process_no_promo(callback: types.CallbackQuery, state: FSMContext):
    # 1. Мгновенный ответ кнопке
    await callback.answer()
    
    # 2. Сбрасываем стейт СРАЗУ. 
    # Так как мы передаем discount=0 напрямую в функцию, стейт нам больше не нужен.
    await state.clear()
    
    # 3. Обновляем сообщение на список тарифов
    # Передаем сам callback, чтобы функция show_plans могла сделать edit_text
    try:
        await show_plans(callback, 0)
    except Exception as e:
        logging.error(f"Ошибка при показе планов без промо: {e}")
        # Если что-то пошло не так, просто шлем меню
        await callback.message.answer("💎 Выберите подходящий тариф:", reply_markup=main_kb())

@router.message(BotStates.waiting_for_promo)
async def process_promo_input(message: types.Message, state: FSMContext):
    # 1. Проверка на наличие текста (защита от стикеров/фото)
    if not message.text:
        return await message.answer("❌ Отправьте промокод текстом или нажмите кнопку выше.")

    code = message.text.strip().upper()
    
    # 2. Получаем скидку (функция из database.py)
    try:
        discount = await get_discount(code)
    except Exception as e:
        logging.error(f"Ошибка БД при проверке промокода: {e}")
        discount = 0

    # 3. Сохраняем результат в стейт СРАЗУ
    await state.update_data(discount=discount)
    
    # 4. Формируем уведомление, но НЕ шлем его отдельным сообщением
    # Вместо этого мы передадим инфо прямо в show_plans
    if discount > 0:
        result_msg = f"✅ Промокод <b>{html.escape(code)}</b> принят! Скидка: <b>{discount}%</b>"
    else:
        result_msg = "❌ Промокод не найден или истек. Цены будут стандартными."

    # 5. Вызываем показ тарифов
    # Мы передаем сообщение пользователя, чтобы show_plans ответил на него
    # Сбрасываем стейт до None, чтобы юзер мог снова пользоваться командами
    await state.set_state(None)
    
    # Чтобы не плодить сообщения, мы можем отправить результат в одном блоке с тарифами
    # Для этого передаем текст результата в нашу функцию (если ты ее чуть подправишь) 
    # или просто шлем сначала уведомление, а потом тарифы (как ниже)
    
    await message.answer(result_msg)
    await show_plans(message, discount)

# --- ШАГ 3: ВЫБОР ТАРИФА (С КНОПКОЙ НАЗАД) ---
async def show_plans(message_or_call: types.Union[types.Message, types.CallbackQuery], discount: int):
    # Конфиг цен
    base_prices = {30: 200, 90: 350, 365: 900}
    gold_prices = {30: 400, 90: 700, 365: 1800}
    
    builder = InlineKeyboardBuilder()
    # Исправлен цикл: добавлена итерация по списку ключей
    for days in [30, 90, 365]:
        disc_factor = max(0, min(100, int(discount))) / 100
        p_rub = int(base_prices[days] * (1 - disc_factor))
        p_gold = int(gold_prices[days] * (1 - disc_factor))
        
        builder.row(types.InlineKeyboardButton(
            text=f"⏳ {days} {plural_days(days)} — {p_rub}₽ / {p_gold}G", 
            callback_data=f"buy_{days}_{p_rub}"
        ))
    
    builder.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="start_menu"))
    
    text = "💎 <b>Выберите подходящий тариф:</b>"
    if discount > 0:
        text += f"\n🔥 <i>Применена скидка {html.escape(str(discount))}%</i>"

    markup = builder.as_markup()

    try:
        if isinstance(message_or_call, types.CallbackQuery):
            # 1. ЗАЩИТА: Мгновенный ответ с перехватом "query is too old"
            try:
                await message_or_call.answer()
            except Exception:
                pass

            # 2. БРОНЕБОЙНОЕ обновление
            if message_or_call.message.content_type == types.ContentType.TEXT:
                try:
                    await message_or_call.message.edit_text(text, reply_markup=markup)
                except TelegramBadRequest as e:
                    if "message is not modified" not in e.message:
                        await message_or_call.message.answer(text, reply_markup=markup)
            else:
                # Если в сообщении было фото - шлем новое и удаляем старое
                await message_or_call.message.answer(text, reply_markup=markup)
                try:
                    await message_or_call.message.delete()
                except Exception:
                    pass
        else:
            # Для обычного сообщения (после ввода промокода)
            await message_or_call.answer(text, reply_markup=markup)
            
    except Exception as e:
        logging.error(f"🚨 Критическая ошибка в show_plans: {e}")
        # Запасной вариант: шлем новое сообщение в любой непонятной ситуации
        if isinstance(message_or_call, types.CallbackQuery):
            await message_or_call.message.answer(text, reply_markup=markup)
        else:
            await message_or_call.answer(text, reply_markup=markup)
# --- ШАГ 4: ИНСТРУКЦИЯ ПО ОПЛАТЕ (ТВОЯ ЛОГИКА) ---


@router.callback_query(F.data == "my_monitoring")
async def show_my_monitoring(callback: types.CallbackQuery):
    try: await callback.answer()
    except: pass

    tracks = await get_user_monitoring(callback.from_user.id)

    if not tracks:
        kb = InlineKeyboardBuilder().button(text="🔙 Назад", callback_data="start_menu").as_markup()
        return await callback.message.edit_text("🔌 <b>У вас нет активных отслеживаний.</b>", reply_markup=kb)

    text = "📡 <b>Ваш список отслеживания:</b>\n\n"
    kb = InlineKeyboardBuilder()

    for m_id, name, down, up, interval in tracks:
        # Твой текст настроек
        time_info = f"⏱ {interval} мин. (интервал отчета)" if interval > 0 else "🚀 Только скачки"
        text += f"📦 <b>{name}</b>\n└ 🔴-{down}% | 🟢+{up}% | {time_info}\n\n"
        
        # Две кнопки в ряд: График и Стоп
        kb.row(
            types.InlineKeyboardButton(text=f"📈 График", callback_data=f"graph_{m_id}"),
            types.InlineKeyboardButton(text=f"❌ Стоп", callback_data=f"del_monit_{m_id}")
        )

    kb.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="start_menu"))
    
    try:
        await callback.message.edit_text(text, reply_markup=kb.as_markup())
    except Exception:
        await callback.message.answer(text, reply_markup=kb.as_markup())

@router.callback_query(F.data.startswith("graph_"))
async def handle_graph_request(callback: types.CallbackQuery):
    # 1. Защита от "часиков"
    try: await callback.answer("⏳ Рисую график...")
    except: pass

    m_id = callback.data.split("_")[-1]
    db = await get_db()
    
    # 2. Получаем имя и ID скина по ID мониторинга
    async with db.execute("SELECT item_id, item_name FROM monitoring WHERE id = ?", (m_id,)) as cursor:
        res = await cursor.fetchone()
        if not res: return
        i_id, name = res[0], res[1]

    # 3. Вызываем твою новую функцию из database.py
    from database import get_price_history_24h
    history_data = await get_price_history_24h(i_id)
    
    if len(history_data) < 2:
        return await callback.message.answer(f"⚠️ Для <b>{name}</b> мало данных (нужно хотя бы 2 записи цен в базе).")

    # 4. Рисуем (функция ниже) и отправляем
    chart_bytes = create_price_chart(history_data, name)
    from aiogram.types import BufferedInputFile
    photo = BufferedInputFile(chart_bytes, filename=f"chart_{i_id}.png")
    
    await callback.message.answer_photo(photo=photo, caption=f"📊 График цен <b>{name}</b> за 24 часа.")

@router.callback_query(F.data.startswith("del_monit_"))
async def delete_specific_monitoring(callback: types.CallbackQuery):
    try: await callback.answer()
    except: pass
    
    m_id = callback.data.split("_")[-1]
    db = await get_db()
    await db.execute("DELETE FROM monitoring WHERE id = ?", (m_id,))
    await db.commit()
    
    await callback.answer("✅ Отслеживание удалено!", show_alert=True)
    # Обновляем список
    await show_my_monitoring(callback)


@router.message(Command("top"))
async def cmd_top_market(message: types.Message):
    # 1. Проверка подписки
    days = await get_user_sub_days(message.from_user.id)
    if days <= 0:
        return await message.answer("💎 <b>Функция доступна только по подписке!</b>\nКупите её в меню оплаты.")

    # 2. Получаем данные из БД
    gainers, losers = await get_market_tops(limit=5)
    
    if not gainers and not losers:
        return await message.answer("⏳ <b>История цен еще копится...</b>\nЗайдите через час, когда база соберет достаточно данных для сравнения!")

    # 3. Формируем текст
    text = "📊 <b>Аналитика рынка за 1 час</b>\n\n"
    
    if gainers:
        text += "🚀 <b>ЛИДЕРЫ РОСТА:</b>\n"
        for name, curr, old, perc in gainers:
            if perc <= 0: break # Если роста нет, не выводим
            text += f"📦 {html.escape(name)}\n└ 📈 <b>+{perc:.2f}%</b> ({old}G ➔ {curr}G)\n"
    
    text += "\n"
    
    if losers:
        text += "📉 <b>ЛИДЕРЫ ПАДЕНИЯ:</b>\n"
        for name, curr, old, perc in losers:
            if perc >= 0: break # Если падения нет, не выводим
            text += f"📦 {html.escape(name)}\n└ 📉 <b>{perc:.2f}%</b> ({old}G ➔ {curr}G)\n"

    kb = InlineKeyboardBuilder().button(text="🔙 В меню", callback_data="start_menu").as_markup()
    await message.answer(text, reply_markup=kb)

@router.callback_query(F.data.startswith("buy_"))
async def pay_info(callback: types.CallbackQuery, state: FSMContext):
    # 1. ЗАЩИТА: Мгновенный ответ с перехватом ошибки "query is too old"
    try:
        await callback.answer()
    except Exception:
        pass # Если кнопка устарела, просто продолжаем логику

    try:
        # Парсим данные из callback_data
        parts = callback.data.split("_")
        if len(parts) < 3:
            return
            
        days = int(parts[1])
        price = int(parts[2])
        
        # 2. Сохраняем данные в стейт
        await state.update_data(chosen_days=days, final_price=price)
        
        # Клавиатура "Назад"
        kb = InlineKeyboardBuilder()
        kb.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="start_menu"))
        markup = kb.as_markup()
        
        # Текст оплаты
        text = (
            f"💳 <b>Оплата подписки на {days} {plural_days(days)}</b>\n\n"
            f"Сумма к оплате: <b>{price}₽</b>\n"
            f"Реквизиты (СБП): <code>+79626994725</code> (Альфа Банк)\n\n"
            "📸 <b>Отправьте СКРИНШОТ чека прямо в этот чат.</b>\n"
            "<i>После проверки админом вы получите ключ.</i>"
        )
        
        # 3. БРОНЕБОЙНОЕ обновление интерфейса
        try:
            # Проверяем тип контента сообщения (можно ли его редактировать в текст)
            if callback.message.content_type == types.ContentType.TEXT:
                await callback.message.edit_text(text, reply_markup=markup)
            else:
                # Если в сообщении было медиа (например, список тарифов с картинкой) - шлем новое
                await callback.message.answer(text, reply_markup=markup)
                try:
                    await callback.message.delete()
                except Exception:
                    pass
        except TelegramBadRequest as e:
            # Если "message is not modified" (юзер кликнул дважды) - игнорим
            if "message is not modified" not in e.message:
                # В любой другой ситуации шлем новое сообщение
                await callback.message.answer(text, reply_markup=markup)

        # 4. Устанавливаем состояние ожидания скриншота
        await state.set_state(BotStates.waiting_for_screenshot)

    except (ValueError, IndexError, Exception) as e:
        logging.error(f"🚨 Ошибка в pay_info для {callback.from_user.id}: {e}")
        await callback.message.answer("❌ Произошла ошибка при выборе тарифа. Попробуйте /start")

# --- ШАГ 5: ОДОБРЕНИЕ АДМИНОМ (ТВОЙ CREATE_RANDOM_KEY) ---
@router.callback_query(F.data.startswith("adm_ok_"))
async def admin_confirm_pay(callback: types.CallbackQuery):
    # 1. Отвечаем кнопке сразу, чтобы убрать «часики»
    await callback.answer()
    
    try:
        parts = callback.data.split("_")
        u_id = int(parts[2])
        u_days = int(parts[3])

        # 2. Генерируем ключ
        new_key = await create_random_key(u_days) 
        safe_key = html.escape(new_key) # Экранируем на случай спецсимволов в ключе

        # 3. Отправляем пользователю (try/except на случай, если бот в блоке)
        try:
            await bot.send_message(
                u_id, 
                f"🎉 <b>Оплата подтверждена!</b>\n"
                f"Ваш ключ на {u_days} {plural_days(u_days)}:\n"
                f"<code>{safe_key}</code>\n\n"
                f"Активируйте его кнопкой в меню!"
            )
            delivery_status = "отправлен"
        except Exception:
            delivery_status = "НЕ доставлен (блок)"

        # 4. Обновляем инфо у админа (защита от Bad Request: message is not modified)
        new_caption = f"{callback.message.caption}\n\n✅ <b>ОДОБРЕНО. Ключ {delivery_status}.</b>\n<code>{safe_key}</code>"
        
        try:
            await callback.message.edit_caption(caption=new_caption)
        except TelegramBadRequest:
            pass # Если другой админ уже нажал — просто игнорируем ошибку

    except (IndexError, ValueError) as e:
        logging.error(f"Ошибка в данных админ-кнопки: {e}")


async def backup_scheduler():
    """Фоновая задача: проверяет изменения раз в 5 минут"""
    print("⏰ Таймер бэкапа запущен (интервал 5 мин)...")
    while True:
        await asyncio.sleep(300) # 300 секунд = 5 минут
        import database
        await database.backup_to_github()

async def main() -> None:
    # --- ШАГ 0: ТОЛЬКО НУЖНЫЕ ИМПОРТЫ ---
    from aiogram import Dispatcher, Bot
    from aiogram.client.default import DefaultBotProperties

    print("🌐 Запуск бота в стандартном режиме...")
    
    # --- 1. Настройка  ---
    try:
        from redis.asyncio import Redis
        r_client = Redis(host='localhost', port=6379)
        storage = RedisStorage.from_url(redis_url)
        print("✅ Redis подключен.")
    except Exception as e:
        print(f"❌ Ошибка Redis: {e}. Использую память.")
        from aiogram.fsm.storage.memory import MemoryStorage
        storage = MemoryStorage()

    # --- 2. Создаем Диспетчер и подключаем Роутер ---
    dp = Dispatcher(storage=storage)
    dp.include_router(router) 
    
    # --- 3. Создаем бота (БЕЗ ПРОКСИ И СЛОЖНЫХ СЕССИЙ) ---
    global bot
    # Твоя новая ссылка из Google (замени на свою!)
    # 1. Твой полный секрет (с dd в начале)

    from aiogram.client.telegram import TelegramAPIServer

    # Твоя ссылка из Google
    google_url = "https://script.google.com/macros/s/AKfycbyVxBGIT2oncPmPBeYOfRfFTnyoFYJWeqUT4xiXEv1nchlNpV8CLHR-pYAG0gDs_9Ef7w/exec"
    
    # Используем нашу новую "умную" сессию
    session = OrjsonProxySession(google_url=google_url)
    
    bot = Bot(
        token=TOKEN, 
        session=session,
        default=DefaultBotProperties(parse_mode="HTML")
    )
    # --- 4. ЗАПУСК ---
    print("🛠 Инициализация базы данных и кэша...")
    await init_db()
    
    from database import load_items_to_cache
    await load_items_to_cache() 
    
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        
        # Получаем данные о боте вручную
        user = await bot.get_me()
        bot_user = user.result if hasattr(user, 'result') else user
        print("🚀 БОТ ЗАПУЩЕН! Напиши /start в Telegram")
        
        asyncio.create_task(global_monitor())
        asyncio.create_task(backup_scheduler())
        
        # Запускаем поллинг (handle_as_tasks=True поможет избежать некоторых ошибок)
        await dp.start_polling(bot, skip_updates=True, handle_as_tasks=True)
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        print("\n⏳ Завершаю работу...")
        if bot.session:
            await bot.session.close()
            
        from database import db_conn
        from parser import close_session
        if db_conn:
            await db_conn.close()
            print("📁 База закрыта.")
        await close_session()
        
        # Очистка фоновых задач
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        print("👋 Бот выключен. Терминал свободен!")

async def global_monitor():
    """Фоновый процесс: проверяет базу каждую минуту и шлет отчеты"""
    from aiogram.exceptions import TelegramBadRequest
    print("📊 Фоновый мониторинг запущен и следит за ценами...")
    
    while True:
        try:
            db_conn = await get_db()
            now = datetime.now()

            async with db_conn.execute("SELECT * FROM monitoring") as cursor:
                rows = await cursor.fetchall()

            for row in rows:
                # Распаковка параметров из твоей таблицы
                m_id, u_id, i_id, name, t_down, t_up, last_p, interval, n_check = row
                

                async with parse_limit:
                    new_p = await get_actual_price(name)
                    await asyncio.sleep(0.2)
                
                if not new_p: continue

                # 1. Проверка времени (Интервал)
                is_time = False
                if interval > 0 and n_check:
                    try:
                        check_time = datetime.fromisoformat(n_check)
                        if now >= check_time:
                            is_time = True
                    except Exception: pass

                # 2. Проверка порогов (Скачки)
                perc = ((new_p - last_p) / last_p * 100) if last_p > 0 else 0
                is_threshold = perc <= -t_down or perc >= t_up

                # ГЛАВНОЕ УСЛОВИЕ: Шлем отчет, если сработал порог ИЛИ пришло время И цена изменилась
                # Это уберет спам сообщениями "0.00%" каждую минуту
                if is_threshold or (is_time and abs(perc) > 0):
                    try:
                        status = "📉 упал" if perc < 0 else "📈 вырос"
                        reason = "⏱ Плановый отчет" if is_time and not is_threshold else f"🚨 Цена {status}"
                        
                        text = (
                            f"📦 <b>{html.escape(name)}</b>\n"
                            f"💰 <code>{last_p}G</code> ➔ <b>{new_p}G</b>\n"
                            f"📊 Изменение: <b>{perc:.2f}%</b>\n"
                            f"ℹ️ {reason}"
                        )
                        
                        # Кнопка остановки прямо в сообщении
                        stop_kb = InlineKeyboardBuilder().button(
                            text="🛑 Остановить", callback_data=f"del_monit_{m_id}"
                        ).as_markup()

                        # ОТПРАВКА С ЗАЩИТОЙ
                        try:
                            await bot.send_message(u_id, text, reply_markup=stop_kb)
                        except TelegramBadRequest as e:
                            if "message is not modified" in e.message:
                                pass # Игнорируем, если контент не изменился
                            else: raise e

                        # ОБНОВЛЯЕМ БАЗУ (ставим новую цену и время следующего отчета)
                        new_next = (now + timedelta(minutes=interval)).isoformat() if interval > 0 else n_check
                        await db_conn.execute(
                            "UPDATE monitoring SET last_price = ?, next_check = ? WHERE id = ?",
                            (new_p, new_next, m_id)
                        )
                        await db_conn.commit()
                        database.db_changed = True

                    except Exception as e:
                        if "forbidden" in str(e).lower() or "chat not found" in str(e).lower():
                            await db_conn.execute("DELETE FROM monitoring WHERE user_id = ?", (u_id,))
                            await db_conn.commit()
                            database.db_changed = True
                        else:
                            logging.error(f"Ошибка отправки сообщения юзеру {u_id}: {e}")
                
                # Если время вышло, но цена НЕ изменилась (0.00%) — просто переносим "будильник" на следующую минуту
                elif is_time:
                    new_next = (now + timedelta(minutes=interval)).isoformat()
                    await db_conn.execute("UPDATE monitoring SET next_check = ? WHERE id = ?", (new_next, m_id))
                    await db_conn.commit()
                    database.db_changed = True

        except Exception as e:
            logging.error(f"Ошибка в global_monitor: {e}")
        
        await asyncio.sleep(60) # Проверка раз в минуту

if __name__ == "__main__":
    import sys
    import asyncio

    # 🏎️ УСКОРИТЕЛЬ LINUX (теперь это комментарий, мешать не будет)
    if sys.platform != 'win32':
        try:
            import uvloop
            asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
            print("⚡ uvloop активирован: Максимальный форсаж!")
        except ImportError:
            print("ℹ️ uvloop не найден.")

    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)


        

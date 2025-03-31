import logging
import openai
import pandas as pd
from aiogram import Bot, Dispatcher, executor, types
from fuzzywuzzy import process
import os
from datetime import datetime
import sqlite3
import re

# --- CONFIGURATION ---
API_TOKEN = os.getenv("TG_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_KEY")
ADMIN_CHANNEL = os.getenv("ADMIN_CHANNEL", "@your_channel")
ADMIN_IDS = [int(uid) for uid in os.getenv("ADMIN_IDS", "123456789").split(",")]

openai.api_key = OPENAI_API_KEY

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)
logging.basicConfig(level=logging.INFO)

# --- DATABASE ---
conn = sqlite3.connect("database.db")
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    data TEXT,
    timestamp TEXT,
    status TEXT DEFAULT 'новая'
)
""")
conn.commit()

# --- LOAD PRICE LIST ---
price_df = pd.read_excel("Прайс для Эликс-2.xlsx")

# --- KEYBOARDS ---
main_kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
main_kb.add("1️⃣ Получить результаты", "2️⃣ Посчитать стоимость")
main_kb.add("3️⃣ Онлайн-консультация", "4️⃣ Техподдержка")

consult_kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
consult_kb.add("👩‍⚕️ Врач", "🧠 Эликс-ИИ", "👩‍💼 Администратор")
consult_kb.add("🔙 Назад")

consent_kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
consent_kb.add("✅ Согласен", "🔙 Назад")

# --- START ---
@dp.message_handler(commands=['start'])
async def start(msg: types.Message):
    await msg.answer("Привет! Я Эликс — умный бот-помощник Helix.\nГотов помочь с анализами и рекомендациями.", reply_markup=main_kb)

# --- SECTION 1: Получить результаты ---
@dp.message_handler(lambda msg: msg.text.startswith("1️⃣"))
async def request_consent(msg: types.Message):
    await msg.answer("Перед продолжением необходимо согласие на обработку ПДн.", reply_markup=consent_kb)

@dp.message_handler(lambda msg: msg.text == "✅ Согласен")
async def ask_user_data(msg: types.Message):
    await msg.answer("Введите ваши данные в формате:\nФИО, дата рождения, телефон")

@dp.message_handler(lambda msg: "," in msg.text and len(msg.text.split(",")) == 3)
async def save_request(msg: types.Message):
    timestamp = datetime.now().isoformat()
    cursor.execute("INSERT INTO requests (user_id, data, timestamp) VALUES (?, ?, ?)", (msg.from_user.id, msg.text.strip(), timestamp))
    conn.commit()
    req_id = cursor.lastrowid
    await bot.send_message(ADMIN_CHANNEL, f"📥 Заявка #{req_id} ({timestamp[:16]}):\n{msg.text.strip()}")
    await msg.reply(f"✅ Ваша заявка принята! Номер: #{req_id}")

# --- SECTION 2: Стоимость анализов ---
def search_tests(query):
    matches = []
    for test in query.split(","):
        match, score = process.extractOne(test.strip(), price_df['Название анализа'])
        if score > 60:
            row = price_df[price_df['Название анализа'] == match].iloc[0]
            matches.append((match, row['Цена']))
    return matches

@dp.message_handler(lambda msg: msg.text.startswith("2️⃣"))
async def ask_tests(msg: types.Message):
    await msg.answer("Напишите список анализов через запятую (например: ОАК, ТТГ, витамин D)")

@dp.message_handler(lambda msg: any(x in msg.text.lower() for x in ["оак", "ттг", "анализ", "витамин"]))
async def handle_tests(msg: types.Message):
    results = search_tests(msg.text)
    if not results:
        await msg.reply("Не удалось найти анализы. Попробуйте точнее.")
        return
    total = sum(price for _, price in results)
    text = "\n".join([f"🧾 {name} — {price} ₽" for name, price in results])
    await msg.reply(f"{text}\n\n💰 Итого: {total} ₽")

# --- SECTION 3: Консультация ---
@dp.message_handler(lambda msg: msg.text.startswith("3️⃣"))
async def consult_menu(msg: types.Message):
    await msg.answer("Выберите способ консультации:", reply_markup=consult_kb)

@dp.message_handler(lambda msg: msg.text == "👩‍⚕️ Врач")
async def consult_doctor(msg: types.Message):
    await msg.reply("Заявка на врача отправлена.")
    await bot.send_message(ADMIN_CHANNEL, f"📥 Врач: @{msg.from_user.username or msg.from_user.id}")

@dp.message_handler(lambda msg: msg.text == "👩‍💼 Администратор")
async def consult_admin(msg: types.Message):
    await msg.reply("Заявка администратору отправлена.")
    await bot.send_message(ADMIN_CHANNEL, f"📥 Админ: @{msg.from_user.username or msg.from_user.id}")

@dp.message_handler(lambda msg: msg.text == "🧠 Эликс-ИИ")
async def consult_ai(msg: types.Message):
    await msg.reply("Задайте свой вопрос. Например:\n«Мне 32 и ТТГ 36 — это нормально?»")

@dp.message_handler(lambda msg: "ттг" in msg.text.lower() or "что делать" in msg.text.lower())
async def ai_reply(msg: types.Message):
    prompt = f"Пациент спрашивает: {msg.text}\nОтветь кратко, без диагноза, но по сути."
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "system", "content": "Ты медицинский ассистент без права ставить диагноз."},
                      {"role": "user", "content": prompt}]
        )
        reply = response.choices[0].message.content
        await msg.reply(reply)
    except:
        await msg.reply("⚠️ Ошибка при обращении к ИИ. Попробуйте позже.")

# --- SECTION 4: Техподдержка ---
@dp.message_handler(lambda msg: msg.text.startswith("4️⃣"))
async def support(msg: types.Message):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("Написать Екатерине", url="https://t.me/ekaterina_username"))
    await msg.answer("Что-то пошло не так?", reply_markup=kb)

# --- BACK ---
@dp.message_handler(lambda msg: msg.text == "🔙 Назад")
async def back(msg: types.Message):
    await msg.answer("Возвращаю вас в главное меню 👇", reply_markup=main_kb)

# --- RUN ---
if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)

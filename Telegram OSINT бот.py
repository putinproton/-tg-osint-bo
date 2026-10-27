#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TG OSINT Bot — анализ номера телефона по публичным источникам.

Запуск:
    export BOT_TOKEN="123456:ABC-DEF..."
    python bot.py

Зависимости:
    pip install pyTelegramBotAPI phonenumbers
"""

import os
import re
import time
import logging
from collections import defaultdict

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import phonenumbers
from phonenumbers import geocoder, carrier, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# ==================== КОНФИГ ====================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise SystemExit("Не задан BOT_TOKEN. Выполни: export BOT_TOKEN='123:ABC'")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

REGIONS = ["RU", "UA", "KZ", "BY", "US", "GB", "DE", "FR", "PL", "TR", "IL", "AE"]
RATE_LIMIT_SECONDS = 5

_last_call = defaultdict(float)

TYPE_MAP = {
    phonenumbers.PhoneNumberType.MOBILE: "мобильный",
    phonenumbers.PhoneNumberType.FIXED_LINE: "стационарный",
    phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE: "стационарный / мобильный",
    phonenumbers.PhoneNumberType.TOLL_FREE: "бесплатный (800)",
    phonenumbers.PhoneNumberType.VOIP: "VoIP",
    phonenumbers.PhoneNumberType.PREMIUM_RATE: "премиум",
    phonenumbers.PhoneNumberType.SHARED_COST: "shared cost",
    phonenumbers.PhoneNumberType.PERSONAL_NUMBER: "персональный",
    phonenumbers.PhoneNumberType.PAGER: "пейджер",
    phonenumbers.PhoneNumberType.UAN: "UAN",
    phonenumbers.PhoneNumberType.VOICEMAIL: "голосовая почта",
    phonenumbers.PhoneNumberType.UNKNOWN: "неизвестно",
}

HELP_TEXT = (
    "📱 <b>Phone OSINT Bot</b>\n\n"
    "Отправь номер телефона — получишь разбор по публичным данным:\n"
    "• страна, регион, оператор, тип линии, часовой пояс\n"
    "• ссылки на мессенджеры и поисковики\n\n"
    "Формат любой: <code>+79991234567</code>, "
    "<code>89991234567</code>, <code>+380 50 123 45 67</code>\n\n"
    "Команды:\n"
    "/start — приветствие\n"
    "/help — эта справка\n"
    "/about — что внутри и ограничения"
)

ABOUT_TEXT = (
    "⚙️ <b>Как это работает</b>\n\n"
    "Бот разбирает номер библиотекой <code>phonenumbers</code> "
    "(данные Google libphonenumber) и генерирует ссылки для ручной проверки.\n\n"
    "<b>Что доступно:</b>\n"
    "✅ геоданные и оператор по префиксу\n"
    "✅ ссылки на мессенджеры и поисковики\n\n"
    "<b>Что недоступно:</b>\n"
    "❌ ФИО, адрес, паспорт\n"
    "❌ история звонков и SMS\n"
    "❌ геолокация в реальном времени\n"
    "Это закрытые данные оператора — только по решению суда.\n\n"
    "Бот работает исключительно с публичными источниками."
)


# ==================== ЛОГИКА ====================

def find_number(text):
    """Пытается распарсить номер из произвольного текста."""
    digits = re.sub(r"\D", "", text)

    if len(digits) < 10 or len(digits) > 17:
        return None

    # Пробуем с подсказкой региона
    for region in REGIONS:
        try:
            candidate = phonenumbers.parse("+" + digits, region)
        except phonenumbers.NumberParseException:
            continue
        if phonenumbers.is_valid_number(candidate):
            return candidate

    # Последняя попытка — без региона
    try:
        candidate = phonenumbers.parse("+" + digits, None)
        if phonenumbers.is_possible_number(candidate):
            return candidate
    except phonenumbers.NumberParseException:
        pass

    return None


def esc(value):
    """Экранирование под HTML parse_mode."""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def build_report(n):
    """Текст отчёта."""
    intl = phonenumbers.format_number(n, phonenumbers.International)
    national = phonenumbers.format_number(n, phonenumbers.National)
    e164 = phonenumbers.format_number(n, phonenumbers.E164)

    country = geocoder.country_name_for_number(n, "ru") or "неизвестно"
    region_code = phonenumbers.region_code_for_number(n) or "??"
    area = geocoder.description_for_number(n, "ru") or "—"
    operator = carrier.name_for_number(n, "ru") or "не определён"
    zones = ", ".join(timezone.time_zones_for_number(n)) or "—"
    line_type = TYPE_MAP.get(phonenumbers.number_type(n), "неизвестно")
    valid = "да" if phonenumbers.is_valid_number(n) else "нет"

    return (
        "📱 <b>Результат анализа</b>\n\n"
        f"<b>Международный:</b> <code>{esc(intl)}</code>\n"
        f"<b>Национальный:</b> <code>{esc(national)}</code>\n"
        f"<b>E.164:</b> <code>{esc(e164)}</code>\n\n"
        f"🌍 <b>Страна:</b> {esc(country)} ({esc(region_code)})\n"
        f"📍 <b>Регион:</b> {esc(area)}\n"
        f"📡 <b>Оператор:</b> {esc(operator)}\n"
        f"☎️ <b>Тип линии:</b> {esc(line_type)}\n"
        f"🕐 <b>Часовой пояс:</b> {esc(zones)}\n"
        f"✅ <b>Валидный:</b> {esc(valid)}\n\n"
        "👇 Кнопки ниже — для ручной проверки в открытых источниках."
    )


def build_keyboard(n):
    """Инлайн-клавиатура со ссылками."""
    e164 = phonenumbers.format_number(n, phonenumbers.E164)
    digits = e164.lstrip("+")
    quoted = f"%22{e164}%22"

    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🔍 Google", url=f"https://www.google.com/search?q={quoted}"),
        InlineKeyboardButton("🔍 Яндекс", url=f"https://yandex.ru/search/?text={quoted}"),
        InlineKeyboardButton("🛒 Avito", url=f"https://www.avito.ru/all?q={digits}"),
        InlineKeyboardButton("👤 VK", url=f"https://vk.com/search?c%5Bq%5D={digits}"),
        InlineKeyboardButton("📞 Truecaller", url=f"https://www.truecaller.com/search/ru/{digits}"),
        InlineKeyboardButton("✈️ Telegram", url=f"https://t.me/+{digits}"),
    )
    return kb


# ==================== ХЕНДЛЕРЫ ====================

@bot.message_handler(commands=["start"])
def cmd_start(message):
    bot.send_message(message.chat.id, HELP_TEXT)


@bot.message_handler(commands=["help"])
def cmd_help(message):
    bot.send_message(message.chat.id, HELP_TEXT)


@bot.message_handler(commands=["about"])
def cmd_about(message):
    bot.send_message(message.chat.id, ABOUT_TEXT)


@bot.message_handler(content_types=["text"])
def handle_text(message):
    user_id = message.from_user.id

    # Простейший антифлуд
    now = time.time()
    if now - _last_call[user_id] < RATE_LIMIT_SECONDS:
        bot.reply_to(message, "⏳ Слишком часто. Подожди пару секунд.")
        return
    _last_call[user_id] = now

    number = find_number(message.text or "")

    if number is None:
        bot.reply_to(
            message,
            "❓ Не похоже на номер телефона.\n"
            "Пример: <code>+79991234567</code>",
        )
        return

    try:
        bot.send_chat_action(message.chat.id, "typing")
        bot.reply_to(message, build_report(number), reply_markup=build_keyboard(number))
        logging.info("Обработан номер %s (user %s)", number, user_id)
    except Exception as exc:  # noqa: BLE001
        logging.exception("Ошибка обработки")
        bot.reply_to(message, f"⚠️ Ошибка: <code>{esc(exc)}</code>")


# ==================== ЗАПУСК ====================

if __name__ == "__main__":
    logging.info("Бот запущен, ожидаю сообщения...")
    bot.infinity_polling(timeout=30, long_polling_timeout=25)

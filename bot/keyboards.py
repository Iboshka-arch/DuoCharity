from telebot import types


def phone_request_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton("📱 Поделиться номером / Raqamni ulashish", request_contact=True))
    return markup


def language_keyboard():
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("🇺🇿 O'zbekcha", callback_data="lang_uz"),
        types.InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru"),
    )
    return markup


def car_question_keyboard(lang="ru"):
    from bot.translations import bt
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(bt("car_yes", lang), callback_data="car_yes"),
        types.InlineKeyboardButton(bt("car_no", lang), callback_data="car_no"),
    )
    return markup


def car_confirm_keyboard(lang="ru"):
    from bot.translations import bt
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(bt("car_yes", lang), callback_data="car_confirm_yes"),
        types.InlineKeyboardButton(bt("car_no", lang), callback_data="car_confirm_no"),
    )
    return markup


def language_change_keyboard():
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("🇺🇿 O'zbekcha", callback_data="setlang_uz"),
        types.InlineKeyboardButton("🇷🇺 Русский", callback_data="setlang_ru"),
    )
    return markup
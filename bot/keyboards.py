from telebot import types


def phone_request_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton("Поделиться номером телефона", request_contact=True))
    return markup


def car_question_keyboard():
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("Да", callback_data="car_yes"),
        types.InlineKeyboardButton("Нет", callback_data="car_no"),
    )
    return markup
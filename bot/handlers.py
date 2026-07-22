import telebot
from telebot import types

from bot.config import BOT_TOKEN
from bot.keyboards import phone_request_keyboard, car_question_keyboard, language_keyboard
from bot.translations import bt
from models import db, Volunteer, VolunteerApplication

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)

VOLUNTEER_FORM_URL = "https://duo-charity.vercel.app/volunteer-form"


def normalize_phone(raw):
    digits = "".join(ch for ch in raw if ch.isdigit())
    return digits[-9:] if len(digits) >= 9 else digits


@bot.message_handler(commands=["start"])
def handle_start(message):
    bot.send_message(message.chat.id, bt("start_greeting", "ru"), reply_markup=phone_request_keyboard())


@bot.message_handler(content_types=["contact"])
def handle_contact(message):
    contact = message.contact

    if contact.user_id != message.from_user.id:
        bot.send_message(message.chat.id, bt("own_contact_only", "ru"))
        return

    phone = normalize_phone(contact.phone_number)

    volunteer = Volunteer.query.filter_by(phone=phone).first()
    if volunteer:
        if volunteer.telegram_chat_id and volunteer.pending_action != "awaiting_language":
            lang = volunteer.language or "ru"
            bot.send_message(message.chat.id, bt("matched", lang, name=volunteer.full_name), reply_markup=types.ReplyKeyboardRemove())
            return

        volunteer.telegram_user_id = message.from_user.id
        volunteer.telegram_chat_id = message.chat.id
        volunteer.pending_action = "awaiting_language"
        db.session.commit()

        bot.send_message(message.chat.id, bt("choose_language"), reply_markup=language_keyboard())
        return

    application = (
        VolunteerApplication.query
        .filter_by(phone=phone)
        .filter(VolunteerApplication.status != "closed")
        .order_by(VolunteerApplication.created_at.desc())
        .first()
    )

    if application:
        application.telegram_user_id = message.from_user.id
        application.telegram_chat_id = message.chat.id
        application.pending_action = "awaiting_language"
        db.session.commit()

        bot.send_message(message.chat.id, bt("pending_review"), reply_markup=language_keyboard())
        return

    bot.send_message(
        message.chat.id,
        bt("not_matched", "ru", form_link=VOLUNTEER_FORM_URL),
        reply_markup=types.ReplyKeyboardRemove(),
    )


@bot.callback_query_handler(func=lambda call: call.data in ("lang_uz", "lang_ru"))
def handle_language_choice(call):
    bot.answer_callback_query(call.id)
    lang = "uz" if call.data == "lang_uz" else "ru"

    volunteer = Volunteer.query.filter_by(telegram_chat_id=call.message.chat.id, pending_action="awaiting_language").first()
    if volunteer:
        volunteer.language = lang
        volunteer.pending_action = None
        db.session.commit()

        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        bot.send_message(call.message.chat.id, bt("matched", lang, name=volunteer.full_name))

        if volunteer.has_car is None:
            bot.send_message(call.message.chat.id, bt("ask_car", lang), reply_markup=car_question_keyboard(lang))
        return

    application = VolunteerApplication.query.filter_by(telegram_chat_id=call.message.chat.id, pending_action="awaiting_language").first()
    if application:
        application.language = lang
        application.pending_action = None
        db.session.commit()

        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        bot.send_message(call.message.chat.id, bt("pending_confirmed", lang))
        return

    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)


@bot.callback_query_handler(func=lambda call: call.data in ("car_yes", "car_no"))
def handle_car_answer(call):
    volunteer = Volunteer.query.filter_by(telegram_chat_id=call.message.chat.id).first()
    bot.answer_callback_query(call.id)

    if not volunteer:
        return

    if volunteer.has_car is not None:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        return

    lang = volunteer.language or "ru"
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)

    if call.data == "car_yes":
        volunteer.has_car = True
        volunteer.pending_action = "awaiting_car_brand"
        db.session.commit()
        bot.send_message(call.message.chat.id, bt("ask_car_brand", lang))
    else:
        volunteer.has_car = False
        volunteer.pending_action = None
        db.session.commit()
        bot.send_message(call.message.chat.id, bt("car_declined", lang))


@bot.message_handler(content_types=["text"])
def handle_text(message):
    volunteer = Volunteer.query.filter_by(telegram_chat_id=message.chat.id).first()
    lang = volunteer.language if volunteer and volunteer.language else "ru"

    if volunteer and volunteer.pending_action == "awaiting_car_brand":
        volunteer.car_brand = message.text.strip()
        volunteer.pending_action = "awaiting_car_plate"
        db.session.commit()
        bot.send_message(message.chat.id, bt("ask_car_plate", lang))
        return

    if volunteer and volunteer.pending_action == "awaiting_car_plate":
        volunteer.car_plate = message.text.strip()
        volunteer.pending_action = None
        db.session.commit()
        bot.send_message(message.chat.id, bt("car_saved", lang))
        return

    bot.send_message(message.chat.id, bt("fallback", lang))
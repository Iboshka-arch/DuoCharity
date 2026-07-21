import telebot
from telebot import types

from bot.config import BOT_TOKEN
from bot.keyboards import phone_request_keyboard, car_question_keyboard
from models import db, Volunteer

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)


def normalize_phone(raw):
    digits = "".join(ch for ch in raw if ch.isdigit())
    return digits[-9:] if len(digits) >= 9 else digits


@bot.message_handler(commands=["start"])
def handle_start(message):
    bot.send_message(
        message.chat.id,
        "Здравствуйте! Чтобы бот мог присылать вам уведомления, поделитесь, пожалуйста, своим номером телефона.",
        reply_markup=phone_request_keyboard(),
    )


@bot.message_handler(content_types=["contact"])
def handle_contact(message):
    contact = message.contact

    if contact.user_id != message.from_user.id:
        bot.send_message(message.chat.id, "Пожалуйста, поделитесь своим собственным номером телефона.")
        return

    phone = normalize_phone(contact.phone_number)
    volunteer = Volunteer.query.filter_by(phone=phone).first()

    if not volunteer:
        bot.send_message(
            message.chat.id,
            "Не нашли ваш номер в списке действующих волонтёров DUO Charity. "
            "Если вы подавали заявку и она была принята, напишите @Duo_charity_admin.",
            reply_markup=types.ReplyKeyboardRemove(),
        )
        return

    volunteer.telegram_user_id = message.from_user.id
    volunteer.telegram_chat_id = message.chat.id
    db.session.commit()

    bot.send_message(
        message.chat.id,
        f"Спасибо, {volunteer.full_name}! Вы успешно подключены к уведомлениям DUO Charity.",
        reply_markup=types.ReplyKeyboardRemove(),
    )

    if volunteer.has_car is None:
        bot.send_message(
            message.chat.id,
            "Есть ли у вас личный автомобиль, который можно использовать для перевозки продуктов и вещей?",
            reply_markup=car_question_keyboard(),
        )


@bot.callback_query_handler(func=lambda call: call.data in ("car_yes", "car_no"))
def handle_car_answer(call):
    volunteer = Volunteer.query.filter_by(telegram_chat_id=call.message.chat.id).first()

    if not volunteer:
        bot.answer_callback_query(call.id)
        return

    bot.answer_callback_query(call.id)

    if call.data == "car_yes":
        volunteer.has_car = True
        volunteer.pending_action = "awaiting_car_plate"
        db.session.commit()
        bot.send_message(call.message.chat.id, "Отлично! Напишите, пожалуйста, номер автомобиля.")
    else:
        volunteer.has_car = False
        volunteer.pending_action = None
        db.session.commit()
        bot.send_message(call.message.chat.id, "Понял, спасибо за информацию!")


@bot.message_handler(content_types=["text"])
def handle_text(message):
    volunteer = Volunteer.query.filter_by(telegram_chat_id=message.chat.id).first()

    if volunteer and volunteer.pending_action == "awaiting_car_plate":
        volunteer.car_plate = message.text.strip()
        volunteer.pending_action = None
        db.session.commit()
        bot.send_message(message.chat.id, "Номер автомобиля сохранён. Спасибо!")
        return

    bot.send_message(
        message.chat.id,
        "Я пока умею только регистрировать волонтёров. Если нужна помощь — напишите @Duo_charity_admin.",
    )
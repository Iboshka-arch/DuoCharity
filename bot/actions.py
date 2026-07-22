from telebot import types

from bot.handlers import bot
from bot.translations import bt
from bot.keyboards import car_question_keyboard
from models import db, Volunteer


def accept_application(application):
    existing = Volunteer.query.filter_by(phone=application.phone).first()
    if existing:
        return existing, False

    volunteer = Volunteer(
        full_name=application.full_name,
        phone=application.phone,
        telegram=application.telegram,
        gender=application.gender,
        age=application.age,
        occupation=application.occupation,
        telegram_user_id=application.telegram_user_id,
        telegram_chat_id=application.telegram_chat_id,
        language=application.language,
    )
    db.session.add(volunteer)
    application.status = "closed"
    db.session.commit()

    if volunteer.telegram_chat_id:
        lang = volunteer.language or "ru"
        try:
            bot.send_message(volunteer.telegram_chat_id, bt("application_accepted", lang, name=volunteer.full_name))
            if volunteer.has_car is None:
                bot.send_message(volunteer.telegram_chat_id, bt("ask_car", lang), reply_markup=car_question_keyboard(lang))
        except Exception as e:
            print(f"Не удалось уведомить волонтёра: {e}")

    return volunteer, True


def decline_application(application):
    application.status = "closed"
    db.session.commit()
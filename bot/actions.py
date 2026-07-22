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
    )
    db.session.add(volunteer)
    application.status = "closed"
    db.session.commit()

    if volunteer.telegram_chat_id:
        volunteer.pending_action = "awaiting_language"
        db.session.commit()
        try:
            bot.send_message(
                volunteer.telegram_chat_id,
                bt("auto_accepted_choose_language"),
                reply_markup=language_keyboard(),
            )
        except Exception as e:
            print(f"Не удалось уведомить волонтёра: {e}")

    return volunteer, True


def decline_application(application):
    application.status = "closed"
    db.session.commit()
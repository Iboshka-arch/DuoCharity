import html

from bot.handlers import bot, send_group_invite, find_and_consume_pending_telegram
from bot.utils import safe_send_message
from bot.translations import bt
from models import db, Volunteer
from activity_log import log_activity


def accept_application(application, actor):
    existing = Volunteer.query.filter_by(phone=application.phone).first()

    if existing:
        full_name = application.full_name
        db.session.delete(application)
        db.session.commit()
        log_activity(actor, "application_accept", f"{full_name} (уже был(а) в списке)")
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
    db.session.delete(application)
    db.session.commit()

    if not volunteer.telegram_chat_id:
        pending = find_and_consume_pending_telegram(volunteer.phone)
        if pending:
            volunteer.telegram_user_id = pending["user_id"]
            volunteer.telegram_chat_id = pending["chat_id"]
            volunteer.language = pending["lang"]
            db.session.commit()

    if volunteer.telegram_chat_id:
        lang = volunteer.language or "ru"
        try:
            safe_send_message(
                volunteer.telegram_chat_id,
                bt("application_accepted", lang, name=html.escape(volunteer.full_name)),
                parse_mode="HTML",
            )

            if volunteer.has_car is None:
                from bot.keyboards import car_question_keyboard
                safe_send_message(volunteer.telegram_chat_id, bt("ask_car", lang), reply_markup=car_question_keyboard(lang))
            else:
                send_group_invite(volunteer.telegram_chat_id, volunteer, lang)
        except Exception as e:
            print(f"Не удалось уведомить волонтёра: {e}")

    log_activity(actor, "application_accept", volunteer.full_name)
    return volunteer, True


def decline_application(application, actor):
    full_name = application.full_name
    db.session.delete(application)
    db.session.commit()
    log_activity(actor, "application_decline", full_name)
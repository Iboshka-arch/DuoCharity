import html

from bot.handlers import bot
from bot.utils import safe_send_message
from bot.translations import bt
from models import db, Volunteer


def accept_application(application):
    existing = Volunteer.query.filter_by(phone=application.phone).first()

    if existing:
        db.session.delete(application)
        db.session.commit()
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

    if volunteer.telegram_chat_id:
        lang = volunteer.language or "ru"
        try:
            safe_send_message(
                volunteer.telegram_chat_id,
                bt("application_accepted", lang, name=html.escape(volunteer.full_name)),
                parse_mode="HTML",
            )

            from bot.config import VOLUNTEER_GROUP_CHAT_ID
            invite = bot.create_chat_invite_link(
                int(VOLUNTEER_GROUP_CHAT_ID),
                creates_join_request=True,
                name=f"volunteer-{volunteer.id}",
            )
            safe_send_message(
                volunteer.telegram_chat_id,
                bt("group_invite", lang, link=invite.invite_link),
                parse_mode="HTML",
            )

            if volunteer.has_car is None:
                from bot.keyboards import car_question_keyboard
                safe_send_message(volunteer.telegram_chat_id, bt("ask_car", lang), reply_markup=car_question_keyboard(lang))
        except Exception as e:
            print(f"Не удалось уведомить волонтёра: {e}")

    return volunteer, True


def decline_application(application):
    db.session.delete(application)
    db.session.commit()
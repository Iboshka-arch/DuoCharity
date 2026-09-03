import html
import json

from telebot import types

from bot.handlers import bot
from bot.config import VOLUNTEER_GROUP_CHAT_ID, OWNER_CHAT_ID
from bot.translations import bt
from models import db, Event, EventRegistration, EventFeedback, VolunteerPenalty, Volunteer, ConversationDraft

_LABELS = {
    "uz": {
        "date": "🗓",
        "location": "📍",
        "seats": "👥 Joylar",
        "registered_header": "📝 Ro'yxatdagilar:",
        "none": "—",
        "drivers_header": "🚗 Haydovchilar:",
        "closed": "🔒 Ro'yxatga olish yopiq",
    },
    "ru": {
        "date": "🗓",
        "location": "📍",
        "seats": "👥 Мест",
        "registered_header": "📝 Записавшиеся:",
        "none": "—",
        "drivers_header": "🚗 Водители:",
        "closed": "🔒 Регистрация закрыта",
    },
}


def _collect_registrants(event):
    registrations = EventRegistration.query.filter_by(event_id=event.id).all()
    volunteer_ids = [r.volunteer_id for r in registrations]
    volunteers_by_id = {}
    if volunteer_ids:
        volunteers_by_id = {v.id: v for v in Volunteer.query.filter(Volunteer.id.in_(volunteer_ids)).all()}

    names = []
    drivers = []
    for r in registrations:
        v = volunteers_by_id.get(r.volunteer_id)
        if not v:
            continue
        names.append(html.escape(v.full_name))
        if v.has_car:
            drivers.append(html.escape(v.full_name))

    return names, drivers


def _build_text_for_lang(event, names, drivers, lang):
    labels = _LABELS[lang]
    count_suffix = f"{len(names)}/{event.capacity}" if event.capacity else f"{len(names)}"

    parts = [f"📅 <b>{html.escape(event.title)}</b>"]
    if event.date_text:
        parts.append(f"{labels['date']} {html.escape(event.date_text)}")
    if event.location:
        parts.append(f"{labels['location']} {html.escape(event.location)}")
    if event.description:
        parts.append("")
        parts.append(html.escape(event.description))
    parts.append("")
    parts.append(f"{labels['seats']}: {count_suffix}")
    parts.append("")
    parts.append(labels["registered_header"])
    parts.append("\n".join(f"{i + 1}. {n}" for i, n in enumerate(names)) if names else labels["none"])
    if drivers:
        parts.append("")
        parts.append(labels["drivers_header"])
        parts.append("\n".join(f"- {n}" for n in drivers))
    if event.is_closed:
        parts.append("")
        parts.append(labels["closed"])

    return "\n".join(parts)


def _build_announcement_text(event):
    """Двуязычный текст для общего объявления в группе — не трогаем без отдельного решения."""
    names, drivers = _collect_registrants(event)
    uz_text = _build_text_for_lang(event, names, drivers, "uz")
    ru_text = _build_text_for_lang(event, names, drivers, "ru")
    return f"{uz_text}\n\n〰️〰️〰️\n\n{ru_text}"


def _build_announcement_text_lang(event, lang):
    """Одноязычный текст — для личных сообщений, каждому на его языке."""
    names, drivers = _collect_registrants(event)
    return _build_text_for_lang(event, names, drivers, lang if lang in _LABELS else "uz")


def _build_registration_confirmation(event, lang):
    labels = _LABELS[lang if lang in _LABELS else "uz"]
    parts = [bt("event_registration_confirmed", lang, title=html.escape(event.title))]
    if event.date_text:
        parts.append(f"{labels['date']} {html.escape(event.date_text)}")
    if event.location:
        parts.append(f"{labels['location']} {html.escape(event.location)}")
    return "\n".join(parts)


def _event_register_keyboard(event_id, lang=None):
    if lang == "uz":
        label = "📝 Yozilish"
    elif lang == "ru":
        label = "📝 Записаться"
    else:
        label = "📝 Yozilish / Записаться"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(label, callback_data=f"event_register_{event_id}"))
    return markup


def _refresh_message(chat_id, message_id, event, lang=None):
    if not chat_id or not message_id:
        return
    text = _build_announcement_text(event) if lang is None else _build_announcement_text_lang(event, lang)
    markup = None if event.is_closed else _event_register_keyboard(event.id, lang)
    try:
        bot.edit_message_text(text, chat_id, message_id, parse_mode="HTML", reply_markup=markup)
    except Exception as e:
        print(f"Не удалось обновить сообщение о мероприятии: {e}")


def _refresh_announcement(event):
    _refresh_message(event.announcement_chat_id, event.announcement_message_id, event)


def _approval_keyboard(event_id):
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ Всё верно", callback_data=f"event_approve_{event_id}"),
        types.InlineKeyboardButton("✏️ Редактировать", callback_data=f"event_edit_{event_id}"),
    )
    return markup


def request_event_approval(event):
    if not OWNER_CHAT_ID:
        print("OWNER_CHAT_ID не задан — публикую мероприятие сразу, без проверки.")
        publish_event(event)
        return

    preview_text = "Так будет выглядеть объявление в группе волонтёров:\n\n" + _build_announcement_text(event)

    try:
        bot.send_message(
            int(OWNER_CHAT_ID),
            preview_text,
            parse_mode="HTML",
            reply_markup=_approval_keyboard(event.id),
        )
    except Exception as e:
        print(f"Не удалось отправить мероприятие на проверку владельцу: {e}")


@bot.callback_query_handler(func=lambda call: call.data.startswith("event_approve_"))
def handle_event_approve(call):
    if str(call.message.chat.id) != str(OWNER_CHAT_ID):
        bot.answer_callback_query(call.id, "Недостаточно прав.")
        return

    event_id = int(call.data.rsplit("_", 1)[1])
    event = Event.query.get(event_id)

    if not event:
        bot.answer_callback_query(call.id, "Мероприятие не найдено (возможно, уже удалено).", show_alert=True)
        return

    bot.answer_callback_query(call.id, "Публикую ✅")
    publish_event(event)

    try:
        bot.edit_message_text(
            call.message.html_text + "\n\n✅ Опубликовано волонтёрам",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=None,
            parse_mode="HTML",
        )
    except Exception as e:
        print(f"Не удалось обновить сообщение проверки: {e}")


@bot.callback_query_handler(func=lambda call: call.data.startswith("event_edit_"))
def handle_event_edit_request(call):
    if str(call.message.chat.id) != str(OWNER_CHAT_ID):
        bot.answer_callback_query(call.id, "Недостаточно прав.")
        return

    event_id = int(call.data.rsplit("_", 1)[1])
    event = Event.query.get(event_id)

    bot.answer_callback_query(call.id, "Отменено")

    if event:
        EventRegistration.query.filter_by(event_id=event.id).delete()
        EventFeedback.query.filter_by(event_id=event.id).delete()
        db.session.delete(event)
        db.session.commit()

    try:
        bot.edit_message_text(
            call.message.html_text + "\n\n✏️ Отменено — отредактируйте и создайте заново на сайте",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=None,
            parse_mode="HTML",
        )
    except Exception as e:
        print(f"Не удалось обновить сообщение проверки: {e}")


def publish_event(event):
    group_text = _build_announcement_text(event)

    try:
        msg = bot.send_message(
            int(VOLUNTEER_GROUP_CHAT_ID), group_text, parse_mode="HTML", reply_markup=_event_register_keyboard(event.id)
        )
        event.announcement_chat_id = msg.chat.id
        event.announcement_message_id = msg.message_id
        db.session.commit()
    except Exception as e:
        print(f"Не удалось опубликовать мероприятие в группе: {e}")

    for volunteer in Volunteer.query.filter(Volunteer.telegram_chat_id.isnot(None)).all():
        lang = volunteer.language or "uz"
        try:
            bot.send_message(
                volunteer.telegram_chat_id,
                _build_announcement_text_lang(event, lang),
                parse_mode="HTML",
                reply_markup=_event_register_keyboard(event.id, lang),
            )
        except Exception as e:
            print(f"Не удалось разослать мероприятие волонтёру {volunteer.id}: {e}")


def close_event_and_notify(event):
    event.is_closed = True
    db.session.commit()
    _refresh_announcement(event)

    registrations = EventRegistration.query.filter_by(event_id=event.id).all()

    for r in registrations:
        if r.status != "no_show":
            continue

        penalty = VolunteerPenalty.query.get(r.volunteer_id)
        if not penalty:
            penalty = VolunteerPenalty(volunteer_id=r.volunteer_id, no_show_count=0, suspended=False)
            db.session.add(penalty)

        penalty.no_show_count += 1
        volunteer = Volunteer.query.get(r.volunteer_id)
        lang = (volunteer.language or "uz") if volunteer else "uz"

        if penalty.no_show_count >= 2:
            penalty.suspended = True
            penalty.no_show_count = 0
            warn_key = "event_warning_2"
        else:
            warn_key = "event_warning_1"

        db.session.commit()

        if volunteer and volunteer.telegram_chat_id:
            try:
                bot.send_message(volunteer.telegram_chat_id, bt(warn_key, lang))
            except Exception as e:
                print(f"Не удалось отправить предупреждение волонтёру: {e}")

    for r in registrations:
        if r.feedback_submitted or not r.telegram_chat_id:
            continue

        volunteer = Volunteer.query.get(r.volunteer_id)
        lang = (volunteer.language or "uz") if volunteer else "uz"

        try:
            markup = types.InlineKeyboardMarkup()
            markup.add(*[types.InlineKeyboardButton("⭐" * n, callback_data=f"fbstar_{event.id}_{n}") for n in range(1, 6)])
            bot.send_message(
                r.telegram_chat_id,
                bt("event_feedback_request", lang, title=html.escape(event.title)),
                reply_markup=markup,
            )
        except Exception as e:
            print(f"Не удалось запросить отзыв: {e}")


def reopen_event(event):
    event.is_closed = False
    db.session.commit()
    _refresh_announcement(event)


@bot.callback_query_handler(func=lambda call: call.data.startswith("event_register_"))
def handle_event_register(call):
    event_id = int(call.data.rsplit("_", 1)[1])
    event = Event.query.get(event_id)

    volunteer = Volunteer.query.filter_by(telegram_user_id=call.from_user.id).first()
    lang = (volunteer.language or "uz") if volunteer else "uz"

    if not event or event.is_closed:
        bot.answer_callback_query(call.id, bt("event_closed_alert", lang), show_alert=True)
        return

    if not volunteer:
        bot.answer_callback_query(call.id, bt("event_need_start", lang), show_alert=True)
        return

    penalty = VolunteerPenalty.query.get(volunteer.id)
    if penalty and penalty.suspended:
        penalty.suspended = False
        db.session.commit()
        bot.answer_callback_query(call.id, bt("event_suspended_alert", lang), show_alert=True)
        return

    existing = EventRegistration.query.filter_by(event_id=event.id, volunteer_id=volunteer.id).first()

    if existing:
        db.session.delete(existing)
        db.session.commit()
        bot.answer_callback_query(call.id, bt("event_unregistered", lang), show_alert=True)
    else:
        if event.capacity:
            current_count = EventRegistration.query.filter_by(event_id=event.id).count()
            if current_count >= event.capacity:
                bot.answer_callback_query(call.id, bt("event_full", lang), show_alert=True)
                return
        db.session.add(
            EventRegistration(event_id=event.id, volunteer_id=volunteer.id, telegram_chat_id=volunteer.telegram_chat_id)
        )
        db.session.commit()
        bot.answer_callback_query(call.id, bt("event_registered", lang), show_alert=True)

        if volunteer.telegram_chat_id:
            try:
                bot.send_message(
                    volunteer.telegram_chat_id,
                    _build_registration_confirmation(event, lang),
                    parse_mode="HTML",
                )
            except Exception as e:
                print(f"Не удалось отправить подтверждение записи: {e}")

    _refresh_announcement(event)

    if call.message.chat.id != event.announcement_chat_id:
        _refresh_message(call.message.chat.id, call.message.message_id, event, lang=lang)


@bot.callback_query_handler(func=lambda call: call.data.startswith("fbstar_"))
def handle_feedback_star(call):
    _, event_id_str, rating_str = call.data.split("_")
    bot.answer_callback_query(call.id)
    chat_id = call.message.chat.id
    draft_data = json.dumps({"event_id": int(event_id_str), "rating": int(rating_str)})

    volunteer = Volunteer.query.filter_by(telegram_chat_id=chat_id).first()
    lang = (volunteer.language or "uz") if volunteer else "uz"

    draft = ConversationDraft.query.get(chat_id)
    if draft:
        draft.kind = "event_feedback"
        draft.state = "awaiting_comment"
        draft.data = draft_data
    else:
        db.session.add(
            ConversationDraft(telegram_chat_id=chat_id, kind="event_feedback", state="awaiting_comment", data=draft_data)
        )
    db.session.commit()

    try:
        bot.edit_message_text(bt("event_feedback_ask_comment", lang), chat_id, call.message.message_id)
    except Exception as e:
        print(f"Не удалось обновить сообщение отзыва: {e}")


def process_feedback_comment(message, draft):
    data = json.loads(draft.data or "{}")
    event_id = data.get("event_id")
    rating = data.get("rating")
    comment_text = message.text.strip()
    comment = None if comment_text == "-" else comment_text[:1000]

    db.session.add(EventFeedback(event_id=event_id, rating=rating, comment=comment))

    volunteer = Volunteer.query.filter_by(telegram_chat_id=message.chat.id).first()
    lang = (volunteer.language or "uz") if volunteer else "uz"
    if volunteer:
        reg = EventRegistration.query.filter_by(event_id=event_id, volunteer_id=volunteer.id).first()
        if reg:
            reg.feedback_submitted = True

    db.session.delete(draft)
    db.session.commit()

    bot.send_message(message.chat.id, bt("event_feedback_thanks", lang))

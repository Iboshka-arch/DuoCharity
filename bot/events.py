import html
import json

from telebot import types

from bot.handlers import bot
from bot.config import VOLUNTEER_GROUP_CHAT_ID
from models import db, Event, EventRegistration, EventFeedback, VolunteerPenalty, Volunteer, ConversationDraft


def _event_register_keyboard(event_id):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📝 Yozilish / Записаться", callback_data=f"event_register_{event_id}"))
    return markup


def _build_announcement_text(event):
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

    count_suffix = f"{len(names)}/{event.capacity}" if event.capacity else f"{len(names)}"

    parts = [f"📅 <b>{html.escape(event.title)}</b>"]
    if event.date_text:
        parts.append(f"🗓 {html.escape(event.date_text)}")
    if event.location:
        parts.append(f"📍 {html.escape(event.location)}")
    if event.description:
        parts.append("")
        parts.append(html.escape(event.description))
    parts.append("")
    parts.append(f"👥 Mest / Записалось: {count_suffix}")
    parts.append("")
    parts.append("📝 Ro'yxatdagilar / Записавшиеся:")
    parts.append("\n".join(f"{i + 1}. {n}" for i, n in enumerate(names)) if names else "—")
    if drivers:
        parts.append("")
        parts.append("🚗 Haydovchilar / Водители:")
        parts.append("\n".join(f"- {n}" for n in drivers))
    if event.is_closed:
        parts.append("")
        parts.append("🔒 Ro'yxatga olish yopiq / Регистрация закрыта")

    return "\n".join(parts)


def _refresh_message(chat_id, message_id, event):
    if not chat_id or not message_id:
        return
    text = _build_announcement_text(event)
    markup = None if event.is_closed else _event_register_keyboard(event.id)
    try:
        bot.edit_message_text(text, chat_id, message_id, parse_mode="HTML", reply_markup=markup)
    except Exception as e:
        print(f"Не удалось обновить сообщение о мероприятии: {e}")


def _refresh_announcement(event):
    _refresh_message(event.announcement_chat_id, event.announcement_message_id, event)


def publish_event(event):
    text = _build_announcement_text(event)

    try:
        msg = bot.send_message(
            int(VOLUNTEER_GROUP_CHAT_ID), text, parse_mode="HTML", reply_markup=_event_register_keyboard(event.id)
        )
        event.announcement_chat_id = msg.chat.id
        event.announcement_message_id = msg.message_id
        db.session.commit()
    except Exception as e:
        print(f"Не удалось опубликовать мероприятие в группе: {e}")

    for volunteer in Volunteer.query.filter(Volunteer.telegram_chat_id.isnot(None)).all():
        try:
            bot.send_message(
                volunteer.telegram_chat_id, text, parse_mode="HTML", reply_markup=_event_register_keyboard(event.id)
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

        if penalty.no_show_count >= 2:
            penalty.suspended = True
            penalty.no_show_count = 0
            warn_text = (
                "⚠️ 2/2. Siz ketma-ket 2 ta tadbirga kelmadingiz — keyingi ro'yxatga olish vaqtinchalik yopiladi.\n"
                "⚠️ 2/2. Вы не пришли на 2 мероприятия подряд — следующая запись будет временно недоступна."
            )
        else:
            warn_text = (
                "⚠️ 1/2. Siz tadbirga kelmadingiz.\n"
                "⚠️ 1/2. Вы не пришли на мероприятие."
            )

        db.session.commit()

        if volunteer and volunteer.telegram_chat_id:
            try:
                bot.send_message(volunteer.telegram_chat_id, warn_text)
            except Exception as e:
                print(f"Не удалось отправить предупреждение волонтёру: {e}")

    for r in registrations:
        if r.feedback_submitted or not r.telegram_chat_id:
            continue
        try:
            markup = types.InlineKeyboardMarkup()
            markup.add(*[types.InlineKeyboardButton("⭐" * n, callback_data=f"fbstar_{event.id}_{n}") for n in range(1, 6)])
            bot.send_message(
                r.telegram_chat_id,
                f"Tadbir \"{html.escape(event.title)}\" yakunlandi. Uni 1 dan 5 gacha baholang (izoh ixtiyoriy, anonim).\n"
                f"Мероприятие \"{html.escape(event.title)}\" завершено. Оцените от 1 до 5 (комментарий необязателен, анонимно).",
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

    if not event or event.is_closed:
        bot.answer_callback_query(call.id, "Ro'yxat yopiq / Регистрация закрыта", show_alert=True)
        return

    volunteer = Volunteer.query.filter_by(telegram_user_id=call.from_user.id).first()
    if not volunteer:
        bot.answer_callback_query(
            call.id, "Avval botga shaxsiy xabar yozing / Сначала напишите боту в личные сообщения", show_alert=True
        )
        return

    penalty = VolunteerPenalty.query.get(volunteer.id)
    if penalty and penalty.suspended:
        penalty.suspended = False
        db.session.commit()
        bot.answer_callback_query(
            call.id,
            "Siz oldingi tadbirga kelmagansiz, shu safar yozila olmaysiz / Вы пропустили прошлое мероприятие, в этот раз записаться нельзя. Со следующего раза снова можно.",
            show_alert=True,
        )
        return

    existing = EventRegistration.query.filter_by(event_id=event.id, volunteer_id=volunteer.id).first()

    if existing:
        db.session.delete(existing)
        db.session.commit()
        bot.answer_callback_query(call.id, "Yozuv bekor qilindi ❌ / Запись отменена", show_alert=True)
    else:
        if event.capacity:
            current_count = EventRegistration.query.filter_by(event_id=event.id).count()
            if current_count >= event.capacity:
                bot.answer_callback_query(call.id, "Joy yo'q 😔 / Мест больше нет", show_alert=True)
                return
        db.session.add(
            EventRegistration(event_id=event.id, volunteer_id=volunteer.id, telegram_chat_id=volunteer.telegram_chat_id)
        )
        db.session.commit()
        bot.answer_callback_query(call.id, "Siz yozildingiz ✅ / Вы записаны", show_alert=True)

    _refresh_announcement(event)

    if call.message.chat.id != event.announcement_chat_id:
        _refresh_message(call.message.chat.id, call.message.message_id, event)


@bot.callback_query_handler(func=lambda call: call.data.startswith("fbstar_"))
def handle_feedback_star(call):
    _, event_id_str, rating_str = call.data.split("_")
    bot.answer_callback_query(call.id)
    chat_id = call.message.chat.id
    draft_data = json.dumps({"event_id": int(event_id_str), "rating": int(rating_str)})

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
        bot.edit_message_text(
            "Rahmat! Izoh yozing yoki \"-\" yuboring / Спасибо! Напишите комментарий, или отправьте \"-\", чтобы пропустить.",
            chat_id,
            call.message.message_id,
        )
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
    if volunteer:
        reg = EventRegistration.query.filter_by(event_id=event_id, volunteer_id=volunteer.id).first()
        if reg:
            reg.feedback_submitted = True

    db.session.delete(draft)
    db.session.commit()

    bot.send_message(message.chat.id, "Rahmat! 🙏 / Спасибо за отзыв! 🙏")

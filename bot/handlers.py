import html
import json
import time
from datetime import datetime, timedelta

import telebot
from telebot import types

from bot.config import BOT_TOKEN, VOLUNTEER_GROUP_CHAT_ID, ADMIN_GROUP_CHAT_ID, OWNER_CHAT_ID
from bot.keyboards import phone_request_keyboard, car_question_keyboard, car_confirm_keyboard, language_keyboard, language_change_keyboard
from bot.translations import bt
from models import db, Volunteer, VolunteerApplication, BotStartCooldown, ConversationDraft

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)

VOLUNTEER_FORM_URL = "https://duocharity.uz/volunteer-form"
START_COOLDOWN_SECONDS = 5


def normalize_phone(raw):
    digits = "".join(ch for ch in raw if ch.isdigit())
    return digits[-9:] if len(digits) >= 9 else digits


def safe_send_message(chat_id, *args, **kwargs):
    try:
        return bot.send_message(chat_id, *args, **kwargs)
    except Exception as e:
        print(f"Не удалось отправить сообщение: {e}")


def safe_delete_message(chat_id, message_id):
    try:
        bot.delete_message(chat_id, message_id)
    except Exception as e:
        print(f"Не удалось удалить сообщение {message_id}: {e}")
        try:
            bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
        except Exception as e2:
            print(f"Не удалось убрать кнопки у сообщения {message_id}: {e2}")


def send_group_invite(chat_id, volunteer, lang):
    try:
        invite = bot.create_chat_invite_link(
            int(VOLUNTEER_GROUP_CHAT_ID),
            creates_join_request=True,
            name=f"volunteer-{volunteer.id}",
        )
        bot.send_message(chat_id, bt("group_invite", lang, link=invite.invite_link), parse_mode="HTML")
    except Exception as e:
        print(f"Не удалось создать инвайт-ссылку: {e}")


@bot.message_handler(commands=["start"])
def handle_start(message):
    if message.chat.type != "private":
        return

    now = datetime.utcnow()
    cooldown = BotStartCooldown.query.get(message.chat.id)

    if cooldown and (now - cooldown.last_start_at) < timedelta(seconds=START_COOLDOWN_SECONDS):
        return

    if cooldown:
        cooldown.last_start_at = now
    else:
        cooldown = BotStartCooldown(telegram_chat_id=message.chat.id, last_start_at=now)
        db.session.add(cooldown)
    db.session.commit()

    volunteer = Volunteer.query.filter_by(telegram_chat_id=message.chat.id).first()
    if volunteer:
        lang = volunteer.language or cooldown.language or "uz"
        safe_send_message(message.chat.id, bt("welcome_back", lang, name=volunteer.full_name))
        return

    if cooldown.language:
        safe_send_message(message.chat.id, bt("ask_phone", cooldown.language), reply_markup=phone_request_keyboard())
        return

    safe_send_message(message.chat.id, bt("start_choose_language"), reply_markup=language_keyboard(), parse_mode="HTML")


@bot.message_handler(commands=["language"])
def handle_language_command(message):
    if message.chat.type != "private":
        return

    safe_send_message(message.chat.id, bt("change_language_prompt"), reply_markup=language_change_keyboard())


@bot.callback_query_handler(func=lambda call: call.data in ("setlang_uz", "setlang_ru"))
def handle_language_change(call):
    if call.message.chat.type != "private":
        return

    bot.answer_callback_query(call.id)
    lang = "uz" if call.data == "setlang_uz" else "ru"
    chat_id = call.message.chat.id

    volunteer = Volunteer.query.filter_by(telegram_chat_id=chat_id).first()
    if volunteer:
        volunteer.language = lang
    else:
        application = VolunteerApplication.query.filter_by(telegram_chat_id=chat_id).first()
        if application:
            application.language = lang

    cooldown = BotStartCooldown.query.get(chat_id)
    if cooldown:
        cooldown.language = lang
    else:
        cooldown = BotStartCooldown(telegram_chat_id=chat_id, last_start_at=datetime.utcnow(), language=lang)
        db.session.add(cooldown)
    db.session.commit()

    safe_delete_message(chat_id, call.message.message_id)
    bot.send_message(chat_id, bt("language_changed", lang))


@bot.message_handler(commands=["base"])
def handle_base_command(message):
    if not OWNER_CHAT_ID or str(message.chat.id) != str(OWNER_CHAT_ID):
        return

    from excel_export import build_active_volunteers_workbook

    volunteers = Volunteer.query.order_by(Volunteer.created_at.desc()).all()
    output = build_active_volunteers_workbook(volunteers)

    try:
        bot.send_document(message.chat.id, output, visible_file_name="duo_volunteers.xlsx")
    except Exception as e:
        print(f"Не удалось отправить excel-базу владельцу: {e}")


def build_status_report():
    problems = []
    lines = []

    start = time.monotonic()
    try:
        info = bot.get_webhook_info()
        ping_ms = int((time.monotonic() - start) * 1000)
        if not info.url:
            problems.append("вебхук не настроен")
        lines.append(f"🔗 Вебхук: {'подключен' if info.url else 'не подключен'} ({info.url or '—'})")
        lines.append(f"📬 В очереди: {info.pending_update_count}")
        lines.append(f"⏱ Пинг Telegram API: {ping_ms} мс")
        if info.last_error_message:
            when = datetime.utcfromtimestamp(info.last_error_date).strftime("%d.%m %H:%M UTC") if info.last_error_date else "?"
            problems.append(f"была ошибка доставки вебхука ({when}): {info.last_error_message}")
    except Exception as e:
        problems.append(f"не удалось получить статус вебхука: {e}")

    lines.append("")
    lines.append("👥 Группы:")
    for label, chat_id in (("Волонтёры", VOLUNTEER_GROUP_CHAT_ID), ("Админы", ADMIN_GROUP_CHAT_ID)):
        if not chat_id:
            problems.append(f"группа «{label}» не задана в конфиге")
            lines.append(f"  • {label}: не задано в конфиге")
            continue
        try:
            chat = bot.get_chat(chat_id)
            count = bot.get_chat_member_count(chat_id)
            lines.append(f"  • {label}: «{chat.title or 'без названия'}» — {count} участников")
        except Exception as e:
            problems.append(f"группа «{label}» недоступна: {e}")
            lines.append(f"  • {label}: ⚠️ недоступна")

    lines.append("")
    try:
        volunteers = Volunteer.query.order_by(Volunteer.created_at.desc()).all()
        waiting_confirmation = VolunteerApplication.query.filter_by(status="new").count()
        with_car = sum(1 for v in volunteers if v.has_car)
        lines.append(
            f"🗄 База данных: в норме — {len(volunteers)} волонтёров, "
            f"{waiting_confirmation} ждут подтверждения, {with_car} с машиной"
        )
    except Exception as e:
        problems.append(f"база данных недоступна: {e}")
        lines.append("🗄 База данных: ⚠️ недоступна")

    return problems, lines


def format_status_report(problems, lines, ok_suffix=""):
    if problems:
        header = f"🔴 Обнаружены неисправности ({len(problems)}):\n" + "\n".join(f"— {p}" for p in problems)
    else:
        header = f"🟢 Неисправности не найдены, всё в норме{ok_suffix}!"
    return header + "\n\n" + "\n".join(lines)


@bot.message_handler(commands=["status"])
def handle_status_command(message):
    if not OWNER_CHAT_ID or str(message.from_user.id) != str(OWNER_CHAT_ID):
        return

    problems, lines = build_status_report()
    bot.send_message(message.chat.id, format_status_report(problems, lines, ok_suffix=", хозяин"))


@bot.message_handler(commands=["givestatus"])
def handle_givestatus_command(message):
    if not OWNER_CHAT_ID or str(message.from_user.id) != str(OWNER_CHAT_ID):
        return

    reply = message.reply_to_message
    if not reply:
        bot.send_message(message.chat.id, "Ответьте (Reply) на сообщение человека, для которого нужен статус, и повторите /givestatus.")
        return

    target_chat_id = None
    target_name = None

    if reply.from_user and not reply.from_user.is_bot and reply.from_user.id != message.from_user.id:
        target_chat_id = reply.from_user.id
        target_name = reply.from_user.first_name or (f"@{reply.from_user.username}" if reply.from_user.username else None)
    else:
        target_chat_id = lookup_support_ticket(message.chat.id, reply.message_id)
        if target_chat_id:
            volunteer = Volunteer.query.filter_by(telegram_chat_id=target_chat_id).first()
            application = volunteer or VolunteerApplication.query.filter_by(telegram_chat_id=target_chat_id).first()
            target_name = getattr(application, "full_name", None)

    if not target_chat_id:
        bot.send_message(message.chat.id, "Не удалось определить, кому отправить статус — ответьте на сообщение этого человека.")
        return

    target_name = target_name or "друг"
    problems, lines = build_status_report()
    report = format_status_report(problems, lines, ok_suffix=", хозяин")

    if message.chat.type == "private":
        sent = safe_send_message(target_chat_id, report)
        bot.send_message(message.chat.id, "Отправлено ✅" if sent else "Не удалось отправить — пользователь мог не запускать бота.")
    else:
        mention = f'<a href="tg://user?id={target_chat_id}">{html.escape(target_name)}</a>'
        bot.send_message(message.chat.id, f"{mention}\n\n{html.escape(report)}", parse_mode="HTML")


@bot.message_handler(commands=["message"])
def handle_message_command(message):
    if not OWNER_CHAT_ID or str(message.chat.id) != str(OWNER_CHAT_ID):
        return

    prompt = bot.send_message(message.chat.id, "Введите номер телефона волонтёра (9 цифр):")
    data = json.dumps({"prompt_id": prompt.message_id})

    draft = ConversationDraft.query.get(message.chat.id)
    if draft:
        draft.kind = "message"
        draft.state = "awaiting_phone"
        draft.data = data
    else:
        db.session.add(ConversationDraft(telegram_chat_id=message.chat.id, kind="message", state="awaiting_phone", data=data))
    db.session.commit()


def handle_message_draft_text(message, draft):
    data = json.loads(draft.data or "{}")
    prev_prompt_id = data.get("prompt_id")

    if draft.state == "awaiting_phone":
        phone = normalize_phone(message.text)
        volunteer = Volunteer.query.filter_by(phone=phone).first()

        if prev_prompt_id:
            safe_delete_message(message.chat.id, prev_prompt_id)

        if not volunteer:
            bot.send_message(message.chat.id, "Волонтёр с таким номером не найден.")
            db.session.delete(draft)
            db.session.commit()
            return

        prompt = bot.send_message(message.chat.id, f"Найден: {volunteer.full_name}. Введите текст сообщения:")
        draft.state = "awaiting_text"
        draft.data = json.dumps({"phone": phone, "name": volunteer.full_name, "prompt_id": prompt.message_id})
        db.session.commit()
        return

    if draft.state == "awaiting_text":
        if prev_prompt_id:
            safe_delete_message(message.chat.id, prev_prompt_id)

        text = message.text.strip()
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("✅ Отправить", callback_data="msgconfirm_yes"),
            types.InlineKeyboardButton("❌ Отмена", callback_data="msgconfirm_no"),
        )
        confirm = bot.send_message(
            message.chat.id,
            f"Отправить волонтёру {data.get('name')}?\n\n«{text}»",
            reply_markup=markup,
        )
        draft.state = "awaiting_confirm"
        draft.data = json.dumps({"phone": data.get("phone"), "name": data.get("name"), "text": text, "prompt_id": confirm.message_id})
        db.session.commit()
        return


@bot.callback_query_handler(func=lambda call: call.data in ("msgconfirm_yes", "msgconfirm_no"))
def handle_message_confirm(call):
    bot.answer_callback_query(call.id)
    draft = ConversationDraft.query.get(call.message.chat.id)

    if not draft or draft.kind != "message" or draft.state != "awaiting_confirm":
        safe_delete_message(call.message.chat.id, call.message.message_id)
        return

    data = json.loads(draft.data or "{}")
    safe_delete_message(call.message.chat.id, call.message.message_id)
    db.session.delete(draft)
    db.session.commit()

    if call.data == "msgconfirm_no":
        bot.send_message(call.message.chat.id, "Отменено.")
        return

    volunteer = Volunteer.query.filter_by(phone=data.get("phone")).first()
    if not volunteer or not volunteer.telegram_chat_id:
        bot.send_message(call.message.chat.id, "У волонтёра ещё не подключён Telegram, сообщение не отправлено.")
        return

    try:
        bot.send_message(volunteer.telegram_chat_id, f"✉️ Сообщение от организаторов DUO Charity:\n\n{data.get('text')}")
        bot.send_message(call.message.chat.id, "Отправлено ✅")
    except Exception as e:
        bot.send_message(call.message.chat.id, "Не удалось отправить сообщение.")
        print(f"Не удалось отправить личное сообщение волонтёру: {e}")


@bot.message_handler(commands=["support"])
def handle_support_command(message):
    if message.chat.type != "private":
        volunteer = Volunteer.query.filter_by(telegram_user_id=message.from_user.id).first()
        lang = volunteer.language if volunteer and volunteer.language else "uz"
        bot.reply_to(message, bt("support_group_redirect", lang))
        return

    volunteer = Volunteer.query.filter_by(telegram_chat_id=message.chat.id).first()
    lang = volunteer.language if volunteer and volunteer.language else "uz"

    prompt = bot.send_message(message.chat.id, bt("support_ask", lang))
    data = json.dumps({"prompt_id": prompt.message_id})

    draft = ConversationDraft.query.get(message.chat.id)
    if draft:
        draft.kind = "support"
        draft.state = "awaiting_text"
        draft.data = data
    else:
        db.session.add(ConversationDraft(telegram_chat_id=message.chat.id, kind="support", state="awaiting_text", data=data))
    db.session.commit()


def handle_support_draft_text(message, draft):
    data = json.loads(draft.data or "{}")
    prev_prompt_id = data.get("prompt_id")
    if prev_prompt_id:
        safe_delete_message(message.chat.id, prev_prompt_id)

    volunteer = Volunteer.query.filter_by(telegram_chat_id=message.chat.id).first()
    application = None
    if not volunteer:
        application = VolunteerApplication.query.filter_by(telegram_chat_id=message.chat.id).first()

    lang = (volunteer.language if volunteer else None) or (application.language if application else None) or "uz"

    if volunteer:
        name, phone = volunteer.full_name, volunteer.phone
    elif application:
        name, phone = application.full_name, application.phone
    else:
        name = " ".join(filter(None, [message.from_user.first_name, message.from_user.last_name])) or "Без имени"
        phone = None

    username = f"@{message.from_user.username}" if message.from_user.username else "—"
    name_link = f'<a href="tg://user?id={message.chat.id}">{html.escape(name)}</a>'

    admin_text = (
        "🆘 <b>Обращение в поддержку</b>\n\n"
        f"👤 <b>От:</b> {name_link}\n"
        f"📞 <b>Телефон:</b> {html.escape(phone) if phone else '—'}\n"
        f"✈️ <b>Telegram:</b> {html.escape(username)}\n\n"
        f"<blockquote>{html.escape(message.text.strip())}</blockquote>\n\n"
        "↩️ Чтобы ответить — свайпните это сообщение (Reply) и напишите текст."
    )

    for chat_id in (ADMIN_GROUP_CHAT_ID, OWNER_CHAT_ID):
        if not chat_id:
            continue
        sent_msg = safe_send_message(chat_id, admin_text, parse_mode="HTML")
        if sent_msg:
            register_support_ticket(int(chat_id), sent_msg.message_id, message.chat.id)

    db.session.delete(draft)
    db.session.commit()

    bot.send_message(message.chat.id, bt("support_sent", lang))


def register_support_ticket(admin_chat_id, message_id, target_chat_id):
    draft = ConversationDraft.query.get(admin_chat_id)
    tickets = json.loads(draft.data or "{}") if draft and draft.kind == "support_tickets" else {}
    tickets[str(message_id)] = target_chat_id
    data = json.dumps(tickets)

    if draft:
        draft.kind = "support_tickets"
        draft.state = "active"
        draft.data = data
    else:
        db.session.add(ConversationDraft(telegram_chat_id=admin_chat_id, kind="support_tickets", state="active", data=data))
    db.session.commit()


def lookup_support_ticket(admin_chat_id, message_id):
    draft = ConversationDraft.query.get(admin_chat_id)
    if not draft or draft.kind != "support_tickets":
        return None
    tickets = json.loads(draft.data or "{}")
    return tickets.get(str(message_id))


def handle_admin_reply_to_support(message, target_chat_id):
    sent = safe_send_message(
        target_chat_id,
        f"💬 <b>Ответ от поддержки DUO Charity:</b>\n\n{html.escape(message.text.strip())}",
        parse_mode="HTML",
    )
    if sent:
        bot.send_message(message.chat.id, "Отправлено ✅", reply_to_message_id=message.message_id)
    else:
        bot.send_message(message.chat.id, "Не удалось отправить — пользователь мог заблокировать бота.", reply_to_message_id=message.message_id)


def resolve_phone_match(message, phone, lang):
    volunteer = Volunteer.query.filter_by(phone=phone).first()
    if volunteer:
        if volunteer.telegram_chat_id == message.chat.id:
            v_lang = volunteer.language or lang
            bot.send_message(message.chat.id, bt("matched", v_lang, name=volunteer.full_name), reply_markup=types.ReplyKeyboardRemove())
            return True

        volunteer.telegram_user_id = message.from_user.id
        volunteer.telegram_chat_id = message.chat.id
        volunteer.language = lang
        volunteer.pending_action = None
        db.session.commit()

        bot.send_message(message.chat.id, bt("matched", lang, name=volunteer.full_name), reply_markup=types.ReplyKeyboardRemove())

        if volunteer.has_car is None:
            bot.send_message(message.chat.id, bt("ask_car", lang), reply_markup=car_question_keyboard(lang))
        else:
            send_group_invite(message.chat.id, volunteer, lang)
        return True

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
        application.language = lang
        application.pending_action = None
        db.session.commit()

        bot.send_message(message.chat.id, bt("pending_review", lang), reply_markup=types.ReplyKeyboardRemove())
        return True

    return False


@bot.message_handler(content_types=["contact"])
def handle_contact(message):
    if message.chat.type != "private":
        return

    contact = message.contact
    cooldown = BotStartCooldown.query.get(message.chat.id)
    lang = (cooldown.language if cooldown else None) or "uz"

    if contact.user_id != message.from_user.id:
        bot.send_message(message.chat.id, bt("own_contact_only", lang))
        return

    phone = normalize_phone(contact.phone_number)
    if resolve_phone_match(message, phone, lang):
        return

    bot.send_message(
        message.chat.id,
        bt("not_matched_try_manual", lang, form_link=VOLUNTEER_FORM_URL),
        reply_markup=types.ReplyKeyboardRemove(),
    )


@bot.callback_query_handler(func=lambda call: call.data in ("lang_uz", "lang_ru"))
def handle_language_choice(call):
    if call.message.chat.type != "private":
        return

    bot.answer_callback_query(call.id)
    lang = "uz" if call.data == "lang_uz" else "ru"

    volunteer = Volunteer.query.filter_by(telegram_chat_id=call.message.chat.id, pending_action="awaiting_language").first()
    if volunteer:
        volunteer.language = lang
        volunteer.pending_action = None
        db.session.commit()

        safe_delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(call.message.chat.id, bt("matched", lang, name=volunteer.full_name))

        if volunteer.has_car is None:
            bot.send_message(call.message.chat.id, bt("ask_car", lang), reply_markup=car_question_keyboard(lang))
        else:
            send_group_invite(call.message.chat.id, volunteer, lang)
        return

    application = VolunteerApplication.query.filter_by(telegram_chat_id=call.message.chat.id, pending_action="awaiting_language").first()
    if application:
        application.language = lang
        application.pending_action = None
        db.session.commit()

        safe_delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(call.message.chat.id, bt("pending_confirmed", lang))
        return

    cooldown = BotStartCooldown.query.get(call.message.chat.id)
    if cooldown:
        cooldown.language = lang
    else:
        cooldown = BotStartCooldown(telegram_chat_id=call.message.chat.id, last_start_at=datetime.utcnow(), language=lang)
        db.session.add(cooldown)
    db.session.commit()

    safe_delete_message(call.message.chat.id, call.message.message_id)
    bot.send_message(call.message.chat.id, bt("ask_phone", lang), reply_markup=phone_request_keyboard())

@bot.callback_query_handler(func=lambda call: call.data in ("car_yes", "car_no"))
def handle_car_answer(call):
    if call.message.chat.type != "private":
        return

    volunteer = Volunteer.query.filter_by(telegram_chat_id=call.message.chat.id).first()
    bot.answer_callback_query(call.id)

    if not volunteer:
        return

    if volunteer.has_car is not None:
        safe_delete_message(call.message.chat.id, call.message.message_id)
        return

    lang = volunteer.language or "uz"
    safe_delete_message(call.message.chat.id, call.message.message_id)

    if call.data == "car_yes":
        volunteer.has_car = True
        msg = bot.send_message(call.message.chat.id, bt("ask_car_brand", lang))
        volunteer.pending_action = f"awaiting_car_brand:{msg.message_id}"
        db.session.commit()
    else:
        volunteer.has_car = False
        volunteer.pending_action = None
        db.session.commit()
        bot.send_message(call.message.chat.id, bt("car_declined", lang))
        send_group_invite(call.message.chat.id, volunteer, lang)


@bot.message_handler(content_types=["text"])
def handle_text(message):
    if message.reply_to_message:
        support_target = lookup_support_ticket(message.chat.id, message.reply_to_message.message_id)
        if support_target:
            handle_admin_reply_to_support(message, support_target)
            return

    if message.chat.type != "private":
        return

    draft = ConversationDraft.query.get(message.chat.id)
    if draft:
        if draft.kind == "message":
            handle_message_draft_text(message, draft)
            return
        if draft.kind == "event_feedback":
            from bot.events import process_feedback_comment
            process_feedback_comment(message, draft)
            return
        if draft.kind == "support":
            handle_support_draft_text(message, draft)
            return

    volunteer = Volunteer.query.filter_by(telegram_chat_id=message.chat.id).first()
    lang = volunteer.language if volunteer and volunteer.language else "uz"
    pending = volunteer.pending_action if volunteer else None

    if pending and pending.startswith("awaiting_car_brand"):
        prev_id = pending.split(":", 1)[1] if ":" in pending else None
        volunteer.car_brand = message.text.strip()[:60]
        msg = bot.send_message(message.chat.id, bt("ask_car_plate", lang))
        volunteer.pending_action = f"awaiting_car_plate:{msg.message_id}"
        db.session.commit()
        if prev_id:
            safe_delete_message(message.chat.id, int(prev_id))
        return

    if pending and pending.startswith("awaiting_car_plate"):
        prev_id = pending.split(":", 1)[1] if ":" in pending else None
        volunteer.car_plate = message.text.strip()[:20]
        volunteer.pending_action = "awaiting_car_confirm"
        db.session.commit()
        bot.send_message(
            message.chat.id,
            bt("confirm_car_details", lang, brand=html.escape(volunteer.car_brand or ""), plate=html.escape(volunteer.car_plate or "")),
            reply_markup=car_confirm_keyboard(lang),
            parse_mode="HTML",
        )
        if prev_id:
            safe_delete_message(message.chat.id, int(prev_id))
        return

    if not volunteer:
        digits = "".join(ch for ch in message.text if ch.isdigit())
        if len(digits) >= 9:
            cooldown = BotStartCooldown.query.get(message.chat.id)
            phone_lang = (cooldown.language if cooldown else None) or lang
            phone = normalize_phone(message.text)
            if resolve_phone_match(message, phone, phone_lang):
                return
            bot.send_message(message.chat.id, bt("manual_phone_not_found", phone_lang, form_link=VOLUNTEER_FORM_URL))
            return

    bot.send_message(message.chat.id, bt("fallback", lang))


@bot.callback_query_handler(func=lambda call: call.data in ("car_confirm_yes", "car_confirm_no"))
def handle_car_confirm(call):
    if call.message.chat.type != "private":
        return

    volunteer = Volunteer.query.filter_by(telegram_chat_id=call.message.chat.id, pending_action="awaiting_car_confirm").first()
    bot.answer_callback_query(call.id)

    if not volunteer:
        safe_delete_message(call.message.chat.id, call.message.message_id)
        return

    lang = volunteer.language or "uz"
    safe_delete_message(call.message.chat.id, call.message.message_id)

    if call.data == "car_confirm_yes":
        volunteer.pending_action = None
        db.session.commit()
        bot.send_message(call.message.chat.id, bt("car_saved", lang))
        send_group_invite(call.message.chat.id, volunteer, lang)
    else:
        volunteer.car_brand = None
        volunteer.car_plate = None
        msg = bot.send_message(call.message.chat.id, bt("ask_car_brand", lang))
        volunteer.pending_action = f"awaiting_car_brand:{msg.message_id}"
        db.session.commit()

@bot.chat_join_request_handler()
def handle_join_request(request):
    if request.chat.id != int(VOLUNTEER_GROUP_CHAT_ID):
        return

    volunteer = Volunteer.query.filter_by(telegram_user_id=request.from_user.id).first()

    try:
        if volunteer:
            bot.approve_chat_join_request(request.chat.id, request.from_user.id)

            mention = f'<a href="tg://user?id={request.from_user.id}">{html.escape(volunteer.full_name)}</a>'
            text_uz = bt("welcome_message", "uz", mention=mention)
            text_ru = bt("welcome_message", "ru", mention=mention)

            car_line = "❓ Не указано"
            if volunteer.has_car:
                brand = html.escape(volunteer.car_brand) if volunteer.car_brand else "—"
                plate = html.escape(volunteer.car_plate) if volunteer.car_plate else "—"
                car_line = f"{brand} ({plate})"
                text_uz += bt("welcome_car_line", "uz", brand=brand, plate=plate)
                text_ru += bt("welcome_car_line", "ru", brand=brand, plate=plate)
            elif volunteer.has_car is False:
                car_line = "Без авто"

            bot.send_message(request.chat.id, text_uz, parse_mode="HTML")
            bot.send_message(request.chat.id, text_ru, parse_mode="HTML")

            admin_text = (
                f"✅ <b>{html.escape(volunteer.full_name)}</b> вступил(а) в группу волонтёров.\n"
                f"🚗 Авто: {car_line}"
            )
            for chat_id in (ADMIN_GROUP_CHAT_ID, OWNER_CHAT_ID):
                if not chat_id:
                    continue
                safe_send_message(chat_id, admin_text, parse_mode="HTML")
        else:
            bot.decline_chat_join_request(request.chat.id, request.from_user.id)
    except Exception as e:
        print(f"Не удалось обработать заявку на вступление: {e}")


@bot.message_handler(content_types=["new_chat_members"])
def handle_new_chat_members(message):
    if not VOLUNTEER_GROUP_CHAT_ID or message.chat.id != int(VOLUNTEER_GROUP_CHAT_ID):
        return

    for member in message.new_chat_members:
        if member.is_bot:
            continue

        volunteer = Volunteer.query.filter_by(telegram_user_id=member.id).first()
        if volunteer:
            continue

        mention = f'<a href="tg://user?id={member.id}">{html.escape(member.first_name or "друг")}</a>'

        try:
            bot.send_message(message.chat.id, bt("stranger_join_prompt", "uz", mention=mention, form_link=VOLUNTEER_FORM_URL), parse_mode="HTML")
            bot.send_message(message.chat.id, bt("stranger_join_prompt", "ru", mention=mention, form_link=VOLUNTEER_FORM_URL), parse_mode="HTML")
        except Exception as e:
            print(f"Не удалось поприветствовать нового участника {member.id}: {e}")

        admin_text = f"⚠️ {mention} вступил(а) в группу напрямую, минуя регистрацию (ID: {member.id})."
        for chat_id in (ADMIN_GROUP_CHAT_ID, OWNER_CHAT_ID):
            if not chat_id:
                continue
            safe_send_message(chat_id, admin_text, parse_mode="HTML")


@bot.message_handler(content_types=["sticker", "photo", "voice", "video", "document", "audio"])
def handle_other_content(message):
    if message.chat.type != "private":
        return

    volunteer = Volunteer.query.filter_by(telegram_chat_id=message.chat.id).first()
    lang = volunteer.language if volunteer and volunteer.language else "uz"
    safe_send_message(message.chat.id, bt("fallback", lang))
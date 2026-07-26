import html
import json
from datetime import datetime, timedelta

import telebot
from telebot import types

from bot.config import BOT_TOKEN, VOLUNTEER_GROUP_CHAT_ID, ADMIN_GROUP_CHAT_ID, OWNER_CHAT_ID
from bot.keyboards import phone_request_keyboard, car_question_keyboard, car_confirm_keyboard, language_keyboard, language_change_keyboard
from bot.translations import bt
from models import db, Volunteer, VolunteerApplication, BotStartCooldown, ConversationDraft

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)

VOLUNTEER_FORM_URL = "https://duo-charity.vercel.app/volunteer-form"
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
    safe_delete_message(message.chat.id, message.message_id)
    safe_send_message(message.chat.id, bt("change_language_prompt"), reply_markup=language_change_keyboard())


@bot.callback_query_handler(func=lambda call: call.data in ("setlang_uz", "setlang_ru"))
def handle_language_change(call):
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

    safe_delete_message(message.chat.id, message.message_id)

    from excel_export import build_active_volunteers_workbook

    volunteers = Volunteer.query.order_by(Volunteer.created_at.desc()).all()
    output = build_active_volunteers_workbook(volunteers)

    try:
        bot.send_document(message.chat.id, output, visible_file_name="duo_volunteers.xlsx")
    except Exception as e:
        print(f"Не удалось отправить excel-базу владельцу: {e}")


@bot.message_handler(commands=["stats"])
def handle_stats_command(message):
    if not OWNER_CHAT_ID or str(message.chat.id) != str(OWNER_CHAT_ID):
        return

    safe_delete_message(message.chat.id, message.message_id)

    volunteers_count = Volunteer.query.count()
    new_applications = VolunteerApplication.query.filter_by(status="new").count()
    with_car = Volunteer.query.filter_by(has_car=True).count()

    bot.send_message(
        message.chat.id,
        "📊 Статистика DUO Charity\n\n"
        f"👥 Активных волонтёров: {volunteers_count}\n"
        f"📥 Новых заявок: {new_applications}\n"
        f"🚗 Волонтёров с машиной: {with_car}",
    )


@bot.message_handler(commands=["message"])
def handle_message_command(message):
    if not OWNER_CHAT_ID or str(message.chat.id) != str(OWNER_CHAT_ID):
        return

    safe_delete_message(message.chat.id, message.message_id)

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
        safe_delete_message(message.chat.id, message.message_id)

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
        safe_delete_message(message.chat.id, message.message_id)

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


@bot.message_handler(content_types=["contact"])
def handle_contact(message):
    contact = message.contact
    cooldown = BotStartCooldown.query.get(message.chat.id)
    lang = (cooldown.language if cooldown else None) or "uz"

    if contact.user_id != message.from_user.id:
        bot.send_message(message.chat.id, bt("own_contact_only", lang))
        return

    phone = normalize_phone(contact.phone_number)

    volunteer = Volunteer.query.filter_by(phone=phone).first()
    if volunteer:
        if volunteer.telegram_chat_id == message.chat.id:
            v_lang = volunteer.language or lang
            bot.send_message(message.chat.id, bt("matched", v_lang, name=volunteer.full_name), reply_markup=types.ReplyKeyboardRemove())
            return

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
        application.language = lang
        application.pending_action = None
        db.session.commit()

        bot.send_message(message.chat.id, bt("pending_review", lang), reply_markup=types.ReplyKeyboardRemove())
        return

    bot.send_message(
        message.chat.id,
        bt("not_matched", lang, form_link=VOLUNTEER_FORM_URL),
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
    draft = ConversationDraft.query.get(message.chat.id)
    if draft:
        if draft.kind == "message":
            handle_message_draft_text(message, draft)
            return
        if draft.kind == "event_feedback":
            from bot.events import process_feedback_comment
            process_feedback_comment(message, draft)
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
        safe_delete_message(message.chat.id, message.message_id)
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
        safe_delete_message(message.chat.id, message.message_id)
        return

    bot.send_message(message.chat.id, bt("fallback", lang))


@bot.callback_query_handler(func=lambda call: call.data in ("car_confirm_yes", "car_confirm_no"))
def handle_car_confirm(call):
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

@bot.message_handler(content_types=["sticker", "photo", "voice", "video", "document", "audio"])
def handle_other_content(message):
    volunteer = Volunteer.query.filter_by(telegram_chat_id=message.chat.id).first()
    lang = volunteer.language if volunteer and volunteer.language else "uz"
    safe_send_message(message.chat.id, bt("fallback", lang))
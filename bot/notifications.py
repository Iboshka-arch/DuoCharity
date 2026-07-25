import html

from telebot import types

from bot.handlers import bot
from bot.utils import safe_send_message
from bot.config import ADMIN_GROUP_CHAT_ID, OWNER_CHAT_ID
from bot.actions import accept_application, decline_application
from models import VolunteerApplication

ADMIN_PANEL_URL = "https://duocharity.uz/admin"


def notify_new_application(application):
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("✅ Принять", callback_data=f"app_accept_{application.id}"),
        types.InlineKeyboardButton("❌ Отклонить", callback_data=f"app_decline_{application.id}"),
    )

    text = (
        "📥 <b>Новая заявка на волонтёрство</b>\n\n"
        f"👤 <b>Имя:</b> {html.escape(application.full_name)}\n"
        f"📞 <b>Телефон:</b> {html.escape(application.phone)}\n"
        f"✈️ <b>Telegram:</b> {html.escape(application.telegram) if application.telegram else '—'}\n\n"
        f"🔗 {ADMIN_PANEL_URL}"
    )

    for chat_id in (ADMIN_GROUP_CHAT_ID, OWNER_CHAT_ID):
        if not chat_id:
            continue
        try:
            safe_send_message(chat_id, text, reply_markup=keyboard, parse_mode="HTML")
        except Exception as e:
            print(f"Не удалось отправить уведомление в {chat_id}: {e}")

ADMIN_CHAT_IDS = {str(ADMIN_GROUP_CHAT_ID), str(OWNER_CHAT_ID)}

def safe_answer(call, text=None):
    try:
        bot.answer_callback_query(call.id, text) if text else bot.answer_callback_query(call.id)
    except Exception as e:
        print(f"Не удалось ответить на callback (вероятно, устарел): {e}")


@bot.callback_query_handler(func=lambda call: call.data.startswith("app_accept_") or call.data.startswith("app_decline_"))
def handle_admin_decision(call):
    if str(call.message.chat.id) not in ADMIN_CHAT_IDS:
        safe_answer(call, "Недостаточно прав.")
        return

    app_id = int(call.data.rsplit("_", 1)[1])
    application = VolunteerApplication.query.get(app_id)

    if not application:
        safe_answer(call, "Заявка уже обработана.")
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception as e:
            print(f"Не удалось убрать кнопки: {e}")
        return

    if call.data.startswith("app_accept_"):
        volunteer, created = accept_application(application)
        safe_answer(call, "Принято ✅")
        note = "\n\n✅ Принят(а) в волонтёры" if created else "\n\n⚠️ Уже был(а) в списке волонтёров"
    else:
        decline_application(application)
        safe_answer(call, "Отклонено")
        note = "\n\n❌ Заявка отклонена"

    try:
        bot.edit_message_text(
            call.message.html_text + note,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=None,
            parse_mode="HTML",
        )
    except Exception as e:
        print(f"Не удалось отредактировать сообщение: {e}")
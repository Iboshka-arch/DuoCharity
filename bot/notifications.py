from telebot import types

from bot.handlers import bot
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
        "📥 Новая заявка на волонтёрство\n\n"
        f"Имя: {application.full_name}\n"
        f"Телефон: {application.phone}\n"
        f"Telegram: {application.telegram or '—'}\n\n"
        f"Панель: {ADMIN_PANEL_URL}"
    )

    for chat_id in (ADMIN_GROUP_CHAT_ID, OWNER_CHAT_ID):
        if not chat_id:
            continue
        try:
            bot.send_message(chat_id, text, reply_markup=keyboard)
        except Exception as e:
            print(f"Не удалось отправить уведомление в {chat_id}: {e}")

ADMIN_CHAT_IDS = {str(ADMIN_GROUP_CHAT_ID), str(OWNER_CHAT_ID)}

@bot.callback_query_handler(func=lambda call: call.data.startswith("app_accept_") or call.data.startswith("app_decline_"))
def handle_admin_decision(call):
    if str(call.message.chat.id) not in ADMIN_CHAT_IDS:
        bot.answer_callback_query(call.id, "Недостаточно прав.")
        return

    from bot.actions import accept_application, decline_application

    app_id = int(call.data.rsplit("_", 1)[1])
    application = VolunteerApplication.query.get(app_id)

    if not application or application.status == "closed":
        bot.answer_callback_query(call.id, "Заявка уже обработана.")
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        return

    if call.data.startswith("app_accept_"):
        volunteer, created = accept_application(application)
        bot.answer_callback_query(call.id, "Принято ✅")
        note = "\n\n✅ Принят(а) в волонтёры" if created else "\n\n⚠️ Уже был(а) в списке волонтёров"
    else:
        decline_application(application)
        bot.answer_callback_query(call.id, "Отклонено")
        note = "\n\n❌ Заявка отклонена"

    bot.edit_message_text(
        call.message.text + note,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=None,
    )            
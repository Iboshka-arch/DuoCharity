from bot.handlers import bot
from bot.config import ADMIN_GROUP_CHAT_ID, OWNER_CHAT_ID

ADMIN_PANEL_URL = "https://duocharity.uz/admin/volunteers"


def notify_new_application(application):
    text = (
        "📥 Новая заявка на волонтёрство\n\n"
        f"Имя: {application.full_name}\n"
        f"Телефон: {application.phone}\n"
        f"Telegram: {application.telegram or '—'}\n\n"
        f"Посмотреть и принять: {ADMIN_PANEL_URL}"
    )

    for chat_id in (ADMIN_GROUP_CHAT_ID, OWNER_CHAT_ID):
        if not chat_id:
            continue
        try:
            bot.send_message(chat_id, text)
        except Exception as e:
            print(f"Не удалось отправить уведомление в {chat_id}: {e}")
from datetime import datetime, timedelta

from bot.handlers import bot
from models import db, BotSpamTracker

WINDOW_SECONDS = 3
MAX_MESSAGES = 3
WARN_COOLDOWN_SECONDS = 15


def check_and_handle_spam(chat_id, message_id):
    now = datetime.utcnow()
    tracker = BotSpamTracker.query.get(chat_id)

    if not tracker or (now - tracker.window_start) > timedelta(seconds=WINDOW_SECONDS):
        if not tracker:
            tracker = BotSpamTracker(telegram_chat_id=chat_id)
            db.session.add(tracker)
        tracker.window_start = now
        tracker.message_count = 1
        tracker.recent_message_ids = str(message_id)
        db.session.commit()
        return False

    tracker.message_count += 1
    ids = tracker.recent_message_ids.split(",") if tracker.recent_message_ids else []
    ids.append(str(message_id))
    ids = ids[-3:]
    tracker.recent_message_ids = ",".join(ids)

    is_spam = tracker.message_count > MAX_MESSAGES

    if is_spam:
        for mid in ids:
            try:
                bot.delete_message(chat_id, int(mid))
            except Exception as e:
                print(f"Не удалось удалить сообщение {mid}: {e}")

        should_warn = not tracker.warned_at or (now - tracker.warned_at) > timedelta(seconds=WARN_COOLDOWN_SECONDS)
        if should_warn:
            try:
                bot.send_message(chat_id, "Пожалуйста, не отправляйте так много сообщений подряд. ⏳")
            except Exception as e:
                print(f"Не удалось отправить предупреждение: {e}")
            tracker.warned_at = now

        tracker.recent_message_ids = ""

    db.session.commit()
    return is_spam
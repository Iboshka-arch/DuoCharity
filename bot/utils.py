from bot.handlers import bot


def safe_send_message(chat_id, text, **kwargs):
    try:
        bot.send_message(chat_id, text, **kwargs)
        return True
    except Exception as e:
        print(f"Не удалось отправить сообщение в чат {chat_id}: {e}")
        return False
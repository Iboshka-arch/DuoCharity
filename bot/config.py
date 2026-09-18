import os

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_GROUP_CHAT_ID = os.environ.get("ADMIN_GROUP_CHAT_ID")
OWNER_CHAT_ID = os.environ.get("OWNER_CHAT_ID")
# Разработчик: технические команды (/base, /status, /givestatus) и read-only копии
# админ-уведомлений — отдельно от OWNER_CHAT_ID, чтобы владелица фонда не путалась
# с dev-инструментами, а разработчик не мог случайно продублировать публикацию.
DEVELOPER_CHAT_ID = os.environ.get("DEVELOPER_CHAT_ID")
VOLUNTEER_GROUP_CHAT_ID = os.environ.get("VOLUNTEER_GROUP_CHAT_ID")
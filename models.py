from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

NO_TELEGRAM_USERNAME = "no_username"


class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    image_filename = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def formatted_date(self):
        return self.created_at.strftime("%d.%m.%Y")

    def excerpt(self, length=140):
        if len(self.content) <= length:
            return self.content
        return self.content[:length].rsplit(" ", 1)[0] + "…"


class GalleryImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    caption = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class HeroImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    order = db.Column(db.Integer, default=0)  # порядок показа в карусели
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class VolunteerApplication(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(50), nullable=False)
    telegram = db.Column(db.String(100), nullable=True)
    gender = db.Column(db.String(10), nullable=True)  # male / female
    age = db.Column(db.Integer, nullable=True)
    occupation = db.Column(db.String(200), nullable=True)  # учится / работает / др.
    message = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default="new")  # new / contacted / closed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    telegram_user_id = db.Column(db.BigInteger, nullable=True)
    telegram_chat_id = db.Column(db.BigInteger, nullable=True)
    language = db.Column(db.String(2), nullable=True)
    pending_action = db.Column(db.String(50), nullable=True)


    def telegram_url(self):
        if not self.telegram or self.telegram == NO_TELEGRAM_USERNAME:
            return None
        clean = self.telegram.strip().lstrip("@")
        return f"https://t.me/{clean}" if clean else None

    def has_no_telegram_username(self):
        return self.telegram == NO_TELEGRAM_USERNAME


class SiteSetting(db.Model):
    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.String(500), nullable=True)

class Volunteer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(50), nullable=False, unique=True)
    telegram = db.Column(db.String(100), nullable=True)
    gender = db.Column(db.String(10), nullable=True)  # male / female
    age = db.Column(db.Integer, nullable=True)
    birth_date = db.Column(db.Date, nullable=True)
    occupation = db.Column(db.String(200), nullable=True)  # учится / работает / др.

    telegram_user_id = db.Column(db.BigInteger, nullable=True, unique=True)
    telegram_chat_id = db.Column(db.BigInteger, nullable=True, unique=True)

    has_car = db.Column(db.Boolean, nullable=True)
    car_plate = db.Column(db.String(20), nullable=True)
    car_brand = db.Column(db.String(60), nullable=True)
    language = db.Column(db.String(2), nullable=True, default="uz")
    pending_action = db.Column(db.String(50), nullable=True)

    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def telegram_url(self):
        if not self.telegram or self.telegram == NO_TELEGRAM_USERNAME:
            return None
        clean = self.telegram.strip().lstrip("@")
        return f"https://t.me/{clean}" if clean else None

    def has_no_telegram_username(self):
        return self.telegram == NO_TELEGRAM_USERNAME

    def formatted_date(self):
        return self.created_at.strftime("%d.%m.%Y")

class BotSpamTracker(db.Model):
    telegram_chat_id = db.Column(db.BigInteger, primary_key=True)
    window_start = db.Column(db.DateTime, default=datetime.utcnow)
    message_count = db.Column(db.Integer, default=0)
    recent_message_ids = db.Column(db.String(200), nullable=True)
    warned_at = db.Column(db.DateTime, nullable=True)

class BotStartCooldown(db.Model):
    telegram_chat_id = db.Column(db.BigInteger, primary_key=True)
    last_start_at = db.Column(db.DateTime, default=datetime.utcnow)
    language = db.Column(db.String(2), nullable=True)

class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    date_text = db.Column(db.String(100), nullable=True)
    description = db.Column(db.Text, nullable=True)
    location = db.Column(db.String(200), nullable=True)
    capacity = db.Column(db.Integer, nullable=True)
    is_closed = db.Column(db.Boolean, default=False)
    announcement_chat_id = db.Column(db.BigInteger, nullable=True)
    announcement_message_id = db.Column(db.BigInteger, nullable=True)
    location_chat_id = db.Column(db.BigInteger, nullable=True)
    location_message_id = db.Column(db.BigInteger, nullable=True)
    admin_roster_chat_id = db.Column(db.BigInteger, nullable=True)
    admin_roster_message_id = db.Column(db.BigInteger, nullable=True)
    last_publish_dm_sent = db.Column(db.Integer, nullable=True)
    last_publish_dm_total = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def formatted_date(self):
        return self.created_at.strftime("%d.%m.%Y")

class EventRegistration(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, nullable=False)
    volunteer_id = db.Column(db.Integer, nullable=False)
    telegram_chat_id = db.Column(db.BigInteger, nullable=True)
    status = db.Column(db.String(20), default="registered")
    feedback_submitted = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class EventFeedback(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class VolunteerPenalty(db.Model):
    volunteer_id = db.Column(db.Integer, primary_key=True)
    no_show_count = db.Column(db.Integer, default=0)
    suspended = db.Column(db.Boolean, default=False)

class ConversationDraft(db.Model):
    telegram_chat_id = db.Column(db.BigInteger, primary_key=True)
    kind = db.Column(db.String(30))
    state = db.Column(db.String(30))
    data = db.Column(db.Text)

class ScheduledDeletion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.BigInteger, nullable=False)
    message_id = db.Column(db.BigInteger, nullable=False)
    delete_at = db.Column(db.DateTime, nullable=False)

class ActivityLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    actor = db.Column(db.String(200), nullable=False)
    action = db.Column(db.String(100), nullable=False)
    detail = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class AdminLoginEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username_attempted = db.Column(db.String(80), nullable=True)
    success = db.Column(db.Boolean, default=False)
    ip_address = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

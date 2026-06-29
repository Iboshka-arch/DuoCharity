from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class Admin(db.Model):
    """Администратор сайта (логин в админ-панель)."""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Post(db.Model):
    """Новость или отчёт."""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    image_filename = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def formatted_date(self):
        return self.created_at.strftime("%d.%m.%Y")

    def excerpt(self, length=140):
        """Автоматически обрезает текст для показа в карточках."""
        if len(self.content) <= length:
            return self.content
        return self.content[:length].rsplit(" ", 1)[0] + "…"


class GalleryImage(db.Model):
    """Фото в галерее."""
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    caption = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class HeroImage(db.Model):
    """Фото для карусели на главном экране (hero)."""
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    order = db.Column(db.Integer, default=0)  # порядок показа в карусели
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class VolunteerApplication(db.Model):
    """Заявка от волонтёра (расширенная анкета)."""
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

    def telegram_url(self):
        """Возвращает кликабельную ссылку t.me/username из юзернейма (с @ или без)."""
        if not self.telegram:
            return None
        clean = self.telegram.strip().lstrip("@")
        return f"https://t.me/{clean}" if clean else None


class SiteSetting(db.Model):
    """Произвольные настройки сайта (статистика, контакты, реквизиты)."""
    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.String(500), nullable=True)

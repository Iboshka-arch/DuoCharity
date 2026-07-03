from app import app
from models import db, Admin, SiteSetting

DEFAULT_SETTINGS = {
    "stat_families": "1,200+",
    "stat_kids_elderly": "3,500+",
    "stat_volunteers": "320",
    "stat_events": "85",
    "contact_phone": "+998 90 000 00 00",
    "contact_email": "info@duocharity.uz",
    "contact_address": "Toshkent shahri, Mirzo Ulug'bek tumani",
    "payme_value": "+998 90 000 00 00",
    "click_value": "+998 90 000 00 00",
    "card_value": "8600 1234 5678 9012",
}

with app.app_context():
    db.create_all()

    if not Admin.query.filter_by(username="admin").first():
        admin = Admin(username="admin")
        admin.set_password("changeme123") 
        db.session.add(admin)
        print("Создан администратор: логин 'admin', пароль 'changeme123'")
        print("ВАЖНО: смени пароль после первого входа в /admin/settings")
    else:
        print("Администратор уже существует, пропускаю создание")

    # Создаём базовые настройки, если их ещё нет
    for key, value in DEFAULT_SETTINGS.items():
        if not SiteSetting.query.filter_by(key=key).first():
            db.session.add(SiteSetting(key=key, value=value))

    db.session.commit()
    print("База данных готова: duocharity.db")

import os
import re
from datetime import datetime, timedelta, date
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, session, make_response, send_from_directory
from flask_wtf import CSRFProtect
from werkzeug.utils import secure_filename

from models import db, Admin, Post, GalleryImage, HeroImage, VolunteerApplication, Volunteer, SiteSetting, Event, EventRegistration, EventFeedback, ActivityLog, AdminLoginEvent, NO_TELEGRAM_USERNAME
from translations import get_translator, LANGUAGES, DEFAULT_LANGUAGE
from activity_log import log_activity

import telebot
from bot.handlers import bot as telegram_bot, process_due_deletions
from bot.notifications import notify_new_application
from bot.actions import accept_application
from bot.spam_guard import check_and_handle_spam
from bot.events import (
    request_event_approval,
    close_event_and_notify,
    reopen_event,
    kick_registration,
    pin_announcement,
    create_admin_roster,
    request_event_location,
    refresh_event_displays,
    announce_more_spots,
)

from excel_export import build_active_volunteers_workbook, build_applications_workbook
from flask import send_file

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

app = Flask(__name__)

secret_key = os.environ.get("SECRET_KEY")
if not secret_key:
    if os.environ.get("VERCEL"):
        raise RuntimeError("SECRET_KEY env var must be set in production")
    secret_key = "dev-secret-key-local"
app.config["SECRET_KEY"] = secret_key

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024

database_url = os.environ.get("DATABASE_URL")
if not database_url:
    database_url = f"sqlite:///{os.path.join(BASE_DIR, 'duocharity.db')}"
elif database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
if "neon.tech" in database_url or "postgres" in database_url:
    separator = "&" if "?" in database_url else "?"
    database_url += f"{separator}connect_timeout=20"
app.config["SQLALCHEMY_DATABASE_URI"] = database_url

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

db.init_app(app)
csrf = CSRFProtect(app)

LOGIN_LOCKOUT_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_WINDOW_MINUTES = 15


def get_client_ip():
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr

def allowed_file(filename):
    if not filename or "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in ALLOWED_EXTENSIONS

CYRILLIC_TO_LATIN = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ё": "yo",
    "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sht",
    "ъ": "", "ы": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "ў": "o'", "қ": "q", "ғ": "g'", "ҳ": "h", "е": "e",
}


def _transliterate_word(word):
    chars = []
    for i, ch in enumerate(word.lower()):
        if ch == "е" and i == 0:
            chars.append("ye")
        else:
            chars.append(CYRILLIC_TO_LATIN.get(ch, ch))
    return "".join(chars)


def normalize_name_part(value):
    value = value.strip()
    if not value:
        return value

    words = []
    for word in value.split():
        if any(ch.lower() in CYRILLIC_TO_LATIN for ch in word):
            word = _transliterate_word(word)
        else:
            word = word.lower()
        words.append(word[:1].upper() + word[1:])
    return " ".join(words)

INVALID_NAME_CHARS = re.compile(r'[\d"();<>=\[\]{}\\/]')

def is_valid_name_part(value):
    return bool(value) and len(value) <= 40 and not INVALID_NAME_CHARS.search(value)

def calculate_age(birth_date):
    if not birth_date:
        return None
    today = date.today()
    years = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        years -= 1
    return years

def save_uploaded_file(file_storage):
    if not file_storage or file_storage.filename == "":
        print(f"DEBUG filename: {file_storage.filename if file_storage else 'None'}")
        print(f"DEBUG allowed: {allowed_file(file_storage.filename) if file_storage else 'None'}")
        return None
    if not allowed_file(file_storage.filename):
        print(f"❌ Недопустимый формат файла: {file_storage.filename}")
        return None

    try:
        from imagekitio import ImageKit

        client = ImageKit(
            private_key=os.environ.get("IMAGEKIT_PRIVATE_KEY"),
        )

        filename = secure_filename(file_storage.filename)
        file_data = file_storage.read()

        result = client.files.upload(
            file=file_data,
            file_name=filename,
        )

        return result.url

    except Exception as e:
        print(f"ImageKit upload error: {e}")
        return None

def get_settings():
    return {s.key: s.value for s in SiteSetting.query.all()}


def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get("admin_id"):
            flash("Iltimos, tizimga kiring.", "error")
            return redirect(url_for("admin_login"))
        return view_func(*args, **kwargs)
    return wrapped

def get_current_language():
    return request.cookies.get("lang", DEFAULT_LANGUAGE)


OCCUPATION_LEGACY_MAP = {"talaba": "study", "ishlayman": "work"}


def occupation_label(value, t):
    normalized = OCCUPATION_LEGACY_MAP.get(value, value)
    if normalized == "study":
        return t("vf_occupation_study")
    if normalized == "work":
        return t("vf_occupation_work")
    return value or ""


@app.context_processor
def inject_translator():
    lang = get_current_language()
    t = get_translator(lang)
    return {
        "t": t,
        "current_lang": lang,
        "languages": LANGUAGES,
        "occupation_label": lambda value: occupation_label(value, t),
    }

@csrf.exempt
@app.route("/bot/webhook", methods=["POST"])
def bot_webhook():
    try:
        json_data = request.get_json()
        update = telebot.types.Update.de_json(json_data)

        message = update.message
        if message and message.chat.type == "private":
            if check_and_handle_spam(message.chat.id, message.message_id):
                return "", 200

        telegram_bot.process_new_updates([update])
    except Exception as e:
        print(f"Ошибка обработки апдейта бота: {e}")

    try:
        process_due_deletions()
    except Exception as e:
        print(f"Ошибка отложенного удаления сообщений: {e}")

    return "", 200

@app.route("/set-language/<lang_code>")
def set_language(lang_code):
    if lang_code not in LANGUAGES:
        lang_code = DEFAULT_LANGUAGE

    redirect_target = request.referrer or url_for("home")
    response = make_response(redirect(redirect_target))
    response.set_cookie("lang", lang_code, max_age=60 * 60 * 24 * 365)
    return response

@app.route("/")
def home():
    settings = get_settings()
    stats = {
        "families": settings.get("stat_families", "0"),
        "kids_elderly": settings.get("stat_kids_elderly", "0"),
        "volunteers": settings.get("stat_volunteers", "0"),
        "events": settings.get("stat_events", "0"),
    }
    news_items = Post.query.order_by(Post.created_at.desc()).limit(3).all()
    gallery_images = GalleryImage.query.order_by(GalleryImage.created_at.desc()).all()
    hero_images = HeroImage.query.order_by(HeroImage.order.asc()).all()

    return render_template(
        "index.html",
        stats=stats,
        news_items=news_items,
        gallery_images=gallery_images,
        hero_images=hero_images,
        settings=settings,
    )

@app.route("/robots.txt")
def robots_txt():
    lines = [
        "User-agent: *",
        "Disallow: /admin",
        "Disallow: /bot/webhook",
        "Allow: /",
        f"Sitemap: https://{request.host}/sitemap.xml",
    ]
    return app.response_class("\n".join(lines) + "\n", mimetype="text/plain")

@app.route("/sitemap.xml")
def sitemap_xml():
    base = f"https://{request.host}"
    static_paths = ["/", "/volunteer-form", "/privacy-policy"]
    urls = [{"loc": base + path} for path in static_paths]
    for post in Post.query.order_by(Post.created_at.desc()).all():
        urls.append({
            "loc": f"{base}/news/{post.id}",
            "lastmod": post.created_at.strftime("%Y-%m-%d"),
        })

    xml_parts = ['<?xml version="1.0" encoding="UTF-8"?>',
                 '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for entry in urls:
        xml_parts.append("<url>")
        xml_parts.append(f"<loc>{entry['loc']}</loc>")
        if "lastmod" in entry:
            xml_parts.append(f"<lastmod>{entry['lastmod']}</lastmod>")
        xml_parts.append("</url>")
    xml_parts.append("</urlset>")

    return app.response_class("\n".join(xml_parts), mimetype="application/xml")

@app.route("/admin/init-db")
@login_required
def admin_init_db():
    db.create_all()
    try:
        db.session.execute(db.text("ALTER TABLE volunteer ADD COLUMN IF NOT EXISTS birth_date DATE"))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Не удалось добавить колонку birth_date: {e}")
    flash("База данных обновлена.", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/volunteer-form")
def volunteer_form():
    return render_template("volunteer_form.html")

@app.route("/privacy-policy")
def privacy_policy():
    return render_template("privacy_policy.html")

@app.route("/volunteer", methods=["POST"])
def volunteer_submit():
    first_name = normalize_name_part(request.form.get("first_name", ""))
    last_name = normalize_name_part(request.form.get("last_name", ""))
    phone = request.form.get("phone", "").strip()
    telegram = request.form.get("telegram", "").strip()
    gender = request.form.get("gender", "").strip()
    age = request.form.get("age", "").strip()
    occupation = request.form.get("occupation", "").strip()
    message = request.form.get("message", "").strip()

    if not first_name or not last_name or not phone:
        flash(get_translator(get_current_language())('vf_error_name_phone'), "error")
        return redirect(url_for("volunteer_form"))

    if not is_valid_name_part(first_name) or not is_valid_name_part(last_name):
        flash(get_translator(get_current_language())('vf_error_invalid_name'), "error")
        return redirect(url_for("volunteer_form"))

    full_name = f"{first_name} {last_name}".strip()

    if not gender or not age.isdigit():
        flash(get_translator(get_current_language())('vf_error_required'), "error")
        return redirect(url_for("volunteer_form"))

    existing_volunteer = Volunteer.query.filter(
        db.or_(Volunteer.phone == phone, Volunteer.full_name == full_name)
    ).first()
    if existing_volunteer:
        flash(get_translator(get_current_language())('vf_error_already_volunteer'), "error")
        return redirect(url_for("volunteer_form"))

    cooldown_cutoff = datetime.utcnow() - timedelta(hours=24)
    recent_application = VolunteerApplication.query.filter(
        db.or_(VolunteerApplication.phone == phone, VolunteerApplication.full_name == full_name),
        VolunteerApplication.created_at > cooldown_cutoff,
    ).first()

    if recent_application:
        flash(get_translator(get_current_language())('vf_error_cooldown'), "error")
        return redirect(url_for("volunteer_form"))

    application = VolunteerApplication(
        full_name=full_name,
        phone=phone,
        telegram=telegram or None,
        gender=gender or None,
        age=int(age) if age.isdigit() else None,
        occupation=occupation or None,
        message=message or None,
    )
    db.session.add(application)
    db.session.commit()
    notify_new_application(application)

    return redirect(url_for("volunteer_thanks"))

@app.route("/volunteer-thanks")
def volunteer_thanks():
    return render_template("volunteer_thanks.html")

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        ip = get_client_ip()

        try:
            window_start = datetime.utcnow() - timedelta(minutes=LOGIN_LOCKOUT_WINDOW_MINUTES)
            recent_failures = AdminLoginEvent.query.filter(
                AdminLoginEvent.ip_address == ip,
                AdminLoginEvent.success.is_(False),
                AdminLoginEvent.created_at >= window_start,
            ).count()
        except Exception as e:
            db.session.rollback()
            print(f"Не удалось проверить блокировку входа: {e}")
            recent_failures = 0

        if recent_failures >= LOGIN_LOCKOUT_MAX_ATTEMPTS:
            flash("Слишком много неудачных попыток входа. Попробуйте позже.", "error")
            return render_template("admin/login.html")

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        admin = Admin.query.filter_by(username=username).first()
        success = bool(admin and admin.check_password(password))

        try:
            db.session.add(AdminLoginEvent(
                username_attempted=username,
                success=success,
                ip_address=ip,
                user_agent=request.headers.get("User-Agent", "")[:255],
            ))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Не удалось записать попытку входа: {e}")

        if success:
            session["admin_id"] = admin.id
            log_activity(f"admin:{admin.username}", "admin_login", ip)
            return redirect(url_for("admin_dashboard"))

        flash("Login yoki parol noto'g'ri.", "error")

    return render_template("admin/login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_id", None)
    return redirect(url_for("admin_login"))

@app.route("/admin")
@login_required
def admin_dashboard():
    posts_count = Post.query.count()
    images_count = GalleryImage.query.count()
    new_applications_count = VolunteerApplication.query.filter_by(status="new").count()

    return render_template(
        "admin/dashboard.html",
        posts_count=posts_count,
        images_count=images_count,
        new_applications_count=new_applications_count,
    )


@app.route("/admin/activity")
@login_required
def admin_activity():
    try:
        activity_entries = ActivityLog.query.order_by(ActivityLog.created_at.desc()).limit(200).all()
        login_events = AdminLoginEvent.query.order_by(AdminLoginEvent.created_at.desc()).limit(200).all()
    except Exception as e:
        db.session.rollback()
        print(f"Не удалось загрузить журнал активности: {e}")
        flash("Таблицы журнала ещё не созданы — зайдите на /admin/init-db.", "error")
        activity_entries, login_events = [], []
    return render_template("admin/activity.html", activity_entries=activity_entries, login_events=login_events)


@app.route("/admin/posts")
@login_required
def admin_posts():
    posts = Post.query.order_by(Post.created_at.desc()).all()
    return render_template("admin/posts.html", posts=posts)


@app.route("/admin/posts/new", methods=["GET", "POST"])
@login_required
def admin_post_new():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()

        if not title or not content:
            flash("Sarlavha va matn majburiy.", "error")
            return render_template("admin/post_form.html", post=None)

        image_filename = save_uploaded_file(request.files.get("image"))

        post = Post(title=title, content=content, image_filename=image_filename)
        db.session.add(post)
        db.session.commit()

        flash("Post muvaffaqiyatli qo'shildi.", "success")
        return redirect(url_for("admin_posts"))

    return render_template("admin/post_form.html", post=None)


@app.route("/admin/posts/<int:post_id>/edit", methods=["GET", "POST"])
@login_required
def admin_post_edit(post_id):
    post = Post.query.get_or_404(post_id)

    if request.method == "POST":
        post.title = request.form.get("title", "").strip()
        post.content = request.form.get("content", "").strip()

        new_image = save_uploaded_file(request.files.get("image"))
        if new_image:
            post.image_filename = new_image

        db.session.commit()
        flash("Post yangilandi.", "success")
        return redirect(url_for("admin_posts"))

    return render_template("admin/post_form.html", post=post)


@app.route("/news/<int:post_id>")
def news_detail(post_id):
    post = Post.query.get_or_404(post_id)
    return render_template("news_detail.html", post=post)


@app.route("/admin/posts/<int:post_id>/delete", methods=["POST"])
@login_required
def admin_post_delete(post_id):
    post = Post.query.get_or_404(post_id)
    db.session.delete(post)
    db.session.commit()
    flash("Post o'chirildi.", "success")
    return redirect(url_for("admin_posts"))


@app.route("/admin/gallery")
@login_required
def admin_gallery():
    images = GalleryImage.query.order_by(GalleryImage.created_at.desc()).all()
    return render_template("admin/gallery.html", images=images)


@app.route("/admin/gallery/upload", methods=["POST"])
@login_required
def admin_gallery_upload():
    caption = request.form.get("caption", "").strip()
    filename = save_uploaded_file(request.files.get("image"))

    if not filename:
        flash("Faylni yuklab bo'lmadi. PNG, JPG yoki WEBP formatini tanlang.", "error")
        return redirect(url_for("admin_gallery"))

    image = GalleryImage(filename=filename, caption=caption)
    db.session.add(image)
    db.session.commit()

    flash("Rasm galereyaga qo'shildi.", "success")
    return redirect(url_for("admin_gallery"))


@app.route("/admin/gallery/<int:image_id>/delete", methods=["POST"])
@login_required
def admin_gallery_delete(image_id):
    image = GalleryImage.query.get_or_404(image_id)
    db.session.delete(image)
    db.session.commit()
    flash("Rasm o'chirildi.", "success")
    return redirect(url_for("admin_gallery"))


@app.route("/admin/hero")
@login_required
def admin_hero():
    images = HeroImage.query.order_by(HeroImage.order.asc()).all()
    settings = get_settings()
    return render_template("admin/hero.html", images=images, settings=settings)


@app.route("/admin/hero/upload", methods=["POST"])
@login_required
def admin_hero_upload():
    filename = save_uploaded_file(request.files.get("image"))

    if not filename:
        flash(get_translator(get_current_language())('adm_invalid_file'), "error")
        return redirect(url_for("admin_hero"))

    max_order = db.session.query(db.func.max(HeroImage.order)).scalar() or 0
    image = HeroImage(filename=filename, order=max_order + 1)
    db.session.add(image)
    db.session.commit()

    flash("Rasm hero galereyasiga qo'shildi.", "success")
    return redirect(url_for("admin_hero"))


@app.route("/admin/hero/<int:image_id>/delete", methods=["POST"])
@login_required
def admin_hero_delete(image_id):
    image = HeroImage.query.get_or_404(image_id)
    db.session.delete(image)
    db.session.commit()
    flash("Rasm o'chirildi.", "success")
    return redirect(url_for("admin_hero"))

@app.route('/admin/about-photo/delete', methods=['POST'])
@login_required
def admin_about_photo_delete():
    setting = SiteSetting.query.filter_by(key='about_photo').first()
    if setting:
        setting.value = ''
        db.session.commit()
        flash('Фото успешно удалено', 'success')
    return redirect(url_for('admin_hero'))


@app.route("/admin/hero/about-photo", methods=["POST"])
@login_required
def admin_about_photo_upload():
    filename = save_uploaded_file(request.files.get("about_photo"))

    if not filename:
        flash("Faylni yuklab bo'lmadi.", "error")
        return redirect(url_for("admin_hero"))

    setting = SiteSetting.query.filter_by(key="about_photo").first()
    if setting:
        setting.value = filename
    else:
        db.session.add(SiteSetting(key="about_photo", value=filename))
    db.session.commit()

    flash("'Biz haqimizda' rasmi yangilandi.", "success")
    return redirect(url_for("admin_hero"))

@app.route("/admin/volunteers")
@login_required
def admin_volunteers():
    applications = VolunteerApplication.query.order_by(VolunteerApplication.created_at.desc()).all()
    return render_template("admin/volunteers.html", applications=applications)


@app.route("/admin/volunteers/<int:app_id>/status", methods=["POST"])
@login_required
def admin_volunteer_status(app_id):
    application = VolunteerApplication.query.get_or_404(app_id)
    application.status = request.form.get("status", application.status)
    db.session.commit()
    return redirect(url_for("admin_volunteers"))

@app.route("/admin/volunteers/<int:app_id>/delete", methods=["POST"])
@login_required
def admin_volunteer_delete(app_id):
    application = VolunteerApplication.query.get_or_404(app_id)
    admin = db.session.get(Admin, session["admin_id"])
    full_name = application.full_name
    db.session.delete(application)
    db.session.commit()
    log_activity(f"admin:{admin.username}", "application_delete", full_name)
    flash(get_translator(get_current_language())('adm_volunteer_deleted'), "success")
    return redirect(url_for("admin_volunteers"))

@app.route("/admin/volunteers/<int:app_id>/accept", methods=["POST"])
@login_required
def admin_volunteer_accept(app_id):
    application = VolunteerApplication.query.get_or_404(app_id)

    if application.status == "closed":
        flash("Эта заявка уже обработана.", "error")
        return redirect(url_for("admin_volunteers"))

    admin = db.session.get(Admin, session["admin_id"])
    volunteer, created = accept_application(application, f"admin:{admin.username}")

    if created:
        flash(f"{volunteer.full_name} добавлен(а) в список волонтёров.", "success")
    else:
        flash("Этот номер телефона уже есть в списке волонтёров.", "error")

    return redirect(url_for("admin_volunteers"))

@app.route("/admin/active-volunteers")
@login_required
def admin_active_volunteers():
    search_query = request.args.get("q", "").strip()
    bot_filter = request.args.get("bot", "").strip()
    car_filter = request.args.get("car", "").strip()

    volunteers_query = Volunteer.query
    if search_query:
        like = f"%{search_query}%"
        volunteers_query = volunteers_query.filter(
            db.or_(Volunteer.full_name.ilike(like), Volunteer.phone.ilike(like))
        )
    if bot_filter == "connected":
        volunteers_query = volunteers_query.filter(Volunteer.telegram_chat_id.isnot(None))
    elif bot_filter == "not_connected":
        volunteers_query = volunteers_query.filter(Volunteer.telegram_chat_id.is_(None))
    if car_filter == "with_car":
        volunteers_query = volunteers_query.filter(Volunteer.has_car.is_(True))
    elif car_filter == "without_car":
        volunteers_query = volunteers_query.filter(Volunteer.has_car.isnot(True))

    volunteers = volunteers_query.order_by(Volunteer.created_at.desc()).all()
    return render_template(
        "admin/active_volunteers.html",
        volunteers=volunteers,
        search_query=search_query,
        bot_filter=bot_filter,
        car_filter=car_filter,
    )
 
 
@app.route("/admin/active-volunteers/<int:volunteer_id>/delete", methods=["POST"])
@login_required
def admin_active_volunteer_delete(volunteer_id):
    volunteer = Volunteer.query.get_or_404(volunteer_id)
    admin = db.session.get(Admin, session["admin_id"])
    full_name = volunteer.full_name
    db.session.delete(volunteer)
    db.session.commit()
    log_activity(f"admin:{admin.username}", "volunteer_delete", full_name)
    flash("Волонтёр удалён из списка.", "success")
    return redirect(url_for("admin_active_volunteers"))


def _apply_volunteer_form(volunteer):
    volunteer.full_name = request.form.get("full_name", "").strip()
    volunteer.phone = request.form.get("phone", "").strip()
    volunteer.telegram = request.form.get("telegram", "").strip() or None
    volunteer.gender = request.form.get("gender", "").strip() or None

    birth_date = request.form.get("birth_date", "").strip()
    try:
        volunteer.birth_date = datetime.strptime(birth_date, "%Y-%m-%d").date() if birth_date else None
    except ValueError:
        volunteer.birth_date = None

    age = request.form.get("age", "").strip()
    volunteer.age = int(age) if age.isdigit() else calculate_age(volunteer.birth_date)

    volunteer.occupation = request.form.get("occupation", "").strip() or None

    has_car = request.form.get("has_car", "")
    volunteer.has_car = {"1": True, "0": False}.get(has_car)
    volunteer.car_brand = request.form.get("car_brand", "").strip() or None
    volunteer.car_plate = request.form.get("car_plate", "").strip() or None


@app.route("/admin/active-volunteers/new", methods=["GET", "POST"])
@login_required
def admin_active_volunteer_new():
    t = get_translator(get_current_language())

    if request.method == "POST":
        phone = request.form.get("phone", "").strip()

        if not request.form.get("full_name", "").strip() or not phone:
            flash(t("vf_error_name_phone"), "error")
            return render_template("admin/volunteer_edit_form.html", volunteer=None)

        if Volunteer.query.filter_by(phone=phone).first():
            flash(t("adm_vol_phone_taken"), "error")
            return render_template("admin/volunteer_edit_form.html", volunteer=None)

        volunteer = Volunteer()
        _apply_volunteer_form(volunteer)
        db.session.add(volunteer)
        db.session.commit()

        flash(t("adm_vol_added"), "success")
        return redirect(url_for("admin_active_volunteers"))

    return render_template("admin/volunteer_edit_form.html", volunteer=None)


@app.route("/admin/active-volunteers/<int:volunteer_id>/edit", methods=["GET", "POST"])
@login_required
def admin_active_volunteer_edit(volunteer_id):
    volunteer = Volunteer.query.get_or_404(volunteer_id)
    t = get_translator(get_current_language())

    if request.method == "POST":
        phone = request.form.get("phone", "").strip()

        if not request.form.get("full_name", "").strip() or not phone:
            flash(t("vf_error_name_phone"), "error")
            return render_template("admin/volunteer_edit_form.html", volunteer=volunteer)

        duplicate = Volunteer.query.filter(Volunteer.phone == phone, Volunteer.id != volunteer.id).first()
        if duplicate:
            flash(t("adm_vol_phone_taken"), "error")
            return render_template("admin/volunteer_edit_form.html", volunteer=volunteer)

        _apply_volunteer_form(volunteer)
        db.session.commit()

        flash(t("adm_vol_updated"), "success")
        return redirect(url_for("admin_active_volunteers"))

    return render_template("admin/volunteer_edit_form.html", volunteer=volunteer)
 

@app.route("/admin/events")
@login_required
def admin_events():
    events = Event.query.order_by(Event.created_at.desc()).all()
    counts = {e.id: EventRegistration.query.filter_by(event_id=e.id).count() for e in events}
    return render_template("admin/events.html", events=events, counts=counts)


@app.route("/admin/events/new", methods=["GET", "POST"])
@login_required
def admin_event_new():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        date_text = request.form.get("date_text", "").strip()
        description = request.form.get("description", "").strip()
        location = request.form.get("location", "").strip()
        capacity_raw = request.form.get("capacity", "").strip()

        if not title:
            flash("Название обязательно.", "error")
            return render_template("admin/event_form.html", event=None)

        capacity = int(capacity_raw) if capacity_raw.isdigit() and int(capacity_raw) > 0 else None

        event = Event(
            title=title,
            date_text=date_text or None,
            description=description or None,
            location=location or None,
            capacity=capacity,
        )
        db.session.add(event)
        db.session.commit()

        request_event_approval(event)

        flash("Мероприятие создано, отправлено вам в личку бота на проверку.", "success")
        return redirect(url_for("admin_event_detail", event_id=event.id))

    return render_template("admin/event_form.html", event=None)


@app.route("/admin/events/<int:event_id>")
@login_required
def admin_event_detail(event_id):
    event = Event.query.get(event_id)
    if not event:
        flash("Это мероприятие отменено или удалено.", "error")
        return redirect(url_for("admin_events"))

    registrations = EventRegistration.query.filter_by(event_id=event.id).order_by(EventRegistration.created_at.asc()).all()

    volunteer_ids = [r.volunteer_id for r in registrations]
    volunteers_by_id = {}
    if volunteer_ids:
        volunteers_by_id = {v.id: v for v in Volunteer.query.filter(Volunteer.id.in_(volunteer_ids)).all()}

    rows = [(r, volunteers_by_id[r.volunteer_id]) for r in registrations if r.volunteer_id in volunteers_by_id]

    feedbacks = EventFeedback.query.filter_by(event_id=event.id).order_by(EventFeedback.created_at.desc()).all()
    avg_rating = round(sum(f.rating for f in feedbacks) / len(feedbacks), 1) if feedbacks else None

    return render_template(
        "admin/event_detail.html",
        event=event,
        rows=rows,
        feedbacks=feedbacks,
        avg_rating=avg_rating,
    )


@app.route("/admin/events/<int:event_id>/attendance", methods=["POST"])
@login_required
def admin_event_attendance(event_id):
    event = Event.query.get_or_404(event_id)
    registrations = EventRegistration.query.filter_by(event_id=event.id).all()

    for r in registrations:
        status = request.form.get(f"status_{r.id}")
        if status in ("registered", "arrived", "late", "no_show"):
            r.status = status

    db.session.commit()
    flash("Явка сохранена.", "success")
    return redirect(url_for("admin_event_detail", event_id=event.id))


@app.route("/admin/events/<int:event_id>/registrations/<int:reg_id>/kick", methods=["POST"])
@login_required
def admin_event_kick(event_id, reg_id):
    registration = EventRegistration.query.get_or_404(reg_id)
    if registration.event_id != event_id:
        flash("Ошибка: запись не относится к этому мероприятию.", "error")
        return redirect(url_for("admin_event_detail", event_id=event_id))

    admin = db.session.get(Admin, session["admin_id"])
    volunteer = Volunteer.query.get(registration.volunteer_id)
    kick_registration(registration)
    log_activity(f"admin:{admin.username}", "event_kick", volunteer.full_name if volunteer else str(reg_id))

    flash("Волонтёр исключён из мероприятия.", "success")
    return redirect(url_for("admin_event_detail", event_id=event_id))


@app.route("/admin/events/<int:event_id>/capacity", methods=["POST"])
@login_required
def admin_event_update_capacity(event_id):
    event = Event.query.get_or_404(event_id)

    capacity_raw = request.form.get("capacity", "").strip()
    new_capacity = int(capacity_raw) if capacity_raw.isdigit() and int(capacity_raw) > 0 else None

    old_capacity = event.capacity
    event.capacity = new_capacity
    db.session.commit()

    refresh_event_displays(event)

    opened_spots = new_capacity is not None and (old_capacity is None or new_capacity > old_capacity)
    if opened_spots:
        announce_more_spots(event)
        flash("Мест стало больше — бот сообщил об этом в группе.", "success")
    else:
        flash("Количество мест обновлено.", "success")

    return redirect(url_for("admin_event_detail", event_id=event_id))


@app.route("/admin/events/<int:event_id>/pin-announcement", methods=["POST"])
@login_required
def admin_event_pin_announcement(event_id):
    event = Event.query.get_or_404(event_id)
    if pin_announcement(event):
        flash("Объявление закреплено в группе.", "success")
    else:
        flash("Не удалось закрепить — мероприятие ещё не опубликовано или нет прав у бота.", "error")
    return redirect(url_for("admin_event_detail", event_id=event_id))


@app.route("/admin/events/<int:event_id>/create-admin-roster", methods=["POST"])
@login_required
def admin_event_create_admin_roster(event_id):
    event = Event.query.get_or_404(event_id)
    if create_admin_roster(event):
        flash("Список закреплён в админ-группе.", "success")
    else:
        flash("Не удалось отправить список — проверь ADMIN_GROUP_CHAT_ID.", "error")
    return redirect(url_for("admin_event_detail", event_id=event_id))


@app.route("/admin/events/<int:event_id>/request-location", methods=["POST"])
@login_required
def admin_event_request_location(event_id):
    event = Event.query.get_or_404(event_id)
    request_event_location(event)
    flash("Запрос на локацию отправлен вам в личку бота.", "success")
    return redirect(url_for("admin_event_detail", event_id=event_id))


@app.route("/admin/events/<int:event_id>/close", methods=["POST"])
@login_required
def admin_event_close(event_id):
    event = Event.query.get_or_404(event_id)
    admin = db.session.get(Admin, session["admin_id"])
    close_event_and_notify(event)
    log_activity(f"admin:{admin.username}", "event_close", event.title)
    flash("Регистрация закрыта, участникам разослан запрос на отзыв.", "success")
    return redirect(url_for("admin_event_detail", event_id=event.id))


@app.route("/admin/events/<int:event_id>/open", methods=["POST"])
@login_required
def admin_event_open(event_id):
    event = Event.query.get_or_404(event_id)
    admin = db.session.get(Admin, session["admin_id"])
    reopen_event(event)
    log_activity(f"admin:{admin.username}", "event_open", event.title)
    flash("Регистрация снова открыта.", "success")
    return redirect(url_for("admin_event_detail", event_id=event.id))


@app.route("/admin/events/<int:event_id>/delete", methods=["POST"])
@login_required
def admin_event_delete(event_id):
    event = Event.query.get_or_404(event_id)
    admin = db.session.get(Admin, session["admin_id"])
    title = event.title
    EventRegistration.query.filter_by(event_id=event.id).delete()
    EventFeedback.query.filter_by(event_id=event.id).delete()
    db.session.delete(event)
    db.session.commit()
    log_activity(f"admin:{admin.username}", "event_delete", title)
    flash("Мероприятие удалено.", "success")
    return redirect(url_for("admin_events"))


@app.route("/admin/settings", methods=["GET", "POST"])
@login_required
def admin_settings():
    if request.method == "POST":
        new_password = request.form.get("new_password", "").strip()
        new_password_repeat = request.form.get("new_password_repeat", "").strip()

        if new_password or new_password_repeat:
            if new_password != new_password_repeat:
                flash("Parollar mos kelmadi.", "error")
                return redirect(url_for("admin_settings"))
            if len(new_password) < 6:
                flash("Parol kamida 6 belgidan iborat bo'lishi kerak.", "error")
                return redirect(url_for("admin_settings"))

            admin = db.session.get(Admin, session["admin_id"])
            admin.set_password(new_password)
            db.session.commit()
            log_activity(f"admin:{admin.username}", "password_change")
            flash("Пароль успешно изменен.", "success")
            return redirect(url_for("admin_settings"))

        for key in request.form:
            if key in ("new_password", "new_password_repeat"):
                continue
            setting = SiteSetting.query.filter_by(key=key).first()
            if setting:
                setting.value = request.form.get(key, "").strip()
            else:
                db.session.add(SiteSetting(key=key, value=request.form.get(key, "").strip()))
        db.session.commit()
        flash("Настройки сохранены.", "success")
        return redirect(url_for("admin_settings"))

    settings = get_settings()
    return render_template("admin/settings.html", settings=settings)


@app.route("/admin/normalize-names", methods=["POST"])
@login_required
def admin_normalize_names():
    admin = db.session.get(Admin, session["admin_id"])
    updated = 0

    for application in VolunteerApplication.query.all():
        normalized = normalize_name_part(application.full_name)
        if normalized != application.full_name:
            application.full_name = normalized
            updated += 1

    for volunteer in Volunteer.query.all():
        normalized = normalize_name_part(volunteer.full_name)
        if normalized != volunteer.full_name:
            volunteer.full_name = normalized
            updated += 1

    db.session.commit()
    log_activity(f"admin:{admin.username}", "normalize_names", f"обновлено записей: {updated}")
    flash(f"Обновлено имён: {updated}.", "success")
    return redirect(url_for("admin_settings"))


# (full_name, phone, telegram_username, telegram_user_id, birth_date "YYYY-MM-DD" or None, gender)
# gender определён по имени/суффиксам фамилии — не 100% гарантия, при желании поправить вручную в /admin/active-volunteers
LEGACY_VOLUNTEERS_2025 = [
    ("Temur Saxatov", "998999785570", "temursaxatov", 977708328, "2005-04-09", "male"),
    ("Мадина Саидкаримова", "998998485624", "Dumpling5", 669296132, None, "female"),
    ("Муйдинова", "998998188160", "wwc_ms", 7134319752, "2008-08-18", "female"),
    ("Юсупбаева Шахноза", "998913844649", None, 1601905656, "2005-04-15", "female"),
    ("Бахор Абдиалимова", "998919521809", None, 6891476532, "2006-10-09", "female"),
    ("Дониёр панаев", "998977679615", "Laawrencce", 249600587, "2001-09-07", "male"),
    ("Исмоил Хаитматов", "998903353996", "ismoil_hs", 151332640, "2003-11-22", "male"),
    ("Мирхалил Мирюнусов", "998998333863", "mirxalil_721", 575596775, "2001-07-21", "male"),
    ("Бекбергенова Айзада", "998770101013", None, 5434386561, "2003-03-19", "female"),
    ("Ruzibaeva Laylo", "998930061888", "Laylo_r8", 1016466295, "1990-10-09", "female"),
    ("Binafsha Tadjiboyeva", "998977772967", "binafsha_2509", 1330349778, "2004-09-25", "female"),
    ("Саидазиз Шоисломов", "998909777999", None, 74839853, "2001-02-09", "male"),
    ("Камилова Диёра", "998909549744", "di_kmlva", 2009626080, "2005-06-20", "female"),
    ("Манзура Искандаровна Абдурахманова", "998909489446", "manzura_abdurakhman", 2015824452, None, "female"),
    ("Shoabbos Shomurodov", "998331851805", "shmrdv", 991688894, "2002-11-03", "male"),
    ("Турсунова Мадина", "998901144505", "maiidys", 811240623, "2008-09-09", "female"),
    ("Айбарова Зарина", "998931421360", "aybarovaz", 6614475034, "2006-11-08", "female"),
    ("Raupov Daler", "998997123343", "justDALER", 7217630462, "2007-12-26", "male"),
    ("Иззатхон Вахобжонова", "998933065226", "Izzatkhon_714", 1864246980, "2005-07-14", "female"),
    ("Исраилов Абдуллох", "998913270200", "u711z", 480469113, "2009-01-30", "male"),
    ("Азимбаева Мохидил", "998900015196", "mohidil15", 671858283, "2003-11-15", "female"),
    ("Бобуржон Бойматов", "998903751940", "okgoo", 1814162588, "2000-04-09", "male"),
    ("Хабиба Разакбергенова", "998331788866", None, 1772960531, "1999-08-17", "female"),
    ("Зиеда Аскарова", "998935273600", "ziyoodaa", 1096848488, "2005-04-26", "female"),
    ("Назарова Жасмин", "998940882244", "nazarrovn", 2095493012, "2005-03-01", "female"),
    ("Азиза Абдумаликова", "998991840717", None, 947276018, "2005-03-12", "female"),
    ("Шухрат Рахимжанов", "998888778778", "RakhimjonovShukhrat", 6489324562, "1998-09-09", "male"),
    ("Davlat Xudoykulov", "998334250596", "dkhudoykulov", 1069303370, "2004-12-22", "male"),
    ("Фарангиз Сирожиддинова", "998935188103", "xasanovnaa", 1166832924, "2006-04-14", "female"),
    ("Макнуна Каримжонова", "998974801106", "maknuna_k", 704711947, "2006-07-10", "female"),
    ("Фаррух Алижанов", "998979997722", "Farrukh_Alijanov", 999348381, "2005-05-07", "male"),
    ("Abdulaziz", "6584355264", None, 779108551, "2001-01-01", "male"),
    ("Диёрахон Мухиддинова", "998977325505", None, 634313742, "2006-09-17", "female"),
    ("Хакимова Нисонур", "998909416867", "Nisonuuur", 460706466, "2005-09-28", "female"),
    ("Наврузбек Журабеков", "998947315557", None, 7815682602, "2004-03-13", "male"),
    ("Abdukarimova Nigina", "998770167579", "nwjns_005", 1081487668, "2006-10-15", "female"),
    ("Комила Собиржонзода", "998909879667", "komila_khon", 1257978360, "2004-07-31", "female"),
    ("Баходиров Абдулазиз", "998917732232", "bakhod1_rof", 6032838700, "2005-01-25", "male"),
    ("Зокиров Нуриислом", "998909729050", "nuriislamzakirov", 927769938, "2003-08-29", "male"),
    ("Саидкаримова Нигина", "998998485642", "Niginasz", 649621945, "2003-06-13", "female"),
    ("Носиржонова Муниса", "998935177022", None, 1832641193, "2003-10-08", "female"),
    ("Махаммаджонов Абдурахим Махаммаджонович", "998997978989", "abduraxmm", 1851852120, "2002-11-06", "male"),
    ("Улугбек Нухритдинхаджаев", "998990017800", None, 457471867, "2004-05-11", "male"),
    ("Жасуржон Турдалиев", "998909114105", None, 5576002727, "2004-10-20", "male"),
    ("Axmadbekova Diyora", "998902008620", "one_love_eda", 1918909026, None, "female"),
    ("Kalbaeva Dinara", "998937048278", None, 6631134405, "2005-09-24", "female"),
]


@app.route("/admin/import-legacy-volunteers", methods=["POST"])
@login_required
def admin_import_legacy_volunteers():
    admin = db.session.get(Admin, session["admin_id"])

    backfilled = 0
    inserted = 0
    skipped = []
    needs_review = []

    for full_name, phone, telegram_username, telegram_user_id, birth_date_str, gender in LEGACY_VOLUNTEERS_2025:
        name = normalize_name_part(full_name)
        telegram = f"@{telegram_username}" if telegram_username else NO_TELEGRAM_USERNAME
        birth_date = datetime.strptime(birth_date_str, "%Y-%m-%d").date() if birth_date_str else None
        age = calculate_age(birth_date)
        occupation = None if age is None else ("study" if age < 18 else "work")

        if not birth_date:
            needs_review.append(name)

        existing = Volunteer.query.filter_by(telegram_user_id=telegram_user_id).first()
        if existing:
            changed = False
            if birth_date and not existing.birth_date:
                existing.birth_date = birth_date
                changed = True
            if age and not existing.age:
                existing.age = age
                changed = True
            if gender and not existing.gender:
                existing.gender = gender
                changed = True
            if occupation and not existing.occupation:
                existing.occupation = occupation
                changed = True
            if not existing.telegram:
                existing.telegram = telegram
                changed = True
            if changed:
                backfilled += 1
            continue

        if Volunteer.query.filter_by(phone=phone).first():
            skipped.append(f"{name} (телефон {phone} уже занят другим волонтёром)")
            continue

        db.session.add(Volunteer(
            full_name=name,
            phone=phone,
            telegram=telegram,
            telegram_user_id=telegram_user_id,
            birth_date=birth_date,
            age=age,
            gender=gender,
            occupation=occupation,
        ))
        inserted += 1

    db.session.commit()

    summary = f"дозаполнено: {backfilled}, создано новых: {inserted}, пропущено: {len(skipped)}"
    log_activity(f"admin:{admin.username}", "import_legacy_volunteers", summary)

    flash(f"Импорт старой базы завершён — {summary}.", "success")
    if needs_review:
        flash("Дату рождения не удалось разобрать, проверьте вручную: " + ", ".join(needs_review), "error")
    if skipped:
        flash("Пропущены из-за конфликта телефона: " + ", ".join(skipped), "error")

    return redirect(url_for("admin_active_volunteers"))


@app.route("/admin/volunteers/export")
@login_required
def admin_volunteers_export():
    applications = VolunteerApplication.query.order_by(VolunteerApplication.created_at.desc()).all()
    output = build_applications_workbook(applications)

    return send_file(
        output,
        as_attachment=True,
        download_name="duo_applications.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

@app.route("/admin/active-volunteers/export")
@login_required
def admin_active_volunteers_export():
    volunteers = Volunteer.query.order_by(Volunteer.created_at.desc()).all()
    output = build_active_volunteers_workbook(volunteers)

    return send_file(
        output,
        as_attachment=True,
        download_name="duo_volunteers.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


if __name__ == "__main__":
    app.run(debug=True)

import os
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, session, make_response, send_from_directory
from werkzeug.utils import secure_filename

from models import db, Admin, Post, GalleryImage, HeroImage, VolunteerApplication, Volunteer, SiteSetting
from translations import get_translator, LANGUAGES, DEFAULT_LANGUAGE

import telebot
from bot.handlers import bot as telegram_bot
from bot.notifications import notify_new_application
from bot.actions import accept_application

from io import BytesIO
import openpyxl
from flask import send_file
 
from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key-local")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024

load_dotenv() 

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

@app.route("/debug-db")
def debug_db():
    import os
    db_url = os.environ.get("DATABASE_URL", "NOT SET")
    return f"DATABASE_URL starts with: {db_url[:30] if db_url != 'NOT SET' else 'NOT SET'}"
        
def allowed_file(filename):
    if not filename or "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in ALLOWED_EXTENSIONS

@app.route("/test-imagekit-upload")
def test_imagekit_upload():
    try:
        from imagekitio import ImageKit

        client = ImageKit(
            private_key=os.environ.get("IMAGEKIT_PRIVATE_KEY"),
        )

        result = client.files.upload(
            file=b"test",
            file_name="test.txt",
        )

        return f"""
OK!

URL: {result.url}
ID: {result.file_id}
"""

    except Exception as e:
        import traceback
        return f"ERROR:\n{traceback.format_exc()}"

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


@app.context_processor
def inject_translator():
    lang = get_current_language()
    return {
        "t": get_translator(lang),
        "current_lang": lang,
        "languages": LANGUAGES,
    }

@app.route("/bot/webhook", methods=["POST"])
def bot_webhook():
    json_data = request.get_json()
    update = telebot.types.Update.de_json(json_data)
    telegram_bot.process_new_updates([update])
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

@app.route("/admin/init-db")
@login_required
def admin_init_db():
    db.create_all()
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
    full_name = request.form.get("full_name", "").strip()
    phone = request.form.get("phone", "").strip()
    telegram = request.form.get("telegram", "").strip()
    gender = request.form.get("gender", "").strip()
    age = request.form.get("age", "").strip()
    occupation = request.form.get("occupation", "").strip()
    message = request.form.get("message", "").strip()

    if not full_name or not phone:
        flash(get_translator(get_current_language())('vf_error_name_phone'), "error")
        return redirect(url_for("volunteer_form"))

    if not gender or not age.isdigit():
        flash(get_translator(get_current_language())('vf_error_required'), "error")
        return redirect(url_for("volunteer_form"))

    cooldown_cutoff = datetime.utcnow() - timedelta(hours=24)
    recent_application = VolunteerApplication.query.filter(
        VolunteerApplication.phone == phone,
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
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        admin = Admin.query.filter_by(username=username).first()
        if admin and admin.check_password(password):
            session["admin_id"] = admin.id
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
def admin_about_photo_delete():
    # Находим настройку в базе данных и очищаем путь к фото
    setting = SiteSetting.query.filter_by(key='about_photo').first() # или как у вас устроена модель settings
    if setting:
        setting.value = '' # Удаляем путь к файлу из настроек
        db.session.commit()
        flash('Фото успешно удалено', 'success')
    return redirect(url_for('admin_hero')) # Перенаправление обратно на страницу


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
    db.session.delete(application)
    db.session.commit()
    flash(get_translator(get_current_language())('adm_volunteer_deleted'), "success")
    return redirect(url_for("admin_volunteers"))

@app.route("/admin/volunteers/<int:app_id>/accept", methods=["POST"])
@login_required
def admin_volunteer_accept(app_id):
    application = VolunteerApplication.query.get_or_404(app_id)

    if application.status == "closed":
        flash("Эта заявка уже обработана.", "error")
        return redirect(url_for("admin_volunteers"))

    volunteer, created = accept_application(application)

    if created:
        flash(f"{volunteer.full_name} добавлен(а) в список волонтёров.", "success")
    else:
        flash("Этот номер телефона уже есть в списке волонтёров.", "error")

    return redirect(url_for("admin_volunteers"))
    
@app.route("/admin/active-volunteers")
@login_required
def admin_active_volunteers():
    volunteers = Volunteer.query.order_by(Volunteer.created_at.desc()).all()
    return render_template("admin/active_volunteers.html", volunteers=volunteers)
 
 
@app.route("/admin/active-volunteers/<int:volunteer_id>/delete", methods=["POST"])
@login_required
def admin_active_volunteer_delete(volunteer_id):
    volunteer = Volunteer.query.get_or_404(volunteer_id)
    db.session.delete(volunteer)
    db.session.commit()
    flash("Волонтёр удалён из списка.", "success")
    return redirect(url_for("admin_active_volunteers"))
 

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

@app.route("/admin/volunteers/export")
@login_required
def admin_volunteers_export():
    volunteers = Volunteer.query.order_by(Volunteer.created_at.desc()).all()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Волонтёры"

    headers = ["ФИО", "Телефон", "Telegram", "Пол", "Возраст", "Занятость", "Есть авто", "Номер авто", "Дата регистрации"]
    ws.append(headers)

    for v in volunteers:
        gender_label = "Мужской" if v.gender == "male" else "Женский" if v.gender == "female" else ""
        ws.append([
            v.full_name,
            v.phone,
            v.telegram or "",
            gender_label,
            v.age or "",
            v.occupation or "",
            "Да" if v.has_car else "Нет",
            v.car_plate or "",
            v.formatted_date(),
        ])

    for column_cells in ws.columns:
        length = max(len(str(cell.value)) if cell.value else 0 for cell in column_cells)
        ws.column_dimensions[column_cells[0].column_letter].width = max(12, length + 2)

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="duo_volunteers.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

if __name__ == "__main__":
    app.run(debug=True)

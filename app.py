import os
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, session, make_response, send_from_directory
from werkzeug.utils import secure_filename

from models import db, Admin, Post, GalleryImage, HeroImage, VolunteerApplication, SiteSetting
from translations import get_translator, LANGUAGES, DEFAULT_LANGUAGE

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key-local")
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

@app.before_first_request
def initialize_database():
    try:
        with app.app_context():
            db.create_all()
            from init_db import DEFAULT_SETTINGS, Admin, SiteSetting
            if not Admin.query.filter_by(username="admin").first():
                admin = Admin(username="admin")
                admin.set_password("changeme123")
                db.session.add(admin)
            for key, value in DEFAULT_SETTINGS.items():
                if not SiteSetting.query.filter_by(key=key).first():
                    db.session.add(SiteSetting(key=key, value=value))
            db.session.commit()
    except Exception as e:
        print(f"DB init warning: {e}")

@app.route("/init-db")
def init_db_route():
    initialize_database()
    return "Database initialized"

db.init_app(app)

@app.route("/init-db")
def init_db_route():
    try:
        with app.app_context():
            db.create_all()
            return "✅ Tables created successfully! (только таблицы)"
    except Exception as e:
        return f"❌ Error: {str(e)}", 500

@app.route("/init-db")
def init_db_route():
    with app.app_context():
        db.create_all()
        print("Tables created")
    return "Database initialized"

@app.route("/debug-db")
def debug_db():
    import os
    db_url = os.environ.get("DATABASE_URL", "NOT SET")
    return f"DATABASE_URL starts with: {db_url[:30] if db_url != 'NOT SET' else 'NOT SET'}"
        
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_uploaded_file(file_storage):
    if not file_storage or file_storage.filename == "":
        return None
    if not allowed_file(file_storage.filename):
        return None

    try:
        from imagekitio import ImageKit
        from imagekitio.models.UploadFileRequestOptions import UploadFileRequestOptions
        import time

        imagekit = ImageKit(
            private_key=os.environ.get("IMAGEKIT_PRIVATE_KEY"),
            public_key=os.environ.get("IMAGEKIT_PUBLIC_KEY"),
            url_endpoint=os.environ.get("IMAGEKIT_URL_ENDPOINT"),
        )

        filename = secure_filename(file_storage.filename)
        unique_name = f"{int(time.time())}_{filename}"
        file_data = file_storage.read()

        result = imagekit.upload(
            file=file_data,
            file_name=unique_name,
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


@app.route("/set-language/<lang_code>")
def set_language(lang_code):
    if lang_code not in LANGUAGES:
        lang_code = DEFAULT_LANGUAGE

    # Возвращаемся туда, откуда пришёл запрос (или на главную, если неизвестно)
    redirect_target = request.referrer or url_for("home")
    response = make_response(redirect(redirect_target))
    response.set_cookie("lang", lang_code, max_age=60 * 60 * 24 * 365)
    return response


# ---------- ПУБЛИЧНЫЕ СТРАНИЦЫ ----------

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


@app.route("/volunteer-form")
def volunteer_form():
    return render_template("volunteer_form.html")


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
        flash("Ism va telefon raqamingizni kiriting.", "error")
        return redirect(url_for("volunteer_form"))

    # Защита от спама: один и тот же номер телефона не может отправлять
    # заявки чаще, чем раз в 24 часа.
    cooldown_cutoff = datetime.utcnow() - timedelta(hours=24)
    recent_application = VolunteerApplication.query.filter(
        VolunteerApplication.phone == phone,
        VolunteerApplication.created_at > cooldown_cutoff,
    ).first()

    if recent_application:
        flash("Siz oxirgi 24 soat ichida ariza yubordingiz. Iltimos, keyinroq qayta urinib ko'ring.", "error")
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

    return redirect(url_for("volunteer_thanks"))


@app.route("/volunteer-thanks")
def volunteer_thanks():
    return render_template("volunteer_thanks.html")


# ---------- АДМИНКА: ЛОГИН / ЛОГАУТ ----------

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


# ---------- АДМИНКА: ГЛАВНАЯ ----------

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


# ---------- АДМИНКА: НОВОСТИ ----------

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


# ---------- АДМИНКА: ГАЛЕРЕЯ ----------

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


# ---------- АДМИНКА: HERO КАРУСЕЛЬ ----------

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
        flash("Faylni yuklab bo'lmadi. PNG, JPG yoki WEBP formatini tanlang.", "error")
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


# ---------- АДМИНКА: ЗАЯВКИ ВОЛОНТЁРОВ ----------

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


# ---------- АДМИНКА: НАСТРОЙКИ САЙТА ----------

@app.route("/admin/settings", methods=["GET", "POST"])
@login_required
def admin_settings():
    if request.method == "POST":
        # Смена пароля (если поля заполнены)
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
            flash("Parol muvaffaqiyatli o'zgartirildi.", "success")
            return redirect(url_for("admin_settings"))

        # Обновление обычных настроек
        for key in request.form:
            if key in ("new_password", "new_password_repeat"):
                continue
            setting = SiteSetting.query.filter_by(key=key).first()
            if setting:
                setting.value = request.form.get(key, "").strip()
            else:
                db.session.add(SiteSetting(key=key, value=request.form.get(key, "").strip()))
        db.session.commit()
        flash("Sozlamalar saqlandi.", "success")
        return redirect(url_for("admin_settings"))

    settings = get_settings()
    return render_template("admin/settings.html", settings=settings)


if __name__ == "__main__":
    app.run(debug=True)

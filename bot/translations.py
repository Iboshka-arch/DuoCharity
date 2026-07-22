BOT_TEXTS = {
    "uz": {
        "start_greeting": "Assalomu alaykum! 👋 DUO Charity botiga xush kelibsiz. Xabarnomalar yuborishimiz uchun telefon raqamingizni ulashing.",
        "not_matched": "Raqamingiz DUO Charity faol volontyorlari ro'yxatida topilmadi.\n\nAnketani shu yerda to'ldiring:\n{form_link}\n\nSavollar: @Duo_charity_admin",
        "matched": "Rahmat, {name}! Siz DUO Charity xabarnomalariga ulandingiz. ✅",
        "choose_language": "Iltimos, tilni tanlang / Пожалуйста, выберите язык:",
        "ask_car": "Yuk tashish uchun shaxsiy avtomobilingiz bormi? 🚗",
        "car_yes": "Ha",
        "car_no": "Yo'q",
        "ask_car_brand": "Ajoyib! Avtomobil markasini yozing (masalan: Chevrolet Cobalt).",
        "ask_car_plate": "Endi avtomobil raqamini yozing. Masalan: 01 X 111 XX",
        "car_saved": "Ma'lumot saqlandi. Rahmat! 🙏",
        "car_declined": "Tushunarli, rahmat!",
        "fallback": "Men hozircha faqat volontyorlarni ro'yxatga olaman. Yordam: @Duo_charity_admin",
        "own_contact_only": "Iltimos, o'zingizning raqamingizni ulashing.",
    },
    "ru": {
        "start_greeting": "Здравствуйте! 👋 Добро пожаловать в бота DUO Charity. Чтобы присылать уведомления, поделитесь номером телефона.",
        "not_matched": "Не нашли ваш номер в списке действующих волонтёров.\n\nЗаполните анкету здесь:\n{form_link}\n\nВопросы: @Duo_charity_admin",
        "matched": "Спасибо, {name}! Вы подключены к уведомлениям DUO Charity. ✅",
        "choose_language": "Iltimos, tilni tanlang / Пожалуйста, выберите язык:",
        "ask_car": "Есть ли у вас личный автомобиль для перевозки продуктов и вещей? 🚗",
        "car_yes": "Да",
        "car_no": "Нет",
        "ask_car_brand": "Отлично! Напишите марку автомобиля (например: Chevrolet Cobalt).",
        "ask_car_plate": "Теперь напишите номер автомобиля. Пример: 01 X 111 XX",
        "car_saved": "Данные сохранены. Спасибо! 🙏",
        "car_declined": "Понял, спасибо!",
        "fallback": "Я пока умею только регистрировать волонтёров. Помощь: @Duo_charity_admin",
        "own_contact_only": "Пожалуйста, поделитесь своим собственным номером.",
    },
}


def bt(key, lang="ru", **kwargs):
    lang = lang if lang in BOT_TEXTS else "ru"
    text = BOT_TEXTS[lang].get(key, BOT_TEXTS["ru"].get(key, key))
    return text.format(**kwargs) if kwargs else text
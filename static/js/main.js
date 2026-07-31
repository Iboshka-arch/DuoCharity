document.addEventListener("DOMContentLoaded", function () {

const promoOverlay = document.getElementById("promoOverlay");
    const promoClose = document.getElementById("promoClose");

    if (promoOverlay && !sessionStorage.getItem("promoShown")) {
        setTimeout(function () {
            promoOverlay.classList.add("show");
            sessionStorage.setItem("promoShown", "1");
        }, 2600);

        function closePromo() {
            promoOverlay.classList.remove("show");
        }

        if (promoClose) {
            promoClose.addEventListener("click", closePromo);
        }

        promoOverlay.addEventListener("click", function (e) {
            if (e.target === promoOverlay) closePromo();
        });

        promoOverlay.querySelectorAll("a").forEach(function (link) {
            link.addEventListener("click", closePromo);
        });
    }
    
    // ---------- Анимация появления секций при скролле ----------
    const animatedSections = document.querySelectorAll(
        ".about-grid, .gallery-grid, .news-grid, .donate-options, .stats-grid"
    );

    if ("IntersectionObserver" in window && animatedSections.length) {
        const observer = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (entry.isIntersecting) {
                    entry.target.classList.add("fade-in-visible");
                    observer.unobserve(entry.target);
                }
            });
        }, { threshold: 0.15 });

        animatedSections.forEach(function (section) {
            section.classList.add("fade-in-hidden");
            observer.observe(section);
        });
    }

    // ---------- Мобильное меню (гамбургер) ----------
    const burgerBtn = document.getElementById("burgerBtn");
    const mobileNav = document.getElementById("mobileNav");

    if (burgerBtn && mobileNav) {
        burgerBtn.addEventListener("click", function () {
            mobileNav.classList.toggle("open");
        });

        mobileNav.querySelectorAll("a").forEach(function (link) {
            link.addEventListener("click", function () {
                mobileNav.classList.remove("open");
            });
        });
    }

    // ---------- Переключатель языка (десктоп, выпадающее меню) ----------
    const langToggle = document.getElementById("langToggle");
    const langDropdown = document.getElementById("langDropdown");

    if (langToggle && langDropdown) {
        langToggle.addEventListener("click", function (e) {
            e.stopPropagation();
            langDropdown.classList.toggle("open");
        });

        document.addEventListener("click", function () {
            langDropdown.classList.remove("open");
        });
    }

    // ---------- Переключатель языка (мобильный бургер) ----------
    const langBurgerBtn = document.getElementById("langBurgerBtn");
    const mobileLangDropdown = document.getElementById("mobileLangDropdown");

    if (langBurgerBtn && mobileLangDropdown) {
        langBurgerBtn.addEventListener("click", function (e) {
            e.stopPropagation();
            mobileLangDropdown.classList.toggle("show");
        });

        document.addEventListener("click", function (e) {
            if (!mobileLangDropdown.contains(e.target) && !langBurgerBtn.contains(e.target)) {
                mobileLangDropdown.classList.remove("show");
            }
        });
    }

    // ---------- Hero карусель ----------
    const carousel = document.getElementById("heroCarousel");

    if (carousel) {
        const slides = carousel.querySelectorAll(".hero-carousel-slide");
        const dots = carousel.querySelectorAll(".hero-carousel-dot");
        const prevBtn = carousel.querySelector(".hero-carousel-prev");
        const nextBtn = carousel.querySelector(".hero-carousel-next");
        let currentIndex = 0;
        let autoplayTimer = null;

        function showSlide(index) {
            slides.forEach(function (slide, i) {
                slide.classList.toggle("active", i === index);
            });
            dots.forEach(function (dot, i) {
                dot.classList.toggle("active", i === index);
            });
            currentIndex = index;
        }

        function nextSlide() {
            const newIndex = (currentIndex + 1) % slides.length;
            showSlide(newIndex);
        }

        function prevSlide() {
            const newIndex = (currentIndex - 1 + slides.length) % slides.length;
            showSlide(newIndex);
        }

        function startAutoplay() {
            stopAutoplay();
            autoplayTimer = setInterval(nextSlide, 3000);
        }

        function stopAutoplay() {
            if (autoplayTimer) clearInterval(autoplayTimer);
        }

        if (slides.length > 1) {
            startAutoplay();

            if (nextBtn) {
                nextBtn.addEventListener("click", function () {
                    nextSlide();
                    startAutoplay();
                });
            }

            if (prevBtn) {
                prevBtn.addEventListener("click", function () {
                    prevSlide();
                    startAutoplay();
                });
            }

            dots.forEach(function (dot, i) {
                dot.addEventListener("click", function () {
                    showSlide(i);
                    startAutoplay();
                });
            });

            // Останавливаем автопрокрутку, когда вкладка не активна (экономия ресурсов)
            document.addEventListener("visibilitychange", function () {
                if (document.hidden) {
                    stopAutoplay();
                } else {
                    startAutoplay();
                }
            });
        }
    }

    // ---------- Реквизиты для доната (попап с копированием) ----------
    function setupDonateCard(triggerId, popoverId, copyBtnId, copyValueId) {
        const trigger = document.getElementById(triggerId);
        const popover = document.getElementById(popoverId);
        const copyBtn = document.getElementById(copyBtnId);
        const copyValue = document.getElementById(copyValueId);

        if (trigger && popover) {
            trigger.addEventListener("click", function (e) {
                e.stopPropagation();
                const isHidden = popover.hidden;
                popover.hidden = !isHidden;
                trigger.setAttribute("aria-expanded", String(isHidden));
            });

            popover.addEventListener("click", function (e) {
                e.stopPropagation();
            });

            document.addEventListener("click", function () {
                popover.hidden = true;
                trigger.setAttribute("aria-expanded", "false");
            });
        }

        if (copyBtn && copyValue) {
            copyBtn.addEventListener("click", function () {
                const value = copyValue.textContent.trim();
                const copiedText = copyBtn.dataset.copiedText || "Copied!";
                const defaultText = copyBtn.dataset.defaultText || copyBtn.textContent;

                function showCopied() {
                    copyBtn.textContent = copiedText;
                    setTimeout(function () {
                        copyBtn.textContent = defaultText;
                    }, 2000);
                }

                if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(value).then(showCopied).catch(function () {
                        showCopied();
                    });
                } else {
                    const tempInput = document.createElement("textarea");
                    tempInput.value = value;
                    tempInput.style.position = "fixed";
                    tempInput.style.opacity = "0";
                    document.body.appendChild(tempInput);
                    tempInput.select();
                    try {
                        document.execCommand("copy");
                    } catch (err) {
                        // копирование не поддерживается — пользователь всё равно видит значение в попапе
                    }
                    document.body.removeChild(tempInput);
                    showCopied();
                }
            });
        }
    }

    setupDonateCard("donateCardTrigger", "donateCardPopover", "donateCopyBtn", "donateCopyValue");
    setupDonateCard("donateHumoTrigger", "donateHumoPopover", "donateHumoCopyBtn", "donateHumoCopyValue");

});
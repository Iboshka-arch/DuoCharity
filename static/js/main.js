document.addEventListener("DOMContentLoaded", function () {

// ---------- Промо-попап при первом заходе ----------
    const promoOverlay = document.getElementById("promoOverlay");
    const promoClose = document.getElementById("promoClose");

    if (promoOverlay) {
        const alreadyShown = localStorage.getItem("duoPromoShown");

        if (!alreadyShown) {
            setTimeout(function () {
                promoOverlay.classList.add("show");
            }, 2500); // 
        }

        function closePromo() {
            promoOverlay.classList.remove("show");
            localStorage.setItem("duoPromoShown", "1");
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
            autoplayTimer = setInterval(nextSlide, 5000);
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

});
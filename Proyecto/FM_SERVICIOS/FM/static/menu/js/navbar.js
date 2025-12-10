document.addEventListener("DOMContentLoaded", () => {
  const overlay = document.getElementById("loginOverlay");
  const openBtn = document.getElementById("navbarProfileBtn");
  const closeBtn = document.getElementById("loginOverlayClose");
  const backdrop = document.querySelector("[data-close-overlay]");
  const usernameInput = document.getElementById("overlay_username");
  const isLogged = openBtn && openBtn.dataset.logged === "1";
  const servicesWrapper = document.querySelector("[data-services-dropdown]");
  const servicesToggle = document.getElementById("servicesToggle");
  const servicesPanel = document.getElementById("servicesDropdown");
  const navbar = document.querySelector(".site-navbar");
  const menuToggle = document.getElementById("navbarMenuToggle");
  const menu = document.getElementById("navbarMenu");
  let dropdownTimer;

  const closeMenu = () => {
    if (!menu || !menuToggle) return;
    menu.classList.remove("is-open");
    menuToggle.classList.remove("is-open");
    menuToggle.setAttribute("aria-expanded", "false");
  };
  const toggleMenu = () => {
    if (!menu || !menuToggle) return;
    const willOpen = !menu.classList.contains("is-open");
    menu.classList.toggle("is-open", willOpen);
    menuToggle.classList.toggle("is-open", willOpen);
    menuToggle.setAttribute("aria-expanded", willOpen ? "true" : "false");
  };

  const toggleOverlay = (show) => {
    if (!overlay) return;
    closeMenu();
    overlay.classList.toggle("is-active", show);
    overlay.classList.toggle("show", show);
    overlay.style.display = show ? "flex" : "none";
    overlay.setAttribute("aria-hidden", show ? "false" : "true");

    if (show) {
      openBtn && openBtn.setAttribute("aria-expanded", "true");
      const focusTarget = isLogged ? closeBtn : usernameInput;
      setTimeout(() => focusTarget && focusTarget.focus(), 120);
      document.body.style.overflow = "hidden";
      document.documentElement.style.overflow = "hidden";
    } else {
      openBtn && openBtn.setAttribute("aria-expanded", "false");
      document.body.style.overflow = "";
      document.documentElement.style.overflow = "";
    }
  };

  if (openBtn) {
    openBtn.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      toggleOverlay(true);
    });
  }
  [closeBtn, backdrop].forEach((el) => {
    el && el.addEventListener("click", () => toggleOverlay(false));
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") {
      toggleOverlay(false);
      if (servicesWrapper) {
        servicesWrapper.classList.remove("is-open");
        servicesToggle && servicesToggle.setAttribute("aria-expanded", "false");
      }
      closeMenu();
    }
  });

  const openDropdown = () => {
    if (!servicesWrapper) return;
    servicesWrapper.classList.add("is-open");
    servicesToggle && servicesToggle.setAttribute("aria-expanded", "true");
  };
  const closeDropdown = () => {
    if (!servicesWrapper) return;
    servicesWrapper.classList.remove("is-open");
    servicesToggle && servicesToggle.setAttribute("aria-expanded", "false");
  };

  if (servicesWrapper && servicesToggle && servicesPanel) {
    servicesToggle.addEventListener("click", (ev) => {
      ev.preventDefault();
      const isOpen = servicesWrapper.classList.contains("is-open");
      if (isOpen) {
        closeDropdown();
      } else {
        openDropdown();
      }
    });
    servicesWrapper.addEventListener("mouseenter", () => {
      if (dropdownTimer) clearTimeout(dropdownTimer);
      openDropdown();
    });
    servicesWrapper.addEventListener("mouseleave", () => {
      dropdownTimer = setTimeout(closeDropdown, 120);
    });
    document.addEventListener("click", (ev) => {
      if (!servicesWrapper.contains(ev.target)) {
        closeDropdown();
      }
    });
  }

  const handleScroll = () => {
    if (!navbar) return;
    if (window.scrollY > 10) {
      navbar.classList.add("is-scrolled");
    } else {
      navbar.classList.remove("is-scrolled");
    }
  };
  // Asegura que la pagina quede desbloqueada por si algun overlay quedo abierto
  document.body.style.overflow = "";
  document.documentElement.style.overflow = "";
  handleScroll();
  window.addEventListener("scroll", handleScroll, { passive: true });

  // Fallback para cerrar alerts si Bootstrap JS no esta inicializado
  document.addEventListener("click", (e) => {
    const dismiss = e.target.closest('[data-bs-dismiss="alert"]');
    if (!dismiss) return;
    const alertEl = dismiss.closest(".alert");
    if (alertEl) {
      try {
        if (window.bootstrap && bootstrap.Alert) {
          const inst = bootstrap.Alert.getOrCreateInstance(alertEl);
          inst.close();
        } else {
          alertEl.classList.remove("show");
          alertEl.parentNode && alertEl.parentNode.removeChild(alertEl);
        }
      } catch (_) {
        alertEl.classList.remove("show");
        alertEl.parentNode && alertEl.parentNode.removeChild(alertEl);
      }
    }
  });

  if (menuToggle && menu) {
    menuToggle.addEventListener("click", (ev) => {
      ev.preventDefault();
      toggleMenu();
    });
    document.addEventListener("click", (ev) => {
      if (!menu.contains(ev.target) && !menuToggle.contains(ev.target)) {
        closeMenu();
      }
    });
    window.addEventListener("resize", () => {
      if (window.innerWidth > 992) {
        closeMenu();
      }
    });
  }
});

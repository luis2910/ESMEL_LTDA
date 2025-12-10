document.addEventListener("DOMContentLoaded", () => {
  const overlay = document.getElementById("loginOverlay");
  const openBtn = document.getElementById("navbarProfileBtn");
  const closeBtn = document.getElementById("loginOverlayClose");
  const backdrop = document.querySelector("[data-close-overlay]");
  const usernameInput = document.getElementById("overlay_username");
  const isLogged = openBtn && openBtn.dataset.logged === "1";

  const toggleOverlay = (show) => {
    if (!overlay) return;
    overlay.classList.toggle("is-active", show);
    overlay.classList.toggle("show", show);
    overlay.style.display = show ? "block" : "none";
    overlay.setAttribute("aria-hidden", show ? "false" : "true");

    if (show) {
      openBtn && openBtn.setAttribute("aria-expanded", "true");
      const focusTarget = isLogged ? closeBtn : usernameInput;
      setTimeout(() => focusTarget && focusTarget.focus(), 120);
      document.body.style.overflow = "hidden";
    } else {
      openBtn && openBtn.setAttribute("aria-expanded", "false");
      document.body.style.overflow = "";
    }
  };

  if (openBtn) {
    openBtn.addEventListener("click", () => {
      if (event && typeof event.preventDefault === "function") event.preventDefault();
      if (event && typeof event.stopPropagation === "function") event.stopPropagation();
      toggleOverlay(true);
    });
  }
  [closeBtn, backdrop].forEach((el) => {
    el && el.addEventListener("click", () => toggleOverlay(false));
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") {
      toggleOverlay(false);
    }
  });

  // Fallback para cerrar alerts si Bootstrap JS no está inicializado
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
});

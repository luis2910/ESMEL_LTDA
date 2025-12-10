document.addEventListener("DOMContentLoaded", () => {
  const modals = document.querySelectorAll(".servicio-modal");

  modals.forEach((modal) => {
    modal.addEventListener("hidden.bs.modal", () => {
      const carouselEl = modal.querySelector(".carousel");
      if (carouselEl && window.bootstrap?.Carousel) {
        const instance = bootstrap.Carousel.getOrCreateInstance(carouselEl);
        instance.to(0);
      }
    });
  });
});

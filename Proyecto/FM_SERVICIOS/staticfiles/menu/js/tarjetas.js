document.addEventListener("DOMContentLoaded", () => {
  const buttons = document.querySelectorAll(".btn-toggle");

  buttons.forEach(button => {
    button.addEventListener("click", () => {
      const card = button.closest(".card");
      const details = card.querySelector(".service-details");

      card.classList.toggle("expanded");
      if (details) {
        const isVisible = details.style.display === "block";
        details.style.display = isVisible ? "none" : "block";
      }

      if (card.classList.contains("expanded")) {
        button.textContent = "Ver menos";
      } else {
        button.textContent = "Ver más";
      }
    });
  });
});

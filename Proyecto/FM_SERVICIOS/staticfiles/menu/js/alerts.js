document.addEventListener("DOMContentLoaded", function () {
  var alerts = document.querySelectorAll(".flash-auto-close");
  alerts.forEach(function (alert) {
    setTimeout(function () {
      if (alert.classList.contains("show")) {
        var closeBtn = alert.querySelector(".btn-close");
        if (closeBtn) {
          closeBtn.click();
        } else {
          alert.classList.remove("show");
        }
      }
    }, 2500);
  });
});

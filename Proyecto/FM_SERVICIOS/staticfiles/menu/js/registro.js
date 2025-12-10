$(function () {
  const $form = $("#formRegistro");
  const $warnings = $("#warnings");

  // Helpers
  function setError($input, message, $msgDiv) {
    $input.addClass("is-invalid").removeClass("is-valid");
    if ($msgDiv && $msgDiv.length) {
      $msgDiv.text(message);
    } else {
      appendWarning(message);
    }
  }

  function setOk($input, $msgDiv) {
    $input.addClass("is-valid").removeClass("is-invalid");
    if ($msgDiv && $msgDiv.length) $msgDiv.text("");
  }

  function clearAll() {
    $(".invalid-feedback").text("");
    $(".form-control").removeClass("is-invalid is-valid");
    $warnings.text("").hide();
  }

  function appendWarning(msg) {
    const current = $warnings.html();
    const line = `• ${msg}`;
    $warnings.html(current ? current + "<br>" + line : line).show();
  }

  function isValidEmail(email) {
    const re = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/i;
    return re.test(email);
  }

  function passwordStrong(pwd) {
    // Mín 8, con mayúscula, minúscula, número y símbolo
    const re = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^\w\s]).{8,}$/;
    return re.test(pwd);
  }

  function calcAge(isoDate) {
    const today = new Date();
    const dob = new Date(isoDate);
    if (isNaN(dob.getTime())) return -1;
    let age = today.getFullYear() - dob.getFullYear();
    const m = today.getMonth() - dob.getMonth();
    if (m < 0 || (m === 0 && today.getDate() < dob.getDate())) age--;
    return age;
  }

  // Validaciones
  function validateNombre() {
    const $input = $("#primerNombre");
    const $msg = $("#msgNombre");
    const v = ($input.val() || "").toString().trim();

    if (!v) return setError($input, "El nombre es obligatorio.", $msg), false;
    if (v.length < 2) return setError($input, "Debe tener al menos 2 caracteres.", $msg), false;
    if (!/^[A-Za-zÁÉÍÓÚÑáéíóúñ\s'-]+$/.test(v))
      return setError($input, "Solo letras y espacios son permitidos.", $msg), false;

    setOk($input, $msg);
    return true;
  }

  function validateApellido() {
    const $input = $("#apellidoPaterno");
    const $msg = $("#msgApellido");
    const v = ($input.val() || "").toString().trim();

    if (!v) return setError($input, "El apellido es obligatorio.", $msg), false;
    if (v.length < 2) return setError($input, "Debe tener al menos 2 caracteres.", $msg), false;
    if (!/^[A-Za-zÁÉÍÓÚÑáéíóúñ\s'-]+$/.test(v))
      return setError($input, "Solo letras y espacios son permitidos.", $msg), false;

    setOk($input, $msg);
    return true;
  }

  function validateCorreo() {
    const $input = $("#emailRegistro");
    const $msg = $("#msgCorreo");
    const v = ($input.val() || "").toString().trim();

    if (!v) return setError($input, "El correo es obligatorio.", $msg), false;
    if (!isValidEmail(v)) return setError($input, "Ingresa un correo válido (ej: usuario@dominio.com).", $msg), false;

    setOk($input, $msg);
    return true;
  }

  function validateFecha() {
    const $input = $("#fechaNacimiento");
    const $msg = $("#msgFecha");
    const v = ($input.val() || "").toString();

    if (!v) return setError($input, "La fecha de nacimiento es obligatoria.", $msg), false;

    const age = calcAge(v);
    if (age < 0) return setError($input, "Fecha inválida.", $msg), false;
    if (age < 18) return setError($input, "Debes ser mayor de 18 años.", $msg), false;

    setOk($input, $msg);
    return true;
  }

  function validatePassword() {
    const $input = $("#passwordRegistro");
    const $msg = $("#msgPassword");
    const v = ($input.val() || "").toString();

    if (!v) return setError($input, "La contraseña es obligatoria.", $msg), false;
    if (!passwordStrong(v))
      return setError($input, "Mín. 8 caracteres, con mayúscula, minúscula, número y símbolo.", $msg), false;

    setOk($input, $msg);
    return true;
  }

  function validatePassword2() {
    const $input = $("#password2");
    const $msg = $("#msgPassword2");
    const v1 = ($("#passwordRegistro").val() || "").toString();
    const v2 = ($input.val() || "").toString();

    if (!v2) return setError($input, "Confirma tu contraseña.", $msg), false;
    if (v1 !== v2) return setError($input, "Las contraseñas no coinciden.", $msg), false;

    setOk($input, $msg);
    return true;
  }

  // Submit
  $form.on("submit", function (e) {
    clearAll();

    const okNombre = validateNombre();
    const okApellido = validateApellido();
    const okCorreo = validateCorreo();
    const okFecha = validateFecha();
    const okPwd = validatePassword();
    const okPwd2 = validatePassword2();

    const allOk = okNombre && okApellido && okCorreo && okFecha && okPwd && okPwd2;

    if (!allOk) {
      e.preventDefault();
      const $firstInvalid = $(".is-invalid").first();
      if ($firstInvalid.length) $firstInvalid.focus();
    }
  });

  // Validación en vivo
  $("#primerNombre").on("input blur", validateNombre);
  $("#apellidoPaterno").on("input blur", validateApellido);
  $("#emailRegistro").on("input blur", validateCorreo);
  $("#fechaNacimiento").on("change blur", validateFecha);
  $("#passwordRegistro").on("input blur", function () {
    validatePassword();
    if ($("#password2").val()) validatePassword2();
  });
  $("#password2").on("input blur", validatePassword2);
});

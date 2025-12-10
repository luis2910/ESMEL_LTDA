from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError
from django.db.models import Q
import re

from .models import User, Cotizacion, ContactoWeb, Documento, Servicio, Region, Comuna

CHILE_REGIONES = [
    ("Arica y Parinacota", ["Arica", "Camarones", "Putre", "General Lagos"]),
    ("Tarapaca", ["Iquique", "Alto Hospicio", "Pozo Almonte", "Camina", "Huara"]),
    ("Antofagasta", ["Antofagasta", "Mejillones", "Tocopilla", "Calama"]),
    ("Atacama", ["Copiapo", "Caldera", "Vallenar", "Chanaral"]),
    ("Coquimbo", ["La Serena", "Coquimbo", "Ovalle", "Illapel"]),
    ("Valparaiso", ["Valparaiso", "Vina del Mar", "Quilpue", "Los Andes", "San Antonio"]),
    ("Metropolitana", ["Santiago", "Providencia", "Las Condes", "Maipu", "Puente Alto", "La Florida"]),
    ("O'Higgins", ["Rancagua", "Machali", "San Fernando", "Pichilemu"]),
    ("Maule", ["Talca", "Curico", "Linares", "Cauquenes"]),
    ("Nuble", ["Chillan", "San Carlos", "Bulnes", "Quirihue"]),
    ("Biobio", ["Concepcion", "Talcahuano", "Los Angeles", "Coronel"]),
    ("Araucania", ["Temuco", "Padre Las Casas", "Villarrica", "Angol"]),
    ("Los Rios", ["Valdivia", "La Union", "Rio Bueno", "Panguipulli"]),
    ("Los Lagos", ["Puerto Montt", "Puerto Varas", "Osorno", "Castro"]),
    ("Aysen", ["Coyhaique", "Aysen", "Cochrane", "Chile Chico"]),
    ("Magallanes", ["Punta Arenas", "Puerto Natales", "Porvenir", "Cabo de Hornos"]),
]
CHILE_REGIONES_DICT = {nombre: comunas for nombre, comunas in CHILE_REGIONES}

SECURITY_QUESTION_CHOICES = [
    ("Como se llama tu mama?", "Como se llama tu mama?"),
    ("Cual fue tu primera mascota?", "Cual fue tu primera mascota?"),
    ("En que ciudad naciste?", "En que ciudad naciste?"),
    ("Cual es tu comida favorita?", "Cual es tu comida favorita?"),
    ("Como se llama tu mejor amigo de la infancia?", "Como se llama tu mejor amigo de la infancia?"),
]


def _normalize_rut(raw: str) -> str:
    """
    Normaliza el RUT a formato ########-D (8 numeros + digito verificador), validando DV.
    """
    clean = re.sub(r"[^0-9kK]", "", (raw or ""))
    if len(clean) != 9:
        raise ValidationError("RUT invalido (formato: 8 numeros mas digito verificador).")
    cuerpo, dv = clean[:-1], clean[-1].upper()
    if not cuerpo.isdigit():
        raise ValidationError("RUT invalido (solo numeros en el cuerpo).")
    if len(cuerpo) != 8:
        raise ValidationError("RUT invalido (debe tener 8 numeros en el cuerpo).")
    if not (dv.isdigit() or dv == "K"):
        raise ValidationError("RUT invalido (digito verificador incorrecto).")
    reversed_digits = map(int, reversed(cuerpo))
    factors = [2, 3, 4, 5, 6, 7]
    s = 0
    for i, d in enumerate(reversed_digits):
        s += d * factors[i % len(factors)]
    mod = 11 - (s % 11)
    dv_calc = "0" if mod == 11 else "K" if mod == 10 else str(mod)
    if dv != dv_calc:
        raise ValidationError("RUT invalido.")
    return f"{cuerpo}-{dv}"

def _normalize_phone(raw: str) -> str:
    """
    Normaliza telefono de manera simple: si no cumple patron basico, levanta error.
    """
    tel = (raw or "").strip()
    pattern = re.compile(r"^\+?\d[\d\s-]{7,}$")
    if not tel or not pattern.match(tel):
        raise ValidationError("Ingresa un telefono valido (ej: +56 9 1234 5678).")
    return tel


class RegistroForm(UserCreationForm):
    error_messages = {
        "password_mismatch": "Las contrasenas no coinciden. Asegurate de repetirla correctamente.",
    }
    rut = forms.CharField(label="RUT")
    first_name = forms.CharField(label="Primer Nombre", max_length=150)
    last_name = forms.CharField(label="Apellido Paterno", max_length=150)
    email = forms.EmailField(label="Correo electronico")
    telefono = forms.CharField(label="Telefono", max_length=25, required=False)
    fecha_nacimiento = forms.DateField(
        label="Fecha de nacimiento", required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    acepta_privacidad = forms.BooleanField(label="Acepto la politica de privacidad", required=True)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = (
            "username",
            "rut",
            "first_name",
            "last_name",
            "email",
            "telefono",
            "fecha_nacimiento",
            "acepta_privacidad",
        )

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if not email:
            return email
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("Este correo electronico ya esta registrado.")
        return email

    def clean_username(self):
        username = (self.cleaned_data.get("username") or "").strip()
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if not username:
            base = email.split("@")[0] if email else "persona"
            base = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-") or "persona"
            candidate = base
            counter = 1
            while User.objects.filter(username__iexact=candidate).exists():
                candidate = f"{base}-{counter}"
                counter += 1
            return candidate
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError("Este usuario ya esta registrado.")
        return username

    def clean_rut(self):
        raw = (self.cleaned_data.get("rut") or "").strip()
        if not raw:
            return raw
        rut_normalizado = _normalize_rut(raw)
        if User.objects.filter(rut__iexact=rut_normalizado).exists():
            raise ValidationError("Este RUT ya esta registrado.")
        return rut_normalizado

    def clean_telefono(self):
        raw = (self.cleaned_data.get("telefono") or "").strip()
        if not raw:
            return raw
        return _normalize_phone(raw)

    def clean(self):
        cleaned = super().clean()
        required = {
            "rut": "Ingresa tu RUT.",
            "first_name": "Ingresa tu nombre.",
            "last_name": "Ingresa tu apellido.",
            "email": "Ingresa tu correo electronico.",
        }
        for field, message in required.items():
            val = cleaned.get(field)
            if not (val or "").strip():
                self.add_error(field, message)

        return cleaned

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.update({"class": "form-check-input"})
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs.update({"class": "form-select"})
            else:
                field.widget.attrs.update({"class": "form-control"})
            if field.required:
                field.error_messages.setdefault("required", "Este campo es obligatorio.")
            if isinstance(field, forms.EmailField):
                field.error_messages.setdefault("invalid", "Ingresa un correo electronico valido.")
        # Placeholders
        self.fields["username"].label = "Usuario"
        self.fields["username"].widget.attrs.setdefault("placeholder", "usuario")
        self.fields["username"].widget.attrs.setdefault("autocomplete", "username")
        self.fields["rut"].widget.attrs.update(
            {"class": "form-control", "placeholder": "12345678-9", "pattern": "\\d{8}[0-9kK]", "maxlength": "10"}
        )
        self.fields["first_name"].widget.attrs.setdefault("placeholder", "Juan")
        self.fields["last_name"].widget.attrs.setdefault("placeholder", "Perez")
        self.fields["email"].widget.attrs.setdefault("placeholder", "usuario@correo.com")
        self.fields["telefono"].widget.attrs.setdefault("placeholder", "+56 9 1234 5678")
        # username se autogenera, no se exige en el formulario
        if "username" in self.fields:
            self.fields["username"].required = False
        self.fields["username"].error_messages.setdefault("unique", "Este usuario ya esta registrado.")
        if "rut" in self.fields:
            self.fields["rut"].error_messages.setdefault("unique", "Este RUT ya esta registrado.")

    def clean_password2(self):
        password1 = self.cleaned_data.get("password1")
        password2 = self.cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            raise ValidationError(self.error_messages["password_mismatch"], code="password_mismatch")
        if password2:
            password_validation.validate_password(password2, self.instance)
        return password2


class LoginForm(AuthenticationForm):
    username = forms.CharField(label="Usuario o correo")

    def clean(self):
        data = self.data.copy()
        raw_username = data.get("username")
        if raw_username:
            U = get_user_model()
            ident = raw_username.strip()
            user = (
                U.objects.filter(Q(email__iexact=ident) | Q(username__iexact=ident))
                .order_by("date_joined", "id")
                .first()
            )
            if user:
                data["username"] = user.username
                self.data = data
        return super().clean()


class Login2FACodeForm(forms.Form):
    code = forms.RegexField(
        label="Codigo",
        regex=r"^\d{4}(\d{2})?$",
        max_length=6,
        min_length=4,
        error_messages={"invalid": "Ingresa un codigo de 4 o 6 digitos."},
        widget=forms.TextInput(
            attrs={
                "type": "tel",
                "inputmode": "numeric",
                "pattern": "[0-9]*",
                "maxlength": "6",
                "autocomplete": "one-time-code",
                "placeholder": "000000",
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["code"].widget.attrs.update({"class": "form-control"})


class CotizacionForm(forms.ModelForm):
    class Meta:
        model = Cotizacion
        fields = ("servicio", "edificio", "asunto", "mensaje")
        widgets = {"mensaje": forms.Textarea(attrs={"rows": 5})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs.update({"class": "form-select"})
            elif isinstance(field.widget, forms.Textarea):
                field.widget.attrs.update({"class": "form-control"})
            else:
                field.widget.attrs.update({"class": "form-control"})


class ContactoForm(forms.ModelForm):
    region = forms.ChoiceField(choices=[("", "Selecciona region")] + [(r, r) for r, _ in CHILE_REGIONES], required=False)
    comuna = forms.ChoiceField(choices=[("", "Selecciona comuna")], required=False)

    class Meta:
        model = ContactoWeb
        fields = (
            "nombre",
            "apellido",
            "email",
            "telefono",
            "asunto",
            "tipo_servicio",
            "lugar_servicio",
            "region",
            "comuna",
            "mensaje",
            "boletin",
            "acepta_privacidad",
        )
        widgets = {"mensaje": forms.Textarea(attrs={"rows": 5})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.update({"class": "form-check-input"})
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs.update({"class": "form-select"})
            elif isinstance(field.widget, forms.Textarea):
                field.widget.attrs.update({"class": "form-control"})
            else:
                field.widget.attrs.update({"class": "form-control"})
        services = Servicio.objects.filter(publicado=True).order_by("orden", "titulo")
        service_choices = [("", "Selecciona un servicio")] + [(s.titulo, s.titulo) for s in services]
        self.fields["tipo_servicio"].widget = forms.Select(choices=service_choices)
        self.fields["tipo_servicio"].widget.attrs.update({"class": "form-select"})

        region_field = self.fields["region"]
        try:
            regiones_db = list(Region.objects.all().order_by("nombre"))
        except Exception:
            regiones_db = []
        if regiones_db:
            region_choices = [("", "Selecciona region")] + [(r.nombre, r.nombre) for r in regiones_db]
        else:
            region_choices = [("", "Selecciona region")] + [(r, r) for r, _ in CHILE_REGIONES]
        region_field.choices = region_choices
        region_field.widget = forms.Select(choices=region_choices)
        region_field.widget.attrs.update({"class": "form-select"})

        comuna_field = self.fields["comuna"]
        selected_region = self.data.get("region") or self.initial.get("region")
        comunas = []
        if selected_region and regiones_db:
            try:
                region_obj = next((r for r in regiones_db if r.nombre == selected_region), None)
                if region_obj:
                    comunas = list(Comuna.objects.filter(region=region_obj).order_by("nombre").values_list("nombre", flat=True))
            except Exception:
                comunas = []
        if not comunas:
            comunas = CHILE_REGIONES_DICT.get(selected_region, [])
        comuna_choices = [("", "Selecciona comuna")] + [(c, c) for c in comunas]
        comuna_field.choices = comuna_choices
        comuna_field.widget = forms.Select(choices=comuna_choices)
        comuna_field.widget.attrs.update(
            {"class": "form-select", "data-initial": self.data.get("comuna") or self.initial.get("comuna") or ""}
        )

        self.fields["lugar_servicio"].widget.attrs.setdefault("placeholder", "Ej: Direccion o referencia del lugar")
        required_fields = [
            "nombre",
            "email",
            "asunto",
            "tipo_servicio",
            "lugar_servicio",
            "region",
            "comuna",
            "mensaje",
            "acepta_privacidad",
        ]
        for fname in required_fields:
            field = self.fields.get(fname)
            if field:
                field.required = True
                field.error_messages.setdefault("required", "Este campo es obligatorio.")

    def clean_telefono(self):
        raw = (self.cleaned_data.get("telefono") or "").strip()
        if not raw:
            return raw
        return _normalize_phone(raw)


class DocumentoForm(forms.ModelForm):
    class Meta:
        model = Documento
        fields = ("titulo", "categoria", "tags", "archivo")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["titulo"].widget.attrs.update({"class": "form-control", "placeholder": "Titulo del documento"})
        self.fields["categoria"].widget.attrs.update({"class": "form-select"})
        self.fields["tags"].widget.attrs.update(
            {
                "class": "form-control",
                "placeholder": "Ej: facturacion, contrato, identidad",
                "data-role": "tags",
            }
        )
        self.fields["archivo"].widget.attrs.update({"class": "form-control", "accept": ".pdf,application/pdf"})


class DocumentoEditForm(forms.ModelForm):
    class Meta:
        model = Documento
        fields = ("titulo", "descripcion", "categoria", "tags")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["titulo"].widget.attrs.update({"class": "form-control", "placeholder": "Titulo"})
        self.fields["descripcion"].widget.attrs.update({"class": "form-control", "rows": 4})
        if "categoria" in self.fields:
            self.fields["categoria"].widget.attrs.update({"class": "form-select"})
        if "tags" in self.fields:
            self.fields["tags"].widget.attrs.update(
                {"class": "form-control", "placeholder": "Ej: facturacion, contrato, identidad"}
            )


class ServicioForm(forms.ModelForm):
    class Meta:
        model = Servicio
        fields = ("titulo", "resumen", "contenido_md", "publicado")
        widgets = {"resumen": forms.Textarea(attrs={"rows": 3}), "contenido_md": forms.Textarea(attrs={"rows": 8})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.update({"class": "form-check-input"})
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs.update({"class": "form-select"})
            else:
                field.widget.attrs.update({"class": "form-control"})


class PasswordCodeRequestForm(forms.Form):
    email = forms.EmailField(label="Correo electronico")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs.update({"class": "form-select"})
            else:
                field.widget.attrs.update({"class": "form-control"})
        self.user = None

    def clean(self):
        cleaned = super().clean()
        email = cleaned.get("email")
        if not email:
            return cleaned
        U = get_user_model()
        try:
            self.user = U.objects.get(email__iexact=email)
        except U.DoesNotExist:
            self.user = None
        except U.MultipleObjectsReturned:
            self.user = (
                U.objects.filter(email__iexact=email, is_active=True).order_by("date_joined", "id").first()
            )
        return cleaned


class PasswordCodeVerifyForm(forms.Form):
    code = forms.CharField(label="Codigo", max_length=12)
    new_password1 = forms.CharField(label="Nueva contrasena", widget=forms.PasswordInput)
    new_password2 = forms.CharField(label="Confirmar contrasena", widget=forms.PasswordInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs.update({"class": "form-control"})

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("new_password1")
        p2 = cleaned.get("new_password2")
        if p1 and p2 and p1 != p2:
            raise ValidationError("Las contrasenas no coinciden.")
        return cleaned


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "email", "telefono", "fecha_nacimiento")
        widgets = {"fecha_nacimiento": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.update({"class": "form-check-input"})
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs.update({"class": "form-select"})
            else:
                field.widget.attrs.update({"class": "form-control"})
        self.fields["fecha_nacimiento"].widget.attrs.setdefault("placeholder", "dd/mm/aaaa")
        self.fields["telefono"].widget.attrs.setdefault("placeholder", "+56999999999")

    def clean_telefono(self):
        raw = (self.cleaned_data.get("telefono") or "").strip()
        if not raw:
            return raw
        return _normalize_phone(raw)


class CompanyForm(forms.ModelForm):
    class Meta:
        model = User
        fields = (
            "empresa_nombre",
            "empresa_rut",
            "empresa_encargado",
            "empresa_encargado_rut",
            "empresa_ubicacion",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs.update({"class": "form-control"})
            if not field.required:
                field.widget.attrs.setdefault("placeholder", "")


class PasswordByQuestionForm(forms.Form):
    new_password1 = forms.CharField(label="Nueva contrasena", widget=forms.PasswordInput)
    new_password2 = forms.CharField(label="Confirmar contrasena", widget=forms.PasswordInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs.update({"class": "form-control"})

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("new_password1")
        p2 = cleaned.get("new_password2")
        if p1 and p2 and p1 != p2:
            raise ValidationError("Las contrasenas no coinciden.")
        return cleaned

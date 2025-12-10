from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("FM", "0002_seed_servicios_basicos"),
    ]

    operations = [
        migrations.CreateModel(
            name="Tecnico",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("creado_en", models.DateTimeField(auto_now_add=True)),
                ("actualizado_en", models.DateTimeField(auto_now=True)),
                ("slug", models.SlugField(blank=True, max_length=90, null=True, unique=True)),
                ("nombre", models.CharField(max_length=120)),
                ("apellido", models.CharField(blank=True, max_length=120, null=True)),
                ("correo", models.EmailField(max_length=254, unique=True)),
                ("rut", models.CharField(max_length=20, unique=True)),
                ("telefono", models.CharField(blank=True, max_length=25, null=True)),
                ("especialidad", models.CharField(blank=True, max_length=150, null=True)),
                ("activo", models.BooleanField(default=True)),
                (
                    "servicio",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="tecnicos",
                        to="FM.servicio",
                    ),
                ),
            ],
            options={
                "ordering": ["nombre", "apellido", "id"],
            },
        ),
        migrations.AddIndex(
            model_name="tecnico",
            index=models.Index(fields=["slug"], name="FM_tecnico_slug_idx"),
        ),
        migrations.AddIndex(
            model_name="tecnico",
            index=models.Index(fields=["correo"], name="FM_tecnico_correo_idx"),
        ),
        migrations.AddIndex(
            model_name="tecnico",
            index=models.Index(fields=["rut"], name="FM_tecnico_rut_idx"),
        ),
    ]

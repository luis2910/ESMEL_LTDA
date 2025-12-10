from django.db import migrations, models
import django.db.models.deletion


REGIONES_COMUNAS = [
    ("Arica y Parinacota", ["Arica", "Camarones", "Putre", "General Lagos"]),
    ("Tarapaca", ["Iquique", "Alto Hospicio", "Pozo Almonte", "Camina", "Huara", "Pica", "Colchane"]),
    ("Antofagasta", ["Antofagasta", "Mejillones", "Sierra Gorda", "Taltal", "Calama", "Ollague", "San Pedro de Atacama", "Tocopilla", "Maria Elena"]),
    ("Atacama", ["Copiapo", "Caldera", "Tierra Amarilla", "Chanaral", "Diego de Almagro", "Vallenar", "Alto del Carmen", "Freirina", "Huasco"]),
    ("Coquimbo", ["La Serena", "Coquimbo", "Andacollo", "La Higuera", "Paiguano", "Vicuna", "Illapel", "Canela", "Los Vilos", "Salamanca", "Ovalle", "Combarbala", "Monte Patria", "Punitaqui", "Rio Hurtado"]),
    ("Valparaiso", ["Valparaiso", "Vina del Mar", "Concon", "Quilpue", "Villa Alemana", "Casablanca", "Quintero", "Puchuncavi", "Quillota", "La Calera", "Hijuelas", "La Cruz", "Nogales", "San Antonio", "Cartagena", "El Tabo", "El Quisco", "Algarrobo", "Santo Domingo", "San Felipe", "Catemu", "Llaillay", "Panquehue", "Putaendo", "Santa Maria", "Los Andes", "Calle Larga", "Rinconada", "San Esteban", "Isla de Pascua", "Juan Fernandez", "Petorca", "La Ligua", "Cabildo", "Papudo", "Zapallar"]),
    ("Metropolitana", ["Santiago", "Cerrillos", "Cerro Navia", "Conchali", "El Bosque", "Estacion Central", "Huechuraba", "Independencia", "La Cisterna", "La Florida", "La Granja", "La Pintana", "La Reina", "Las Condes", "Lo Barnechea", "Lo Espejo", "Lo Prado", "Macul", "Maipu", "Nunoa", "Pedro Aguirre Cerda", "Penalolen", "Providencia", "Pudahuel", "Quilicura", "Quinta Normal", "Recoleta", "Renca", "San Joaquin", "San Miguel", "San Ramon", "Vitacura", "Puente Alto", "Pirque", "San Jose de Maipo", "Colina", "Lampa", "Til Til", "San Bernardo", "Buin", "Calera de Tango", "Paine", "Melipilla", "Alhue", "Curacavi", "Maria Pinto", "San Pedro", "Talagante", "El Monte", "Isla de Maipo", "Padre Hurtado", "Penaflor"]),
    ("O'Higgins", ["Rancagua", "Codegua", "Coinco", "Coltauco", "Donihue", "Graneros", "Las Cabras", "Machali", "Malloa", "Mostazal", "Olivar", "Peumo", "Pichidegua", "Quinta de Tilcoco", "Rengo", "Requinoa", "San Vicente", "Pichilemu", "La Estrella", "Litueche", "Marchigue", "Navidad", "Paredones", "San Fernando", "Chepica", "Chimbarongo", "Lolol", "Nancagua", "Palmilla", "Peralillo", "Placilla", "Pumanque", "Santa Cruz"]),
    ("Maule", ["Talca", "Constitucion", "Curepto", "Empedrado", "Maule", "Pelarco", "Pencahue", "Rio Claro", "San Clemente", "San Rafael", "Cauquenes", "Chanco", "Pelluhue", "Curico", "Hualane", "Licanten", "Molina", "Rauco", "Romeral", "Sagrada Familia", "Teno", "Vichuquen", "Linares", "Colbun", "Longavi", "Parral", "Retiro", "San Javier", "Villa Alegre", "Yerbas Buenas"]),
    ("Nuble", ["Chillan", "Chillan Viejo", "Coihueco", "Niquen", "San Carlos", "San Fabian", "San Nicolas", "Bulnes", "Quillon", "San Ignacio", "El Carmen", "Pemuco", "Pinto", "Yungay", "Cobquecura", "Coelemu", "Ninhue", "Portezuelo", "Quirihue", "Ranquil", "Trehuaco"]),
    ("Biobio", ["Concepcion", "Coronel", "Chiguayante", "Florida", "Hualpen", "Hualqui", "Lota", "Penco", "San Pedro de la Paz", "Santa Juana", "Talcahuano", "Tome", "Arauco", "Canete", "Contulmo", "Curanilahue", "Lebu", "Los Alamos", "Tirua", "Los Angeles", "Antuco", "Cabrero", "Laja", "Mulchen", "Nacimiento", "Negrete", "Quilaco", "Quilleco", "San Rosendo", "Santa Barbara", "Tucapel", "Yumbel", "Alto Biobio"]),
    ("Araucania", ["Temuco", "Carahue", "Cholchol", "Cunco", "Curarrehue", "Freire", "Galvarino", "Gorbea", "Lautaro", "Loncoche", "Melipeuco", "Nueva Imperial", "Padre Las Casas", "Perquenco", "Pitrufquen", "Pucon", "Saavedra", "Teodoro Schmidt", "Tolten", "Vilcun", "Villarrica", "Angol", "Collipulli", "Curacautin", "Ercilla", "Lonquimay", "Los Sauces", "Lumaco", "Puren", "Renaico", "Traiguen", "Victoria"]),
    ("Los Rios", ["Valdivia", "Corral", "Lanco", "Los Lagos", "Mafil", "Mariquina", "Paillaco", "Panguipulli", "La Union", "Futrono", "Lago Ranco", "Rio Bueno"]),
    ("Los Lagos", ["Puerto Montt", "Calbuco", "Cochamo", "Fresia", "Frutillar", "Llanquihue", "Los Muermos", "Maullin", "Puerto Varas", "Osorno", "Puerto Octay", "Purranque", "Puyehue", "Rio Negro", "San Juan de la Costa", "San Pablo", "Ancud", "Castro", "Chonchi", "Curaco de Velez", "Dalcahue", "Puqueldon", "Queilen", "Quellon", "Quemchi", "Quinchao", "Chaiten", "Futaleufu", "Hualaihue", "Palena"]),
    ("Aysen", ["Coyhaique", "Lago Verde", "Aysen", "Cisnes", "Guaitecas", "Cochrane", "OHiggins", "Tortel", "Chile Chico", "Rio Ibanez"]),
    ("Magallanes", ["Punta Arenas", "Laguna Blanca", "Rio Verde", "San Gregorio", "Cabo de Hornos", "Antartica", "Porvenir", "Primavera", "Timaukel", "Puerto Natales", "Torres del Paine"]),
]


def seed_regiones_comunas(apps, schema_editor):
    Region = apps.get_model("FM", "Region")
    Comuna = apps.get_model("FM", "Comuna")
    for nombre_region, comunas in REGIONES_COMUNAS:
        region, _ = Region.objects.get_or_create(nombre=nombre_region)
        for c in comunas:
            Comuna.objects.get_or_create(region=region, nombre=c)


class Migration(migrations.Migration):

    dependencies = [
        ("FM", "0004_rename_fm_tecnico_slug_idx_fm_tecnico_slug_a053ed_idx_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="Region",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("creado_en", models.DateTimeField(auto_now_add=True)),
                ("actualizado_en", models.DateTimeField(auto_now=True)),
                ("nombre", models.CharField(max_length=120, unique=True)),
            ],
            options={
                "ordering": ["nombre"],
            },
        ),
        migrations.CreateModel(
            name="Comuna",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("creado_en", models.DateTimeField(auto_now_add=True)),
                ("actualizado_en", models.DateTimeField(auto_now=True)),
                ("nombre", models.CharField(max_length=120)),
                (
                    "region",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="comunas", to="FM.region"),
                ),
            ],
            options={
                "ordering": ["region__nombre", "nombre"],
                "unique_together": {("region", "nombre")},
            },
        ),
        migrations.AddIndex(
            model_name="comuna",
            index=models.Index(fields=["region", "nombre"], name="FM_comuna_region__nombre_idx"),
        ),
        migrations.AddIndex(
            model_name="region",
            index=models.Index(fields=["nombre"], name="FM_region_nombre_idx"),
        ),
        migrations.RunPython(seed_regiones_comunas, migrations.RunPython.noop),
    ]

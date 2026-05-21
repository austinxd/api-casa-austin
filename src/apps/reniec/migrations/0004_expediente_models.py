# Migration generada manualmente para los 7 modelos del expediente extendido.
# Tablas nuevas con FK al campo `dni` (unique) de DNICache.
# DNICache queda INTACTA — no se modifica.

import django.db.models.deletion
import django.utils.timezone
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reniec', '0003_ratelimitconfig'),
    ]

    operations = [
        # ─── PersonPhone ──────────────────────────────────────────────────
        migrations.CreateModel(
            name='PersonPhone',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created', models.DateTimeField(auto_now_add=True, help_text='When the instance was created.', verbose_name='created at')),
                ('updated', models.DateTimeField(auto_now=True, help_text='The last time at the instance was modified.', verbose_name='updated at')),
                ('deleted', models.BooleanField(default=False, help_text='It can be set to false, usefull to simulate deletion')),
                ('phone', models.CharField(db_index=True, help_text='Número normalizado (últimos 9 dígitos Perú)', max_length=15)),
                ('operator', models.CharField(blank=True, help_text='MOVISTAR / ENTEL / CLARO / BITEL / etc.', max_length=30)),
                ('plan', models.CharField(blank=True, max_length=100)),
                ('period', models.DateField(blank=True, help_text='Periodo de la titularidad (parseado de Leder)', null=True)),
                ('source', models.CharField(blank=True, help_text='Fuente original tal cual vino (MOVISTAR / CLARO POSTPAGO / etc.)', max_length=50)),
                ('dni', models.ForeignKey(db_column='dni', help_text='DNI titular del teléfono (según Leder)', on_delete=django.db.models.deletion.CASCADE, related_name='phones', to='reniec.dnicache', to_field='dni')),
            ],
            options={
                'verbose_name': '📱 Titularidad teléfono',
                'verbose_name_plural': '📱 Titularidades teléfono',
                'unique_together': {('phone', 'operator', 'dni')},
            },
        ),
        migrations.AddIndex(
            model_name='personphone',
            index=models.Index(fields=['phone'], name='reniec_pers_phone_idx1'),
        ),
        migrations.AddIndex(
            model_name='personphone',
            index=models.Index(fields=['dni', '-period'], name='reniec_pers_phone_idx2'),
        ),

        # ─── PersonFamilyRelation ─────────────────────────────────────────
        migrations.CreateModel(
            name='PersonFamilyRelation',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created', models.DateTimeField(auto_now_add=True, help_text='When the instance was created.', verbose_name='created at')),
                ('updated', models.DateTimeField(auto_now=True, help_text='The last time at the instance was modified.', verbose_name='updated at')),
                ('deleted', models.BooleanField(default=False, help_text='It can be set to false, usefull to simulate deletion')),
                ('relation_type', models.CharField(db_index=True, help_text='PADRE / MADRE / HERMANO / TIO_PATERNO / COHABITANTE / etc.', max_length=40)),
                ('verification', models.CharField(blank=True, choices=[('ALTA', 'Alta'), ('MEDIA', 'Media'), ('BAJA', 'Baja'), ('', 'Desconocida')], help_text='Solo para arbol_genealogico — confianza de la relación según Leder', max_length=15)),
                ('source', models.CharField(choices=[('arbol_genealogico', 'Árbol Genealógico'), ('familia_1', 'Familia-1 (Censo)')], help_text='De qué endpoint Leder vino esta relación', max_length=20)),
                ('cached_name', models.CharField(blank=True, max_length=200)),
                ('cached_gender', models.CharField(blank=True, max_length=15)),
                ('cached_age_at_query', models.IntegerField(blank=True, null=True)),
                ('cached_birthday', models.DateField(blank=True, null=True)),
                ('dni', models.ForeignKey(db_column='dni', help_text="Persona consultada (el 'titular' del expediente)", on_delete=django.db.models.deletion.CASCADE, related_name='family_relations', to='reniec.dnicache', to_field='dni')),
                ('relative_dni', models.ForeignKey(db_column='relative_dni', help_text='Familiar relacionado (en DNICache, lazy-creado)', on_delete=django.db.models.deletion.CASCADE, related_name='inverse_family_relations', to='reniec.dnicache', to_field='dni')),
            ],
            options={
                'verbose_name': '👥 Relación familiar',
                'verbose_name_plural': '👥 Relaciones familiares',
                'unique_together': {('dni', 'relative_dni', 'source')},
            },
        ),
        migrations.AddIndex(
            model_name='personfamilyrelation',
            index=models.Index(fields=['dni', 'relation_type'], name='reniec_fam_rel_idx1'),
        ),
        migrations.AddIndex(
            model_name='personfamilyrelation',
            index=models.Index(fields=['relative_dni'], name='reniec_fam_rel_idx2'),
        ),

        # ─── PersonSalaryRecord ───────────────────────────────────────────
        migrations.CreateModel(
            name='PersonSalaryRecord',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created', models.DateTimeField(auto_now_add=True, help_text='When the instance was created.', verbose_name='created at')),
                ('updated', models.DateTimeField(auto_now=True, help_text='The last time at the instance was modified.', verbose_name='updated at')),
                ('deleted', models.BooleanField(default=False, help_text='It can be set to false, usefull to simulate deletion')),
                ('ruc', models.CharField(db_index=True, max_length=11)),
                ('company_name', models.CharField(blank=True, max_length=255)),
                ('situation', models.CharField(blank=True, help_text='Estado de la relación laboral según Leder (A/B/...)', max_length=2)),
                ('salary_pen', models.DecimalField(blank=True, decimal_places=2, help_text='Monto declarado en Soles', max_digits=12, null=True)),
                ('period', models.DateField(help_text='Periodo declarado (parseado de YYYYMM o equivalente)')),
                ('dni', models.ForeignKey(db_column='dni', on_delete=django.db.models.deletion.CASCADE, related_name='salaries', to='reniec.dnicache', to_field='dni')),
            ],
            options={
                'verbose_name': '💼 Sueldo declarado',
                'verbose_name_plural': '💼 Sueldos declarados',
                'unique_together': {('dni', 'ruc', 'period')},
            },
        ),
        migrations.AddIndex(
            model_name='personsalaryrecord',
            index=models.Index(fields=['dni', '-period'], name='reniec_salary_idx1'),
        ),
        migrations.AddIndex(
            model_name='personsalaryrecord',
            index=models.Index(fields=['ruc'], name='reniec_salary_idx2'),
        ),

        # ─── PersonMarriage ───────────────────────────────────────────────
        migrations.CreateModel(
            name='PersonMarriage',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created', models.DateTimeField(auto_now_add=True, help_text='When the instance was created.', verbose_name='created at')),
                ('updated', models.DateTimeField(auto_now=True, help_text='The last time at the instance was modified.', verbose_name='updated at')),
                ('deleted', models.BooleanField(default=False, help_text='It can be set to false, usefull to simulate deletion')),
                ('spouse_name', models.CharField(blank=True, help_text='Nombre del cónyuge (fallback si no hay DNI matcheable)', max_length=200)),
                ('marriage_date', models.DateField(blank=True, null=True)),
                ('divorce_date', models.DateField(blank=True, null=True)),
                ('location', models.CharField(blank=True, max_length=200)),
                ('source_raw', models.JSONField(blank=True, default=dict, help_text='JSON crudo de Leder para no perder info')),
                ('dni', models.ForeignKey(db_column='dni', on_delete=django.db.models.deletion.CASCADE, related_name='marriages', to='reniec.dnicache', to_field='dni')),
                ('spouse_dni', models.ForeignKey(blank=True, db_column='spouse_dni', help_text='DNI del cónyuge (lazy-creado en DNICache)', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='inverse_marriages', to='reniec.dnicache', to_field='dni')),
            ],
            options={
                'verbose_name': '💍 Matrimonio',
                'verbose_name_plural': '💍 Matrimonios',
            },
        ),

        # ─── PersonAddress ────────────────────────────────────────────────
        migrations.CreateModel(
            name='PersonAddress',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created', models.DateTimeField(auto_now_add=True, help_text='When the instance was created.', verbose_name='created at')),
                ('updated', models.DateTimeField(auto_now=True, help_text='The last time at the instance was modified.', verbose_name='updated at')),
                ('deleted', models.BooleanField(default=False, help_text='It can be set to false, usefull to simulate deletion')),
                ('address_raw', models.CharField(max_length=500)),
                ('address_norm', models.CharField(db_index=True, help_text='Normalizada para dedupe (uppercase, sin abreviaciones)', max_length=500)),
                ('ubicacion', models.CharField(blank=True, help_text='LIMA - LIMA - SAN LUIS / etc.', max_length=200)),
                ('source', models.CharField(blank=True, help_text='RENIEC 2023 / SUNAT / INMUEBLES / FUENTE INTERNA', max_length=50)),
                ('source_year', models.IntegerField(blank=True, help_text='Año extraído de la fuente (ej. RENIEC 2023 → 2023)', null=True)),
                ('first_seen', models.DateField(default=django.utils.timezone.now, help_text='Cuándo apareció esta dirección por primera vez en nuestras consultas')),
                ('last_seen', models.DateField(default=django.utils.timezone.now, help_text='Última vez que Leder devolvió esta dirección')),
                ('is_current_best', models.BooleanField(db_index=True, default=False, help_text='1 sola dirección por persona — la más probable de ser la actual')),
                ('dni', models.ForeignKey(db_column='dni', on_delete=django.db.models.deletion.CASCADE, related_name='addresses', to='reniec.dnicache', to_field='dni')),
            ],
            options={
                'verbose_name': '🏠 Dirección registrada',
                'verbose_name_plural': '🏠 Direcciones registradas',
                'unique_together': {('dni', 'address_norm')},
            },
        ),
        migrations.AddIndex(
            model_name='personaddress',
            index=models.Index(fields=['dni', '-last_seen'], name='reniec_addr_idx1'),
        ),
        migrations.AddIndex(
            model_name='personaddress',
            index=models.Index(fields=['dni', 'is_current_best'], name='reniec_addr_idx2'),
        ),

        # ─── PersonPoliceRecord ───────────────────────────────────────────
        migrations.CreateModel(
            name='PersonPoliceRecord',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created', models.DateTimeField(auto_now_add=True, help_text='When the instance was created.', verbose_name='created at')),
                ('updated', models.DateTimeField(auto_now=True, help_text='The last time at the instance was modified.', verbose_name='updated at')),
                ('deleted', models.BooleanField(default=False, help_text='It can be set to false, usefull to simulate deletion')),
                ('nro_denuncia', models.CharField(db_index=True, max_length=30)),
                ('clave', models.CharField(blank=True, max_length=30)),
                ('codigo_ruva', models.CharField(blank=True, max_length=30)),
                ('region_policial', models.CharField(blank=True, max_length=100)),
                ('comisaria', models.CharField(blank=True, max_length=100)),
                ('denuncia_type', models.CharField(blank=True, help_text='DENUNCIA / OFICIO / ATESTADO según Leder', max_length=30)),
                ('formalidad', models.CharField(blank=True, help_text='VERBAL / ESCRITA', max_length=30)),
                ('condicion', models.CharField(blank=True, max_length=200)),
                ('category', models.CharField(choices=[
                    ('ROBO', 'Robo'),
                    ('VIOLENCIA', 'Violencia'),
                    ('PERDIDA', 'Perdida'),
                    ('ACCIDENTE', 'Accidente'),
                    ('FRAUDE', 'Fraude'),
                    ('AMENAZAS', 'Amenazas'),
                    ('FAMILIAR', 'Familiar'),
                    ('VEHICULAR', 'Vehicular'),
                    ('OTROS', 'Otros'),
                ], db_index=True, default='OTROS', help_text='Categoría derivada de tipificacion (clasificador automático)', max_length=20)),
                ('tipificacion_raw', models.TextField(blank=True, help_text='Tipificación textual cruda de Leder')),
                ('fecha_hecho', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('fecha_registro', models.DateTimeField(blank=True, null=True)),
                ('lugar_hecho', models.CharField(blank=True, max_length=300)),
                ('contenido', models.TextField(blank=True, help_text='Descripción completa de los hechos (texto largo)')),
                ('qr_valor', models.CharField(blank=True, max_length=255)),
                ('dni', models.ForeignKey(db_column='dni', on_delete=django.db.models.deletion.CASCADE, related_name='police_records', to='reniec.dnicache', to_field='dni')),
            ],
            options={
                'verbose_name': '🚨 Denuncia policial',
                'verbose_name_plural': '🚨 Denuncias policiales',
                'unique_together': {('dni', 'nro_denuncia')},
            },
        ),
        migrations.AddIndex(
            model_name='personpolicerecord',
            index=models.Index(fields=['dni', '-fecha_hecho'], name='reniec_police_idx1'),
        ),
        migrations.AddIndex(
            model_name='personpolicerecord',
            index=models.Index(fields=['dni', 'category'], name='reniec_police_idx2'),
        ),

        # ─── PersonExpedienteMeta ─────────────────────────────────────────
        migrations.CreateModel(
            name='PersonExpedienteMeta',
            fields=[
                ('created', models.DateTimeField(auto_now_add=True, help_text='When the instance was created.', verbose_name='created at')),
                ('updated', models.DateTimeField(auto_now=True, help_text='The last time at the instance was modified.', verbose_name='updated at')),
                ('deleted', models.BooleanField(default=False, help_text='It can be set to false, usefull to simulate deletion')),
                ('phones_fetched_at', models.DateTimeField(blank=True, null=True)),
                ('family_tree_fetched_at', models.DateTimeField(blank=True, null=True)),
                ('family_household_fetched_at', models.DateTimeField(blank=True, null=True)),
                ('salaries_fetched_at', models.DateTimeField(blank=True, null=True)),
                ('marriages_fetched_at', models.DateTimeField(blank=True, null=True)),
                ('addresses_fetched_at', models.DateTimeField(blank=True, null=True)),
                ('police_fetched_at', models.DateTimeField(blank=True, null=True)),
                ('last_full_refresh_at', models.DateTimeField(blank=True, help_text='Última vez que se llamó /full/<dni>/ con refresh completo', null=True)),
                ('dni', models.OneToOneField(db_column='dni', on_delete=django.db.models.deletion.CASCADE, primary_key=True, related_name='expediente_meta', serialize=False, to='reniec.dnicache', to_field='dni')),
            ],
            options={
                'verbose_name': '📋 Expediente meta (TTLs)',
                'verbose_name_plural': '📋 Expedientes meta (TTLs)',
            },
        ),
    ]

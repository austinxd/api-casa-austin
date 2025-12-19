# Generated for reniec app - Complete DNI structure

import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('clients', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='DNICache',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('dni', models.CharField(db_index=True, max_length=8, unique=True)),
                # Datos del documento
                ('nu_dni', models.CharField(blank=True, max_length=20, null=True)),
                ('nu_ficha', models.CharField(blank=True, max_length=50, null=True)),
                ('nu_imagen', models.CharField(blank=True, max_length=50, null=True)),
                ('digito_verificacion', models.CharField(blank=True, max_length=1, null=True)),
                # Datos personales
                ('nombres', models.CharField(blank=True, db_column='preNombres', max_length=200, null=True)),
                ('apellido_paterno', models.CharField(blank=True, db_column='apePaterno', max_length=100, null=True)),
                ('apellido_materno', models.CharField(blank=True, db_column='apeMaterno', max_length=100, null=True)),
                ('apellido_casada', models.CharField(blank=True, db_column='apCasada', max_length=100, null=True)),
                # Datos adicionales
                ('fecha_nacimiento', models.DateField(blank=True, db_column='feNacimiento', null=True)),
                ('estatura', models.IntegerField(blank=True, null=True)),
                ('sexo', models.CharField(blank=True, max_length=1, null=True)),
                ('estado_civil', models.CharField(blank=True, db_column='estadoCivil', max_length=50, null=True)),
                ('grado_instruccion', models.CharField(blank=True, db_column='gradoInstruccion', max_length=100, null=True)),
                # Fechas del documento
                ('fecha_emision', models.DateField(blank=True, db_column='feEmision', null=True)),
                ('fecha_inscripcion', models.DateField(blank=True, db_column='feInscripcion', null=True)),
                ('fecha_caducidad', models.DateField(blank=True, db_column='feCaducidad', null=True)),
                # Padres
                ('nom_padre', models.CharField(blank=True, db_column='nomPadre', max_length=200, null=True)),
                ('nom_madre', models.CharField(blank=True, db_column='nomMadre', max_length=200, null=True)),
                # Ubicación de nacimiento
                ('pais', models.CharField(blank=True, max_length=100, null=True)),
                ('departamento', models.CharField(blank=True, max_length=100, null=True)),
                ('provincia', models.CharField(blank=True, max_length=100, null=True)),
                ('distrito', models.CharField(blank=True, max_length=100, null=True)),
                # Dirección actual
                ('pais_direccion', models.CharField(blank=True, db_column='paisDireccion', max_length=100, null=True)),
                ('departamento_direccion', models.CharField(blank=True, db_column='depaDireccion', max_length=100, null=True)),
                ('provincia_direccion', models.CharField(blank=True, db_column='provDireccion', max_length=100, null=True)),
                ('distrito_direccion', models.CharField(blank=True, db_column='distDireccion', max_length=100, null=True)),
                ('direccion', models.TextField(blank=True, db_column='desDireccion', null=True)),
                # Contacto
                ('telefono', models.CharField(blank=True, max_length=50, null=True)),
                ('email', models.CharField(blank=True, max_length=200, null=True)),
                # Otros datos
                ('dona_organos', models.CharField(blank=True, db_column='donaOrganos', max_length=10, null=True)),
                ('observacion', models.TextField(blank=True, null=True)),
                # Restricciones
                ('fecha_restriccion', models.CharField(blank=True, db_column='feRestriccion', max_length=50, null=True)),
                ('de_restriccion', models.TextField(blank=True, db_column='deRestriccion', null=True)),
                # Datos electorales
                ('gp_votacion', models.CharField(blank=True, db_column='gpVotacion', max_length=100, null=True)),
                ('multas_electorales', models.TextField(blank=True, db_column='multasElectorales', null=True)),
                ('multa_admin', models.TextField(blank=True, db_column='multaAdmin', null=True)),
                # Actualización
                ('fecha_actualizacion', models.DateField(blank=True, db_column='feActualizacion', null=True)),
                # Documentos sustento
                ('doc_sustento', models.CharField(blank=True, db_column='docSustento', max_length=100, null=True)),
                ('nu_doc_sustento', models.CharField(blank=True, db_column='nuDocSustento', max_length=100, null=True)),
                ('nu_doc_declarante', models.CharField(blank=True, db_column='nuDocDeclarante', max_length=100, null=True)),
                ('vinculo_declarante', models.CharField(blank=True, db_column='vinculoDeclarante', max_length=100, null=True)),
                # Cancelación
                ('cancelacion', models.TextField(blank=True, null=True)),
                # Fallecimiento
                ('fecha_fallecimiento', models.DateField(blank=True, db_column='feFallecimiento', null=True)),
                ('depa_fallecimiento', models.CharField(blank=True, db_column='depaFallecimiento', max_length=100, null=True)),
                ('prov_fallecimiento', models.CharField(blank=True, db_column='provFallecimiento', max_length=100, null=True)),
                ('dist_fallecimiento', models.CharField(blank=True, db_column='distFallecimiento', max_length=100, null=True)),
                # Ubigeo
                ('codigo_postal', models.CharField(blank=True, max_length=10, null=True)),
                ('ubigeo_reniec', models.CharField(blank=True, max_length=10, null=True)),
                ('ubigeo_inei', models.CharField(blank=True, max_length=10, null=True)),
                ('ubigeo_sunat', models.CharField(blank=True, max_length=10, null=True)),
                # Imágenes
                ('foto', models.TextField(blank=True, db_column='imagen_foto', null=True)),
                ('huella_izquierda', models.TextField(blank=True, null=True)),
                ('huella_derecha', models.TextField(blank=True, null=True)),
                ('firma', models.TextField(blank=True, null=True)),
                # Datos completos
                ('raw_data', models.JSONField(blank=True, help_text='Datos completos de la API', null=True)),
                # Metadatos
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
                ('source', models.CharField(choices=[('api', 'API Externa'), ('manual', 'Ingreso Manual'), ('legacy', 'Migrado de BD Legacy')], default='api', max_length=20)),
            ],
            options={
                'verbose_name': 'DNI Cache',
                'verbose_name_plural': 'DNI Cache',
                'db_table': 'reniec_dni_cache',
                'ordering': ['-created'],
            },
        ),
        migrations.CreateModel(
            name='APIKey',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(help_text='Nombre de la aplicación', max_length=100)),
                ('key', models.CharField(db_index=True, max_length=64, unique=True)),
                ('is_active', models.BooleanField(default=True)),
                ('rate_limit_per_day', models.IntegerField(default=1000, help_text='Límite de consultas por día')),
                ('rate_limit_per_minute', models.IntegerField(default=10, help_text='Límite de consultas por minuto')),
                ('can_view_photo', models.BooleanField(default=False, help_text='Puede ver la foto del DNI')),
                ('can_view_full_data', models.BooleanField(default=False, help_text='Puede ver todos los datos (direccion, padres, etc)')),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
                ('last_used', models.DateTimeField(blank=True, null=True)),
                ('notes', models.TextField(blank=True, null=True)),
            ],
            options={
                'verbose_name': 'API Key',
                'verbose_name_plural': 'API Keys',
                'db_table': 'reniec_api_keys',
            },
        ),
        migrations.CreateModel(
            name='DNIQueryLog',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('dni', models.CharField(db_index=True, max_length=8)),
                ('source_app', models.CharField(db_index=True, help_text='Identificador de la aplicación que hizo la consulta', max_length=50)),
                ('source_ip', models.GenericIPAddressField(blank=True, null=True)),
                ('user_agent', models.CharField(blank=True, max_length=500, null=True)),
                ('success', models.BooleanField(default=False)),
                ('from_cache', models.BooleanField(default=False, help_text='Si el resultado vino del cache')),
                ('error_message', models.TextField(blank=True, null=True)),
                ('response_time_ms', models.IntegerField(blank=True, help_text='Tiempo de respuesta en ms', null=True)),
                ('created', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('client', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='dni_queries', to='clients.clients')),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='dni_queries', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'DNI Query Log',
                'verbose_name_plural': 'DNI Query Logs',
                'db_table': 'reniec_query_log',
                'ordering': ['-created'],
            },
        ),
        migrations.AddIndex(
            model_name='dniquerylog',
            index=models.Index(fields=['source_app', 'created'], name='reniec_quer_source__df4d08_idx'),
        ),
        migrations.AddIndex(
            model_name='dniquerylog',
            index=models.Index(fields=['dni', 'created'], name='reniec_quer_dni_e01fbe_idx'),
        ),
    ]

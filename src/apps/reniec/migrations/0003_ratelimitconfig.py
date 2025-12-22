# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reniec', '0002_dniquerylog_referrer'),
    ]

    operations = [
        migrations.CreateModel(
            name='RateLimitConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('ip_limit', models.IntegerField(default=3, help_text='Máximo de consultas por IP en la ventana de tiempo')),
                ('ip_window_seconds', models.IntegerField(default=600, help_text='Ventana de tiempo para límite por IP (segundos). 600 = 10 minutos')),
                ('dni_limit', models.IntegerField(default=2, help_text='Máximo de consultas por DNI en la ventana de tiempo')),
                ('dni_window_seconds', models.IntegerField(default=3600, help_text='Ventana de tiempo para límite por DNI (segundos). 3600 = 1 hora')),
                ('global_limit', models.IntegerField(default=10, help_text='Máximo de consultas TOTALES en la ventana de tiempo')),
                ('global_window_seconds', models.IntegerField(default=3600, help_text='Ventana de tiempo para límite global (segundos). 3600 = 1 hora')),
                ('is_enabled', models.BooleanField(default=True, help_text='Si está desactivado, el endpoint público queda deshabilitado')),
                ('updated', models.DateTimeField(auto_now=True)),
                ('updated_by', models.CharField(blank=True, max_length=100, null=True)),
            ],
            options={
                'verbose_name': 'Rate Limit Config',
                'verbose_name_plural': 'Rate Limit Config',
                'db_table': 'reniec_rate_limit_config',
            },
        ),
    ]

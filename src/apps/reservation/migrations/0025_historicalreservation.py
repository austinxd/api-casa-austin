# Generated migration for adding HistoricalRecords to Reservation

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import simple_history.models
import uuid


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('clients', '0001_initial'),
        ('property', '0059_add_status_sensor_to_homeassistant_device'),
        ('reservation', '0024_transform_music_sessions'),
    ]

    operations = [
        migrations.CreateModel(
            name='HistoricalReservation',
            fields=[
                ('id', models.UUIDField(db_index=True, default=uuid.uuid4, editable=False)),
                ('created', models.DateTimeField(blank=True, editable=False, help_text='When the instance was created.', verbose_name='created at')),
                ('deleted', models.BooleanField(default=False, help_text='It can be set to false, usefull to simulate deletion')),
                ('ManychatFecha', models.IntegerField(default=0)),
                ('late_checkout', models.BooleanField(default=False)),
                ('late_check_out_date', models.DateField(blank=True, null=True)),
                ('comentarios_reservas', models.TextField(blank=True, help_text='Comentarios adicionales sobre la reserva.', null=True)),
                ('advance_payment_currency', models.CharField(choices=[('sol', 'Soles'), ('usd', 'Dólares')], default='sol', max_length=3)),
                ('origin', models.CharField(choices=[('air', 'Airbnb'), ('aus', 'Austin'), ('man', 'Mantenimiento'), ('client', 'Cliente Web')], default='aus', max_length=6)),
                ('status', models.CharField(choices=[('incomplete', 'Incompleta'), ('pending', 'Pendiente'), ('under_review', 'En Revisión - Segundo Voucher'), ('approved', 'Aprobada'), ('rejected', 'Rechazada'), ('cancelled', 'Cancelada')], default='incomplete', help_text='Estado de la reserva', max_length=15)),
                ('check_in_date', models.DateField()),
                ('check_out_date', models.DateField()),
                ('guests', models.PositiveIntegerField(default=1)),
                ('price_usd', models.DecimalField(blank=True, decimal_places=2, default=0, max_digits=20, null=True)),
                ('price_sol', models.DecimalField(blank=True, decimal_places=2, default=0, max_digits=20, null=True)),
                ('advance_payment', models.DecimalField(blank=True, decimal_places=2, default=0, max_digits=20, null=True)),
                ('uuid_external', models.CharField(blank=True, max_length=100, null=True)),
                ('tel_contact_number', models.CharField(blank=True, max_length=255, null=True)),
                ('full_payment', models.BooleanField(default=False)),
                ('temperature_pool', models.BooleanField(default=False)),
                ('ip_cliente', models.GenericIPAddressField(blank=True, null=True)),
                ('user_agent', models.TextField(blank=True, null=True)),
                ('referer', models.TextField(blank=True, null=True)),
                ('fbclid', models.CharField(blank=True, max_length=255, null=True)),
                ('utm_source', models.CharField(blank=True, max_length=255, null=True)),
                ('utm_medium', models.CharField(blank=True, max_length=255, null=True)),
                ('utm_campaign', models.CharField(blank=True, max_length=255, null=True)),
                ('fbp', models.CharField(blank=True, max_length=255, null=True)),
                ('fbc', models.CharField(blank=True, max_length=255, null=True)),
                ('points_redeemed', models.DecimalField(decimal_places=2, default=0, help_text='Puntos canjeados en esta reserva', max_digits=10)),
                ('discount_code_used', models.CharField(blank=True, help_text='Código de descuento utilizado en esta reserva', max_length=20, null=True)),
                ('price_latecheckout', models.DecimalField(blank=True, decimal_places=2, default=0, help_text='Precio cobrado por late checkout (uso extendido del día de salida)', max_digits=10, null=True)),
                ('price_temperature_pool', models.DecimalField(blank=True, decimal_places=2, default=0, help_text='Precio cobrado por temperado de piscina', max_digits=10, null=True)),
                ('payment_voucher_deadline', models.DateTimeField(blank=True, help_text='Fecha límite para subir voucher de pago (1 hora después de crear reserva)', null=True)),
                ('payment_voucher_uploaded', models.BooleanField(default=False, help_text='Indica si el cliente ya subió el voucher de pago')),
                ('payment_confirmed', models.BooleanField(default=False, help_text='Indica si el cliente confirmó que realizó el pago')),
                ('payment_approved_notification_sent', models.BooleanField(default=False, help_text='Indica si ya se envió la notificación de pago aprobado por WhatsApp')),
                ('history_id', models.AutoField(primary_key=True, serialize=False)),
                ('history_date', models.DateTimeField(db_index=True)),
                ('history_change_reason', models.CharField(max_length=100, null=True)),
                ('history_type', models.CharField(choices=[('+', 'Created'), ('~', 'Changed'), ('-', 'Deleted')], max_length=1)),
                ('client', models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to='clients.clients')),
                ('history_user', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('property', models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to='property.property')),
                ('seller', models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Histórico',
                'verbose_name_plural': 'Histórico de cambios',
                'ordering': ('-history_date', '-history_id'),
                'get_latest_by': ('history_date', 'history_id'),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
    ]

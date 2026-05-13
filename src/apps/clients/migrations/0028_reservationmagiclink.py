# Generated for R4 — Magic Link de Reserva
import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        # NOTA: no listamos 'chatbot' como dependencia porque ese app no
        # mantiene archivos de migración en este repo (las tablas ya existen
        # en producción). El FK string 'chatbot.ChatSession' se resuelve por
        # app registry al aplicar; la tabla destino debe existir en BD.
        ('property', '0001_initial'),
        ('clients', '0027_add_notification_log'),
    ]

    operations = [
        migrations.CreateModel(
            name='ReservationMagicLink',
            fields=[
                ('id', models.UUIDField(
                    primary_key=True,
                    default=uuid.uuid4,
                    editable=False,
                    serialize=False,
                )),
                ('created', models.DateTimeField(
                    auto_now_add=True,
                    help_text='When the instance was created.',
                    verbose_name='created at',
                )),
                ('updated', models.DateTimeField(
                    auto_now=True,
                    help_text='The last time at the instance was modified.',
                    verbose_name='updated at',
                )),
                ('deleted', models.BooleanField(
                    default=False,
                    help_text='It can be set to false, usefull to simulate deletion',
                )),
                ('token_hash', models.CharField(
                    max_length=64,
                    unique=True,
                    db_index=True,
                    help_text='sha256 del token visible. El raw NUNCA se persiste.',
                )),
                ('check_in', models.DateField(
                    help_text='Fecha de check-in pre-seleccionada.',
                )),
                ('check_out', models.DateField(
                    help_text='Fecha de check-out pre-seleccionada.',
                )),
                ('guests', models.PositiveSmallIntegerField(
                    help_text='Personas pre-seleccionadas.',
                )),
                ('wa_id', models.CharField(
                    max_length=20,
                    help_text='WhatsApp ID al que se envió el link (para auditoría).',
                )),
                ('expires_at', models.DateTimeField(
                    db_index=True,
                    help_text='Fecha de expiración (típicamente 1h tras creación).',
                )),
                ('used_at', models.DateTimeField(
                    null=True, blank=True,
                    help_text='Cuándo fue redimido por primera vez. Si max_uses=1, '
                              'bloquea redenciones posteriores.',
                )),
                ('max_uses', models.PositiveSmallIntegerField(
                    default=1,
                    help_text='Cuántas veces se puede redimir. Por defecto 1 (one-time).',
                )),
                ('use_count', models.PositiveSmallIntegerField(
                    default=0,
                    help_text='Cuántas veces se redimió efectivamente.',
                )),
                ('created_ip', models.GenericIPAddressField(
                    null=True, blank=True,
                    help_text='IP del servidor que generó el link (siempre la del bot).',
                )),
                ('redeemed_ip', models.GenericIPAddressField(
                    null=True, blank=True,
                    help_text='IP del cliente al redimir.',
                )),
                ('redeemed_user_agent', models.CharField(
                    max_length=255, blank=True, default='',
                    help_text='User-Agent al redimir.',
                )),
                ('client', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='magic_links',
                    to='clients.clients',
                    help_text='Cliente al que se emitió el link.',
                )),
                ('chat_session', models.ForeignKey(
                    on_delete=django.db.models.deletion.SET_NULL,
                    null=True, blank=True,
                    related_name='magic_links',
                    to='chatbot.chatsession',
                    help_text='Sesión de chat que generó el link.',
                )),
                ('property', models.ForeignKey(
                    on_delete=django.db.models.deletion.SET_NULL,
                    null=True, blank=True,
                    related_name='magic_links',
                    to='property.property',
                    help_text='Casa pre-seleccionada (opcional).',
                )),
            ],
            options={
                'verbose_name': '🔗 Magic Link de Reserva',
                'verbose_name_plural': '🔗 Magic Links de Reserva',
                'ordering': ['-created'],
            },
        ),
        migrations.AddIndex(
            model_name='reservationmagiclink',
            index=models.Index(
                fields=['expires_at'],
                name='clients_res_expires_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='reservationmagiclink',
            index=models.Index(
                fields=['client', 'created'],
                name='clients_res_client_created_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='reservationmagiclink',
            index=models.Index(
                fields=['chat_session', 'created'],
                name='clients_res_session_created_idx',
            ),
        ),
    ]

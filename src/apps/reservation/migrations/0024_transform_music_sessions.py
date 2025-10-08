# Migration to transform music sessions: remove MusicSession, update MusicSessionParticipant
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('reservation', '0023_alter_musicsession_options'),
    ]

    operations = [
        # Primero eliminar participantes (tabla dependiente)
        migrations.DeleteModel(
            name='MusicSessionParticipant',
        ),
        # Luego eliminar sesiones
        migrations.DeleteModel(
            name='MusicSession',
        ),
        # Recrear MusicSessionParticipant apuntando directamente a Reservation
        migrations.CreateModel(
            name='MusicSessionParticipant',
            fields=[
                ('id', models.UUIDField(default=__import__('uuid').uuid4, editable=False, primary_key=True, serialize=False)),
                ('created', models.DateTimeField(auto_now_add=True, help_text='When the instance was created.', verbose_name='created at')),
                ('updated', models.DateTimeField(auto_now=True, help_text='The last time at the instance was modified.', verbose_name='updated at')),
                ('deleted', models.BooleanField(default=False, help_text='It can be set to false, usefull to simulate deletion')),
                ('status', models.CharField(choices=[('pending', 'Pendiente'), ('accepted', 'Aceptado'), ('rejected', 'Rechazado')], default='pending', max_length=20, verbose_name='Estado')),
                ('requested_at', models.DateTimeField(auto_now_add=True, verbose_name='Solicitado el')),
                ('accepted_at', models.DateTimeField(blank=True, null=True, verbose_name='Aceptado el')),
                ('rejected_at', models.DateTimeField(blank=True, null=True, verbose_name='Rechazado el')),
                ('client', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='music_session_requests', to='clients.clients', verbose_name='Cliente solicitante')),
                ('reservation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='music_participants', to='reservation.reservation', verbose_name='Reserva')),
            ],
            options={
                'verbose_name': 'Participante de Música',
                'verbose_name_plural': 'Participantes de Música',
                'ordering': ['-requested_at'],
                'unique_together': {('reservation', 'client')},
            },
        ),
    ]

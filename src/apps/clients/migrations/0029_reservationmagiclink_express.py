# Generated for R4.2 — Reserva Express (link_type + DNI fields)
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0028_reservationmagiclink'),
    ]

    operations = [
        # Hacer client nullable: para guest_express no hay Client aún.
        migrations.AlterField(
            model_name='reservationmagiclink',
            name='client',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='magic_links',
                to='clients.clients',
                null=True, blank=True,
                help_text='Cliente vinculado. Null para guest_express '
                          '(se crea al confirmar).',
            ),
        ),
        # Nuevo: tipo de link
        migrations.AddField(
            model_name='reservationmagiclink',
            name='link_type',
            field=models.CharField(
                max_length=20,
                choices=[
                    ('existing_client', 'Cliente existente'),
                    ('guest_express', 'Cliente nuevo — DNI validado'),
                ],
                default='existing_client',
                db_index=True,
                help_text='Tipo de magic link: cliente existente o express con DNI.',
            ),
        ),
        # Campos guest_express (null para existing_client)
        migrations.AddField(
            model_name='reservationmagiclink',
            name='document_type',
            field=models.CharField(
                max_length=3,
                null=True, blank=True,
                help_text='Solo "dni" en R4.2 MVP. Null para existing_client.',
            ),
        ),
        migrations.AddField(
            model_name='reservationmagiclink',
            name='document_number',
            field=models.CharField(
                max_length=15,
                null=True, blank=True,
                help_text='DNI de 8 dígitos validado por RENIEC. '
                          'Null para existing_client.',
            ),
        ),
        migrations.AddField(
            model_name='reservationmagiclink',
            name='validated_full_name',
            field=models.CharField(
                max_length=120,
                null=True, blank=True,
                help_text='Nombre completo devuelto por RENIEC y confirmado en chat.',
            ),
        ),
        migrations.AddField(
            model_name='reservationmagiclink',
            name='dni_validated_at',
            field=models.DateTimeField(
                null=True, blank=True,
                help_text='Cuándo se validó el DNI con RENIEC.',
            ),
        ),
    ]

# Agrega rol_dni + nombre_denunciante + personas_raw a PersonPoliceRecord.
# Permite distinguir si el DNI consultado fue denunciante, denunciado,
# testigo, etc. CRÍTICO para no confundir víctimas con acusados.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reniec', '0004_expediente_models'),
    ]

    operations = [
        migrations.AddField(
            model_name='personpolicerecord',
            name='rol_dni',
            field=models.CharField(
                choices=[
                    ('DENUNCIANTE', 'Denunciante (presentó la denuncia)'),
                    ('DENUNCIADO', 'Denunciado (acusado)'),
                    ('AGRAVIADO', 'Agraviado (víctima)'),
                    ('TESTIGO', 'Testigo'),
                    ('INVESTIGADO', 'Investigado'),
                    ('IMPUTADO', 'Imputado'),
                    ('OTRO', 'Otro'),
                    ('DESCONOCIDO', 'Desconocido'),
                ],
                db_index=True,
                default='DESCONOCIDO',
                help_text='Rol del DNI consultado: denunciante / denunciado / testigo / etc.',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='personpolicerecord',
            name='nombre_denunciante',
            field=models.CharField(
                blank=True, max_length=200,
                help_text='Quién presentó la denuncia (puede no ser el DNI consultado)',
            ),
        ),
        migrations.AddField(
            model_name='personpolicerecord',
            name='personas_raw',
            field=models.JSONField(
                default=list, blank=True,
                help_text='Array completo de personas involucradas con su situación (de Leder)',
            ),
        ),
    ]

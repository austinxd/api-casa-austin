# Generated manually for admin_ai app

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AdminChatSession',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created', models.DateTimeField(auto_now_add=True, help_text='When the instance was created.', verbose_name='created at')),
                ('updated', models.DateTimeField(auto_now=True, help_text='The last time at the instance was modified.', verbose_name='updated at')),
                ('deleted', models.BooleanField(default=False, help_text='It can be set to false, usefull to simulate deletion')),
                ('title', models.CharField(default='Nueva conversación', help_text='Título auto-generado o editado por el usuario', max_length=200)),
                ('model_used', models.CharField(default='gpt-4.1', help_text='Modelo de IA utilizado', max_length=50)),
                ('total_tokens', models.PositiveIntegerField(default=0)),
                ('message_count', models.PositiveIntegerField(default=0)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='admin_chat_sessions', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': '🧠 Sesión IA Admin',
                'verbose_name_plural': '🧠 Sesiones IA Admin',
                'ordering': ['-updated'],
            },
        ),
        migrations.CreateModel(
            name='AdminChatMessage',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created', models.DateTimeField(auto_now_add=True, help_text='When the instance was created.', verbose_name='created at')),
                ('updated', models.DateTimeField(auto_now=True, help_text='The last time at the instance was modified.', verbose_name='updated at')),
                ('deleted', models.BooleanField(default=False, help_text='It can be set to false, usefull to simulate deletion')),
                ('role', models.CharField(choices=[('user', 'Usuario'), ('assistant', 'Asistente'), ('system', 'Sistema')], max_length=10)),
                ('content', models.TextField()),
                ('tool_calls', models.JSONField(blank=True, default=list, help_text='Herramientas usadas por la IA en este mensaje')),
                ('tokens_used', models.PositiveIntegerField(default=0)),
                ('session', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='messages', to='admin_ai.adminchatsession')),
            ],
            options={
                'verbose_name': '📝 Mensaje IA Admin',
                'verbose_name_plural': '📝 Mensajes IA Admin',
                'ordering': ['created'],
            },
        ),
    ]

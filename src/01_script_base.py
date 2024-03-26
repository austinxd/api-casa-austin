import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.conf import settings
from django.contrib.auth.hashers import make_password

from apps.accounts.models import CustomUser

# Creamos Roles bases del proyecto
def crear_super_user():

    creado = False
    if not CustomUser.objects.filter(is_staff=True):
        try:
            usuario = CustomUser.objects.create(
                first_name='Admin',
                last_name='Sistema',
                username=f"{settings.DATABASES['default']['NAME']}@mail.com",
                email=f"{settings.DATABASES['default']['NAME']}@mail.com",
                password=make_password(f"{settings.DATABASES['default']['PASSWORD']}")
            )

            usuario.is_staff = True
            usuario.is_superuser = True
            usuario.save()

            creado=True
        except Exception as e:
            print('ERROR AL CREAR SUPER USER: ', str(e))

    print('Super usuario creado exitosamente') if creado else None
    print('*** Finalizar procedimiento de Super User ***')


if __name__ == "__main__":
    crear_super_user()
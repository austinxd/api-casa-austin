import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.conf import settings
from django.contrib.auth.hashers import make_password

from django.contrib.auth.models import Group
from apps.accounts.models import CustomUser

def create_group(group_name):
    """
    Funcion Auxiliar para crear grupo en caso que no exista
    """
    if not Group.objects.filter(name=group_name).exists():
        group = Group.objects.create(name=group_name)
        print(f"Grupo '{group.name}' creado con éxito.")
        return group
    else:
        print(f"El grupo '{group_name}' ya existe.")

# Creamos Roles bases del proyecto
def crear_super_user_and_groups():

    grupo_admin_instance = create_group('admin')
    create_group('vendedor')
    create_group('mantenimiento')

    creado = False
    if not CustomUser.objects.filter(is_staff=True):
        try:
            usuario = CustomUser.objects.create(
                first_name='Admin',
                last_name='Sistema',
                username=f"admin@mail.com",
                email=f"admin@mail.com",
                password=make_password(f"{settings.DATABASES['default']['PASSWORD']}")
            )

            usuario.is_staff = True
            usuario.is_superuser = True
            usuario.save()

            creado=True
        except Exception as e:
            print('ERROR AL CREAR SUPER USER: ', str(e))

    for us in CustomUser.objects.filter(is_staff=True):
        us.groups.add(grupo_admin_instance)

    print('Super usuario creado exitosamente') if creado else None
    print('*** Finalizar procedimiento de Super User ***')


if __name__ == "__main__":
    crear_super_user_and_groups()
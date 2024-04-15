import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from datetime import datetime

from django.conf import settings
from django.contrib.auth.hashers import make_password

from apps.clients.models import Clients
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
    print('*** Comenzar procedimiento de Super User & Roles/Groups***')

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
    print('*** Finalizar procedimiento de Super User & Roles/Groups***')

def crear_cliente_mantenimiento():
    print('*** Comenzar procedimiento Cliente Mantenimiento ***')
    if not Clients.objects.filter(first_name="Mantenimiento").exists():
        print('Creando cliente "Mantenimiento"')
        Clients.objects.create(
            number_doc="0",
            first_name="Mantenimiento",
            last_name="Mantenimiento",
            sex="m",
            date = datetime.now(),
            tel_number=0,
            email="mantenimiento@mail.com"
        )
    else:
        print('Ya existe cliente "Mantenimiento"')

    print('*** Finalizar procedimiento Cliente Mantenimiento ***')


if __name__ == "__main__":
    crear_super_user_and_groups()
    crear_cliente_mantenimiento()
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password

User = get_user_model()
from django.contrib.auth.models import Group


def create_group(group_name):
    """ Funcion para crear un grupo
    - Params:
        - group_name: Nombre del grupo
    - Return:
        - Group instance
    """
    if not Group.objects.filter(name=group_name).exists():
        group = Group.objects.create(name=group_name)
        return group
    else:
        print(f"El grupo '{group_name}' ya existe.")
    
    return False

def create_user(super_user=False, group=None):
    """ Crear usuario y asignarle un grupo (opcional)
    - Params:
        - super_user: True para crear super usuario
        - group: Una instancia de Grupo para asignarle al usuario creado
    - Return:
        - User instance con grupo (opcional)
    """
    try:
        usuario = User.objects.create(
            first_name='Admin',
            last_name='Sistema',
            username=f"admin@mail.com",
            email=f"admin@mail.com",
            password=make_password("paloma227")
        )

        if super_user:
            usuario.is_staff = True
            usuario.is_superuser = True
            usuario.save()

    except Exception as e:
         print('ERROR AL CREAR SUPER USER: ', str(e))
    
    if group:
        usuario.groups.add(group)

    return usuario
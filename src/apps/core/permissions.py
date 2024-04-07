from rest_framework import permissions

class CustomPermissions(permissions.BasePermission):
    """Chequear si el usuario tiene permisos para acceder a la view segun el rol
    Flujo:
        - Todos los roles tienen acceso a pedir datos (GET)
        - Solo Admin y Vendedores puede escribir en la BD
        - Demas restricciones se agregan en otros Permissions, en la view o serializers
    Args:
        - request: Datos de la request
        - view: Datos de la view que llamó la clase
    
    Return
        - Bool segun si tiene permiso o no de acceder a la view
    """

    def has_permission(self, request, view):

        # Todas las peticiones GET de usuarios logueados con algun grupo asignado son permitidas
        if request.method == 'GET':
            if request.user.groups.all():
                return True

        # Si quiere hacer una peticion con los verbos que modifican BD reviso que sea vendedor o admin
        if request.method in ['POST', 'PATCH', 'PUT', 'DELETE']:
            for gr in request.user.groups.all():
                if gr.name == 'admin' or gr.name == 'vendedor':
                    return True

        # Default
        return False

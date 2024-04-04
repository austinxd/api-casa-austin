from rest_framework.views import exception_handler
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from django.http import Http404

def custom_exception_handler(exc, context):
    if isinstance(exc, Http404):
        return Response({"detail": "El recurso no existe o no esta disponible para Ud."}, status=404)
    else:
        return exception_handler(exc, context)

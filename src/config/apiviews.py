import jwt

from django.conf import settings
from django.http.response import JsonResponse

from rest_framework.permissions import IsAuthenticated, AllowAny

from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import CustomUser


class TestApi(APIView):
    permission_classes = [AllowAny]
    serializer_class = None

    def get(self, request, format=None):
        content = {
            'message': 'Bienvenido/a a Casa Austin. API Funcionando ok!'
        }
        return Response(content)

class TestLogeoApi(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = None

    def get(self, request, format=None):

        tokenJWT = self.request.headers['Authorization'].split()[1]
        tokenDecoded = jwt.decode(tokenJWT, settings.SECRET_KEY, algorithms=["HS256"])

        try:
            usuario = CustomUser.objects.get(pk=tokenDecoded['user_id'])
        except:
            return JsonResponse({'mensaje':'Usuario inexistente'}, status=404)

        content = {
            'message': 'Bienvenido/a a Casa Austin. API y Token Funcionando ok!',
            'email': usuario.email
        }

        return Response(content)
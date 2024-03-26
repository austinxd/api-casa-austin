from rest_framework import viewsets

from .models import Clients
from .serializers import ClientsSerializer


class ClientsApiView(viewsets.ModelViewSet):
    serializer_class = ClientsSerializer
    queryset = Clients.objects.all().order_by("last_name")

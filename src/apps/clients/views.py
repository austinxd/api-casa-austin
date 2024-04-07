from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import filters, viewsets
from rest_framework.views import APIView
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.paginator import CustomPagination

from .models import Clients, TokenApiClients
from .serializers import ClientsSerializer, TokenApiClienteSerializer


class TokenApiClientApiView(APIView):
    serializer_class = TokenApiClienteSerializer
    
    def get(self, request):
        content = self.serializer_class(TokenApiClients.objects.exclude(deleted=True).order_by("created").last()).data
        return Response(content, status=200)

class ClientsApiView(viewsets.ModelViewSet):
    serializer_class = ClientsSerializer
    # queryset = Clients.objects.all().order_by("last_name")
    filter_backends = [filters.SearchFilter]
    search_fields = ["email", "first_name", "last_name"]
    pagination_class = CustomPagination

    def get_pagination_class(self):
        """Determinar si usar o no paginación
        - page_size = valor
        - valor = un numero entero, será el tamaño de la pagina
        - valor = none, no se pagina el resultado
        """
        if self.request.GET.get("page_size") == "none":
            return None

        return self.pagination_class
    
    @extend_schema(
        parameters=[
            OpenApiParameter(
                "page_size",
                OpenApiTypes.INT,
                description="Enviar page_size=valor para determinar tamaño de la pagina, sino enviar page_size=none para no tener paginado",
                required=False,
            ),
            OpenApiParameter(
                "search",
                OpenApiTypes.STR,
                description="Busqueda por nombre, apellido o email",
                required=False,
            ),
        ],
        responses={200: ClientsSerializer},
        methods=["GET"],
    )
    def list(self, request, *args, **kwargs):
        self.pagination_class = self.get_pagination_class()
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        queryset = Clients.objects.all().order_by("last_name")
        if self.action == "search_clients":
            params = self.request.GET
            self.pagination_class = None
            if not params:
                return queryset.none()
            return queryset

        return queryset

    @action(
        detail=False,
        methods=["GET"],
        url_name="search",
        url_path="search",
    )
    def search_clients(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

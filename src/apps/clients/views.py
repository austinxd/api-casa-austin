from rest_framework import filters, viewsets
from rest_framework.decorators import action

from apps.core.paginator import CustomPagination

from .models import Clients
from .serializers import ClientsSerializer


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

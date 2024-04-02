from rest_framework import filters, viewsets

from apps.core.paginator import CustomPagination

from .models import Property
from .serializers import PropertySerializer


class PropertyApiView(viewsets.ReadOnlyModelViewSet):
    serializer_class = PropertySerializer
    queryset = Property.objects.all().order_by("name")
    filter_backends = [filters.SearchFilter]
    search_fields = ["name"]
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
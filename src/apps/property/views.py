from rest_framework import filters, viewsets

from .models import Property
from .serializers import PropertySerializer


class PropertyApiView(viewsets.ReadOnlyModelViewSet):
    serializer_class = PropertySerializer
    queryset = Property.objects.all().order_by("name")
    filter_backends = [filters.SearchFilter]
    search_fields = ["name"]

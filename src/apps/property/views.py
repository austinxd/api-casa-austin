import calendar
from datetime import datetime
from django.db.models import Q

from rest_framework import filters, viewsets
from rest_framework.exceptions import ValidationError

from apps.core.paginator import CustomPagination

from .models import Property, ProfitPropertyAirBnb
from .serializers import PropertySerializer, ProfitPropertyAirBnbSerializer


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
    
class ProfitPropertyApiView(viewsets.ModelViewSet):
    serializer_class = ProfitPropertyAirBnbSerializer
    queryset = ProfitPropertyAirBnb.objects.all().order_by("created")
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

    def get_queryset(self):
        queryset = super().get_queryset()

        """
        Custom queryset to search reservations in a given month-year
        """
        if self.action == 'list':
            if self.request.query_params:
                if self.request.query_params.get('year') and self.request.query_params.get('month'):
                    try:
                        month_param = int(self.request.query_params['month'])
                        if not month_param in range(1,13):
                            raise ValidationError({"error":"Parámetro Mes debe ser un número entre el 1 y el 12"})

                    except Exception:
                        raise ValidationError({"error_month_param": "Parámetro Mes debe ser un número entre el 1 y el 12"})
                        
                    try: 
                        year_param = int(self.request.query_params['year'])
                        if year_param < 1:
                            raise ValidationError({"error":"Parámetro Mes debe ser un número entre el 1 y el 12"})
                    
                    except Exception:
                        raise ValidationError({"error_year_param": "Año debe ser un número entero positivo"})

                    last_day_month = calendar.monthrange(year_param, month_param)[1]

                    range_evaluate = (datetime(year_param, month_param, 1), datetime(year_param, month_param, last_day_month))
                    queryset = queryset.filter(
                        Q(check_in_date__range=range_evaluate) |
                        Q(check_out_date__range=range_evaluate)
                    )

        return queryset

import os
from django.http import HttpResponse
from pathlib import Path

import calendar
from datetime import datetime

from django.db import transaction
from django.db.models import Q

from rest_framework.views import APIView
from rest_framework import generics, viewsets
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny

from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema

from apps.core.paginator import CustomPagination
from slugify import slugify

from .models import Reservation, RentalReceipt
from .serializers import ReservationSerializer, ReservationListSerializer, ReservationRetrieveSerializer, ReciptSerializer

from apps.accounts.models import CustomUser

from apps.core.functions import get_month_name, generate_audit, check_user_has_rol, confeccion_ics
from apps.dashboard.utils import get_stadistics_period


class ReservationsApiView(viewsets.ModelViewSet):
    serializer_class = ReservationSerializer
    queryset = Reservation.objects.exclude(deleted=True).order_by("check_in_date")
    search_fields = [
        "client__email",
        "client__first_name",
        "client__last_name",
        "property__name"
    ]
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
                
                elif self.request.query_params.get('from') == 'today':
                    queryset = queryset.filter(check_in_date__gte=datetime.now())

                if self.request.query_params.get('type'):
                    queryset = queryset.filter(origin=self.request.query_params.get('type'))

        elif self.action in ['partial_update', 'update', 'destroy']:
            if not check_user_has_rol("admin", self.request.user):
                queryset = queryset.filter(
                    Q(origin="air") |
                    Q(seller=self.request.user)
                )
        if self.request.query_params.get('exclude'):
            queryset = queryset.exclude(origin=self.request.query_params['exclude'])

        return queryset.exclude(deleted=True)

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ReservationRetrieveSerializer
        if self.action == 'list':
            return ReservationListSerializer

        return super().get_serializer_class()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.action == 'retrieve':
            context['retrieve'] = True
        return context


    @extend_schema(
        parameters=[
            OpenApiParameter(
                "year",
                OpenApiTypes.INT,
                required=False,
                description="Filter results by year",
                enum=[2024, 2023, 2022],
            ),
            OpenApiParameter(
                "month",
                OpenApiTypes.INT,
                required=False,
                description="Filter results by month (number 1 to 12)",
                enum=list(range(1,13)),
            ),
            OpenApiParameter(
                "page_size",
                OpenApiTypes.INT,
                description="Enviar page_size=valor para determinar tamaño de la pagina, sino enviar page_size=none para no tener paginado",
                required=False,
            ),
            OpenApiParameter(
                "from",
                OpenApiTypes.STR,
                description="Obtiene todas las reservas desde la fecha de hoy en adelante. Se puede combinar con type (tipo de reserva), pero no con year o month",
                required=False,
                enum=["today"]
            ),
            OpenApiParameter(
                "type",
                OpenApiTypes.STR,
                description="Filtra las resevas según donde se generaron, AriBnB (air), Sistema Casa Austin (aus), Mantenimiento (man)",
                required=False,
                enum=["aus", "air", "man"]
            ),
            OpenApiParameter(
                "type",
                OpenApiTypes.STR,
                description="Excluye las resevas según donde se generaron, AriBnB (air), Sistema Casa Austin (aus), Mantenimiento (man)",
                required=False,
                enum=["aus", "air", "man"]
            ),
        ],
        responses={200: ReservationListSerializer(many=True)},
        methods=["GET"],
    )
    def list(self, request, *args, **kwargs):
        self.pagination_class = self.get_pagination_class()
        return super().list(request, *args, **kwargs)

    def perform_create(self, serializer):
        with transaction.atomic():
            user_seller = self.request.user
            if self.request.POST['origin'].lower() == 'air':
                user_seller = CustomUser.objects.get(first_name='AirBnB')

            serializer.save(seller=user_seller)

            for file in self.request.FILES.getlist('file'):
                RentalReceipt.objects.create(
                    reservation=serializer.instance,
                    file=file
                )
        
        confeccion_ics()

        generate_audit(
            serializer.instance,
            self.request.user,
            "create",
            "Reserva creada"
        )


    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        
        with transaction.atomic():
            self.perform_update(serializer)

            for file in request.FILES.getlist('file'):
                RentalReceipt.objects.create(
                    reservation=instance,
                    file=file
                )
        
        confeccion_ics()

        generate_audit(
            serializer.instance,
            self.request.user,
            "update",
            "Reserva actulizada"
        )
        return Response(serializer.data)
    
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)

        generate_audit(
            instance,
            self.request.user,
            "delete",
            "Reserva eliminada"
        )
        return Response(status=204)
    

class DeleteRecipeApiView(generics.DestroyAPIView):
    queryset = RentalReceipt.objects.all()
    serializer_class = ReciptSerializer


    def get_queryset(self):
        queryset = super().get_queryset()

        return queryset.filter(reservation__seller=self.request.user)

class GetICSApiView(APIView):
    serializer_class = None
    permission_classes = [AllowAny]

    def get(self, request):

        if self.request.query_params:
            if self.request.query_params.get('q'):
                casa_sluged_name = slugify(self.request.query_params.get('q'))


                directory = str(Path(__file__).parent.parent.parent) + "/media/"
                f = open(os.path.join(directory, f'{casa_sluged_name}.ics'), 'rb')

                # Crear una respuesta HTTP con el contenido del archivo .ics
                response = HttpResponse(f, content_type='text/calendar')
                
                # Establecer el encabezado de Content-Disposition para descargar el archivo
                response['Content-Disposition'] = 'attachment; filename="evento.ics"'

        return response
    
class UpdateICSApiView(APIView):
    serializer_class = None

    def get(self, request):
        confeccion_ics()

        return Response({'message':'ok'}, status=200)

class ProfitApiView(APIView):
    serializer_class = None

    def get(self, request):
        rta = {}

        evaluate_year = int(self.request.query_params['year'])
        for m in range(1,13):
            last_day_month = calendar.monthrange(evaluate_year, m)[1]

            _, _, _, _, total_facturado = get_stadistics_period(
                datetime(evaluate_year, m, 1),
                last_day_month
            )
            
            rta[get_month_name(m)] = total_facturado 

        return Response(
            rta,
            status=200
        )    

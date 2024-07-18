import os
from django.http import HttpResponse
from pathlib import Path

import calendar
from datetime import datetime, time, timedelta

from django.db import transaction
from django.db.models import Q

from rest_framework.views import APIView
from rest_framework.decorators import action
from rest_framework import generics, viewsets
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny

from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema

from apps.core.paginator import CustomPagination
from slugify import slugify

from .models import Reservation, RentalReceipt, Clients, Property
from .serializers import ReservationSerializer, ReservationListSerializer, ReservationRetrieveSerializer, ReciptSerializer

from apps.accounts.models import CustomUser

from apps.core.functions import get_month_name, generate_audit, check_user_has_rol, confeccion_ics
from apps.dashboard.utils import get_stadistics_period
from docx import Document
from docx.shared import Pt
import io

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
                from_param = self.request.query_params.get('from')
                type_param = self.request.query_params.get('type')
                now = datetime.now()
                check_in_time = time(15, 0)  # 3 PM
                check_out_time = time(11, 0)  # 11 AM

                if self.request.query_params.get('year') and self.request.query_params.get('month'):
                    try:
                        month_param = int(self.request.query_params['month'])
                        if not month_param in range(1, 13):
                            raise ValidationError({"error": "Parámetro Mes debe ser un número entre el 1 y el 12"})

                    except Exception:
                        raise ValidationError({"error_month_param": "Parámetro Mes debe ser un número entre el 1 y el 12"})

                    try:
                        year_param = int(self.request.query_params['year'])
                        if year_param < 1:
                            raise ValidationError({"error": "Parámetro Año debe ser un número entero positivo"})

                    except Exception:
                        raise ValidationError({"error_year_param": "Año debe ser un número entero positivo"})

                    last_day_month = calendar.monthrange(year_param, month_param)[1]

                    range_evaluate = (datetime(year_param, month_param, 1), datetime(year_param, month_param, last_day_month))

                    if self.request.query_params.get('from_check_in') == 'true':
                        queryset = queryset.filter(check_in_date__range=range_evaluate)
                    else:
                        queryset = queryset.filter(
                            Q(check_in_date__range=range_evaluate) |
                            Q(check_out_date__range=range_evaluate)
                        )

                if from_param == 'today':
                    queryset = queryset.filter(check_in_date__gte=now)
                elif from_param == 'in_progress':
                    # Verificar reservas que están en curso
                    now_time = now.time()
                    today_date = now.date()
                    tomorrow_date = today_date + timedelta(days=1)

                    queryset = queryset.filter(
                        Q(check_in_date__lt=today_date, check_out_date__gt=today_date) |
                        (Q(check_in_date=today_date) & Q(check_out_date__gt=today_date)) |
                        (Q(check_out_date=today_date) & Q(check_out_date__gt=now)) |
                        (Q(check_out_date=tomorrow_date) & Q(check_out_date__gt=datetime.combine(tomorrow_date, check_out_time)))
                    )

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
                enum=list(range(1, 13)),
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
                enum=["today", "in_progress"]
            ),
            OpenApiParameter(
                "from_check_in",
                OpenApiTypes.STR,
                description="Obtiene todas las reservas que hayan comenzado este mes. Se usa en combinacion de los queryparams year y month",
                required=False,
                enum=["true"]
            ),
            OpenApiParameter(
                "type",
                OpenApiTypes.STR,
                description="Filtra las resevas según donde se generaron, AriBnB (air), Sistema Casa Austin (aus), Mantenimiento (man)",
                required=False,
                enum=["aus", "air", "man"]
            ),
            OpenApiParameter(
                "exclude",
                OpenApiTypes.STR,
                description="Excluye las resevas según donde se generaron, AriBnB (air), Sistema Casa Austin (aus), Mantenimiento (man)",
                required=False,
                enum=["aus", "air", "man"]
            ),
            OpenApiParameter(
                name='id',
                description='A numeric ID identifying this reservation.',
                required=True,
                type=OpenApiTypes.INT,
                location=OpenApiParameter.PATH
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

    def perform_update(self, serializer):
        confeccion_ics()

        generate_audit(
            serializer.instance,
            self.request.user,
            "update",
            "Reserva actualizada full"
        )

        return super().perform_update(serializer)

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
            "Reserva actualizada"
        )
        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)

        confeccion_ics()

        generate_audit(
            instance,
            self.request.user,
            "delete",
            "Reserva eliminada"
        )
        return Response(status=204)
###### MOD AUSTIN ######
    @action(detail=True, methods=['get'], url_path='contrato')
    def contrato(self, request, pk=None):
        try:
            reservation = self.get_object()
            client = Clients.objects.get(id=reservation.client_id)
            property = Property.objects.get(id=reservation.property_id)

            # Obtener document_type de clients_clients
            document_type = client.document_type

            # Depuración: Verificar que estamos obteniendo el document_type
            print(f"Document Type: {document_type}")

            # Cargar la plantilla existente
            doc = Document("/srv/casaaustin/api-casa-austin/src/plantilla.docx")

            # Crear el contexto con los datos necesarios
            context = {
                'nombre': f"{client.first_name.upper()} {client.last_name.upper()}",
                'tipodocumento': document_type.upper(),
                'dni': client.number_doc,
                'propiedad': property.name,
                'checkin': reservation.check_in_date.strftime('%d/%m/%Y'),
                'checkout': reservation.check_out_date.strftime('%d/%m/%Y'),
                'preciodolares': f"${reservation.price_usd:.2f}",
                'numpax': str(reservation.guests)
            }

            # Depuración: Verificar el contexto
            print(f"Context: {context}")

            def replace_text(paragraph, key, value):
                # Reemplaza el texto de una variable en un párrafo y agrega el texto reemplazado en negrita
                for run in paragraph.runs:
                    if key in run.text:
                        run.text = run.text.replace(key, value)
                        run.bold = True
                        print(f"Reemplazado {key} con {value} en run: {run.text}")

            def replace_text_in_paragraph(paragraph, context):
                # Reemplazar las variables en el párrafo
                inline = paragraph.runs
                full_text = ''.join(run.text for run in inline)
                for key, value in context.items():
                    if f'{{{key}}}' in full_text:
                        print(f"Reemplazando {key} en el párrafo: {full_text}")  # Depuración
                        for run in inline:
                            replace_text(run, f'{{{key}}}', value)

            # Reemplazar las variables en los párrafos de la plantilla
            for paragraph in doc.paragraphs:
                replace_text_in_paragraph(paragraph, context)

            # Reemplazar las variables en las celdas de las tablas (si hay tablas en la plantilla)
            for table in doc.tables:
                for row in table.rows:
                    for cell in row.cells:
                        for paragraph in cell.paragraphs:
                            replace_text_in_paragraph(paragraph, context)

            # Guardar el documento en un archivo de bytes
            file_stream = io.BytesIO()
            doc.save(file_stream)
            file_stream.seek(0)

            # Preparar la respuesta HTTP
            response = HttpResponse(file_stream.read(), content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
            response['Content-Disposition'] = f'attachment; filename="{property.name}_contract.docx"'
            return response
        except Clients.DoesNotExist:
            return Response({'error': 'Client not found'}, status=404)
        except Property.DoesNotExist:
            return Response({'error': 'Property not found'}, status=404)
        except Exception as e:
            return Response({'error': str(e)}, status=400)
###### FIN MOD #######

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
        return Response({'message': 'ok'}, status=200)


class ProfitApiView(APIView):
    serializer_class = None

    def get(self, request):
        rta = {}

        evaluate_year = int(self.request.query_params['year'])
        for m in range(1, 13):
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

############ Austin MOD ############
class VistaCalendarioApiView(viewsets.ModelViewSet):
    serializer_class = ReservationSerializer
    queryset = Reservation.objects.exclude(deleted=True).order_by("check_in_date")
    search_fields = [
        "client__email",
        "client__first_name",
        "client__last_name",
        "property__name"
    ]
    permission_classes = [AllowAny]
    pagination_class = None  # Desactiva la paginación

    def get_queryset(self):
        queryset = super().get_queryset()

        if self.action == 'list':
            if self.request.query_params:
                from_param = self.request.query_params.get('from')
                type_param = self.request.query_params.get('type')
                now = datetime.now()
                check_in_time = time(15, 0)  # 3 PM
                check_out_time = time(11, 0)  # 11 AM

                if self.request.query_params.get('year') and self.request.query_params.get('month'):
                    try:
                        month_param = int(self.request.query_params['month'])
                        if not month_param in range(1, 13):
                            raise ValidationError({"error": "Parámetro Mes debe ser un número entre el 1 y el 12"})
                    except Exception:
                        raise ValidationError({"error_month_param": "Parámetro Mes debe ser un número entre el 1 y el 12"})

                    try:
                        year_param = int(self.request.query_params['year'])
                        if year_param < 1:
                            raise ValidationError({"error": "Parámetro Año debe ser un número entero positivo"})
                    except Exception:
                        raise ValidationError({"error_year_param": "Año debe ser un número entero positivo"})

                    last_day_month = calendar.monthrange(year_param, month_param)[1]

                    range_evaluate = (datetime(year_param, month_param, 1), datetime(year_param, month_param, last_day_month))

                    if self.request.query_params.get('from_check_in') == 'true':
                        queryset = queryset.filter(check_in_date__range=range_evaluate)
                    else:
                        queryset = queryset.filter(
                            Q(check_in_date__range=range_evaluate) |
                            Q(check_out_date__range=range_evaluate)
                        )

                if from_param == 'today':
                    queryset = queryset.filter(check_in_date__gte=now)
                elif from_param == 'in_progress':
                    now_time = now.time()
                    today_date = now.date()
                    tomorrow_date = today_date + timedelta(days=1)

                    queryset = queryset.filter(
                        Q(check_in_date__lt=today_date, check_out_date__gt=today_date) |
                        (Q(check_in_date=today_date) & Q(check_out_date__gt=today_date)) |
                        (Q(check_out_date=today_date) & Q(check_out_date__gt=now)) |
                        (Q(check_out_date=tomorrow_date) & Q(check_out_date__gt=datetime.combine(tomorrow_date, check_out_time)))
                    )

                if type_param:
                    queryset = queryset.filter(origin=type_param)

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
                enum=list(range(1, 13)),
            ),
            OpenApiParameter(
                "from",
                OpenApiTypes.STR,
                description="Obtiene todas las reservas desde la fecha de hoy en adelante. Se puede combinar con type (tipo de reserva), pero no con year o month",
                required=False,
                enum=["today", "in_progress"]
            ),
            OpenApiParameter(
                "from_check_in",
                OpenApiTypes.STR,
                description="Obtiene todas las reservas que hayan comenzado este mes. Se usa en combinacion de los queryparams year y month",
                required=False,
                enum=["true"]
            ),
            OpenApiParameter(
                "type",
                OpenApiTypes.STR,
                description="Filtra las resevas según donde se generaron, AriBnB (air), Sistema Casa Austin (aus), Mantenimiento (man)",
                required=False,
                enum=["aus", "air", "man"]
            ),
            OpenApiParameter(
                "exclude",
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
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

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

    def perform_update(self, serializer):
        confeccion_ics()

        generate_audit(
            serializer.instance,
            self.request.user,
            "update",
            "Reserva actualizada full"
        )

        return super().perform_update(serializer)

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
            "Reserva actualizada"
        )
        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)

        confeccion_ics()

        generate_audit(
            instance,
            self.request.user,
            "delete",
            "Reserva eliminada"
        )
        return Response(status=204)
    
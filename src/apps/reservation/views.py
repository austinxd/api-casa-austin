import os
from django.http import HttpResponse
from pathlib import Path

import calendar
from datetime import datetime, time, timedelta

from django.db import transaction
from django.db.models import Q

from rest_framework.views import APIView
from rest_framework.decorators import action
from rest_framework import generics, viewsets, serializers
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
import subprocess
from docxtpl import DocxTemplate
from babel.dates import format_date
import io
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django.utils.timezone import now
from .signals import send_purchase_event_to_meta
from django.views.decorators.csrf import csrf_exempt
import json
from django.http import JsonResponse, HttpResponseBadRequest

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
            
            instance = serializer.save(seller=user_seller)
            if instance.late_checkout:
                original_check_out_date = instance.check_out_date
                instance.late_check_out_date = original_check_out_date
                instance.check_out_date = original_check_out_date + timedelta(days=1)
            else:
                instance.late_check_out_date = None
            instance.save()

            for file in self.request.FILES.getlist('file'):
                RentalReceipt.objects.create(
                    reservation=instance,
                    file=file
                )

        confeccion_ics()

        generate_audit(
            instance,
            self.request.user,
            "create",
            "Reserva creada"
        )

    def perform_update(self, serializer):
        with transaction.atomic():
            instance = self.get_object()
            original_late_checkout = instance.late_checkout
            original_check_out_date = instance.check_out_date
            instance = serializer.save()

            if instance.late_checkout and not original_late_checkout:
                instance.late_check_out_date = original_check_out_date
                instance.check_out_date = original_check_out_date + timedelta(days=1)
            elif not instance.late_checkout and original_late_checkout:
                instance.check_out_date = instance.late_check_out_date
                instance.late_check_out_date = None
            instance.save()

            confeccion_ics()

            generate_audit(
                instance,
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
            original_late_checkout = instance.late_checkout
            original_check_out_date = instance.check_out_date
            instance = serializer.save()

            if instance.late_checkout and not original_late_checkout:
                instance.late_check_out_date = original_check_out_date
                instance.check_out_date = original_check_out_date + timedelta(days=1)
            elif not instance.late_checkout and original_late_checkout:
                instance.check_out_date = instance.late_check_out_date
                instance.late_check_out_date = None
            instance.save()

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

###### MOD AUSTIN #######
    @action(detail=True, methods=['get'], url_path='contrato')
    def contrato(self, request, pk=None):
        try:
            reservation = self.get_object()
            client = Clients.objects.get(id=reservation.client_id)
            property = Property.objects.get(id=reservation.property_id)

            document_type_map = {
                'pas': 'pasaporte',
                'cex': 'carnet de extranjería',
                'dni': 'DNI'
            }

            document_type = document_type_map.get(client.document_type, None)
            if document_type is None:
                raise ValueError(f"Tipo de documento desconocido: {client.document_type}")

            checkin_date = format_date(reservation.check_in_date, format="d 'de' MMMM 'del' YYYY", locale='es')
            checkout_date = format_date(reservation.check_out_date, format="d 'de' MMMM 'del' YYYY", locale='es')

            doc = DocxTemplate("/srv/casaaustin/api-casa-austin/src/plantilla.docx")

            context = {
                'nombre': f"{client.first_name.upper()} {client.last_name.upper()}",
                'tipodocumento': document_type.upper(),
                'dni': client.number_doc,
                'propiedad': property.name,
                'checkin': checkin_date,
                'checkout': checkout_date,
                'preciodolares': f"${reservation.price_usd:.2f}",
                'numpax': str(reservation.guests)
            }

            doc.render(context)

            temp_doc_path = "/tmp/temp_contract.docx"
            temp_pdf_path = "/tmp/temp_contract.pdf"
            doc.save(temp_doc_path)

            subprocess.run(['libreoffice', '--headless', '--convert-to', 'pdf', '--outdir', '/tmp', temp_doc_path], check=True)

            with open(temp_pdf_path, "rb") as pdf_file:
                pdf_data = pdf_file.read()

            response = HttpResponse(pdf_data, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="{property.name}_contract.pdf"'

            os.remove(temp_doc_path)
            os.remove(temp_pdf_path)

            return response
        except Clients.DoesNotExist:
            return Response({'error': 'Client not found'}, status=404)
        except Property.DoesNotExist:
            return Response({'error': 'Property not found'}, status=404)
        except ValueError as e:
            return Response({'error': str(e)}, status=400)
        except subprocess.CalledProcessError as e:
            return Response({'error': 'Error converting DOCX to PDF'}, status=500)
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

            _, _, _, _, _, total_facturado = get_stadistics_period(
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

                # Modificación: Manejo del parámetro 'year' sin depender de 'month'
                year_param = self.request.query_params.get('year')
                month_param = self.request.query_params.get('month')

                if year_param:
                    try:
                        year_param = int(year_param)
                        if year_param < 1:
                            raise ValidationError({"error": "El parámetro 'year' debe ser un número entero positivo"})
                    except ValueError:
                        raise ValidationError({"error": "El parámetro 'year' debe ser un número válido"})

                    if month_param:
                        # Si 'month' también está presente
                        try:
                            month_param = int(month_param)
                            if month_param not in range(1, 13):
                                raise ValidationError({"error": "El parámetro 'month' debe ser un número entre 1 y 12"})
                        except ValueError:
                            raise ValidationError({"error": "El parámetro 'month' debe ser un número válido"})

                        # Filtrar por año y mes específico
                        last_day_month = calendar.monthrange(year_param, month_param)[1]
                        range_evaluate = (datetime(year_param, month_param, 1), datetime(year_param, month_param, last_day_month))

                        queryset = queryset.filter(
                            Q(check_in_date__range=range_evaluate) |
                            Q(check_out_date__range=range_evaluate)
                        )
                    else:
                        # Solo filtrar por año completo
                        start_of_year = datetime(year_param, 1, 1)
                        end_of_year = datetime(year_param, 12, 31)
                        queryset = queryset.filter(
                            Q(check_in_date__range=(start_of_year, end_of_year)) |
                            Q(check_out_date__range=(start_of_year, end_of_year))
                        )

                # Otros filtros existentes
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

            instance = serializer.save(seller=user_seller)
            if instance.late_checkout:
                original_check_out_date = instance.check_out_date - timedelta(days=1)
                instance.late_check_out_date = original_check_out_date
                instance.check_out_date = original_check_out_date + timedelta(days=1)
                instance.save()

            for file in self.request.FILES.getlist('file'):
                RentalReceipt.objects.create(
                    reservation=instance,
                    file=file
                )

        confeccion_ics()

        generate_audit(
            instance,
            self.request.user,
            "create",
            "Reserva creada"
        )

    def perform_update(self, serializer):
        with transaction.atomic():
            instance = serializer.save()
            if instance.late_checkout:
                if instance.late_check_out_date is None:
                    original_check_out_date = instance.check_out_date - timedelta(days=1)
                    instance.late_check_out_date = original_check_out_date
                    instance.check_out_date = original_check_out_date + timedelta(days=1)
                instance.save()

            confeccion_ics()

            generate_audit(
                instance,
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
        instance = serializer.save()
        if instance.late_checkout:
            if instance.late_check_out_date is None:
                original_check_out_date = instance.check_out_date - timedelta(days=1)
                instance.late_check_out_date = original_check_out_date
                instance.check_out_date = original_check_out_date + timedelta(days=1)
            instance.save()

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

@csrf_exempt
def confirm_reservation(request, uuid):
    if request.method != "POST":
        return HttpResponseBadRequest("Método no permitido")

    # Buscar reserva por ID o uuid_external (sin guiones)
    try:
        reservation = Reservation.objects.get(id=uuid)
    except Reservation.DoesNotExist:
        uuid_clean = uuid.replace("-", "")
        reservation = get_object_or_404(Reservation, uuid_external=uuid_clean)

    # Intentar leer JSON, sino usar POST clásico
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        data = request.POST

    # Obtener IP real del cliente (considerando proxy)
    ip = request.META.get("HTTP_X_FORWARDED_FOR")
    if ip:
        ip = ip.split(",")[0]
    else:
        ip = request.META.get("REMOTE_ADDR")

    # Guardar datos de navegación
    reservation.ip_cliente = ip
    reservation.user_agent = request.META.get("HTTP_USER_AGENT", "")
    reservation.referer = request.META.get("HTTP_REFERER", "")
    reservation.fbclid = data.get("fbclid", "")
    reservation.utm_source = data.get("utm_source", "")
    reservation.utm_medium = data.get("utm_medium", "")
    reservation.utm_campaign = data.get("utm_campaign", "")
    reservation.fbc = data.get("fbc", "")
    reservation.fbp = data.get("fbp", "")
    reservation.save()

    # Enviar a Meta
    send_purchase_event_to_meta(
        phone=reservation.client.tel_number,
        email=reservation.client.email,
        first_name=reservation.client.first_name,
        last_name=reservation.client.last_name,
        amount=reservation.price_usd,
        currency="USD",
        ip=reservation.ip_cliente,
        user_agent=reservation.user_agent,
        fbc=reservation.fbc,
        fbp=reservation.fbp,
        fbclid=reservation.fbclid,
        utm_source=reservation.utm_source,
        utm_medium=reservation.utm_medium,
        utm_campaign=reservation.utm_campaign,
        birthday=str(reservation.client.date) if reservation.client.date else None  # <-- aquí

    )

    return JsonResponse({"message": "✅ ¡Reserva confirmada correctamente!"})
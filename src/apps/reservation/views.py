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
from .serializers import ReservationSerializer, ReservationListSerializer, ReservationRetrieveSerializer, ClientReservationSerializer, CalendarReservationSerializer, ReciptSerializer

from apps.core.paginator import CustomPagination
from slugify import slugify

from .models import Reservation, RentalReceipt, Clients, Property

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

                elif from_param == 'pending':
                    queryset = queryset.filter(status__in=['pending', 'under_review'])

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
                enum=["today", "in_progress", "pending"]
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

            # Las reservas creadas por admin/vendedores están aprobadas por defecto
            instance = serializer.save(seller=user_seller, status='approved')
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

            # Solo guardar si realmente hay cambios en late checkout
            if instance.late_checkout and not original_late_checkout:
                instance.late_check_out_date = original_check_out_date
                instance.check_out_date = original_check_out_date + timedelta(days=1)
                instance.save(update_fields=['late_check_out_date', 'check_out_date'])
            elif not instance.late_checkout and original_late_checkout:
                instance.check_out_date = instance.late_check_out_date
                instance.late_check_out_date = None
                instance.save(update_fields=['check_out_date', 'late_check_out_date'])

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

            # Solo guardar si realmente hay cambios en late checkout
            if instance.late_checkout and not original_late_checkout:
                instance.late_check_out_date = original_check_out_date
                instance.check_out_date = original_check_out_date + timedelta(days=1)
                instance.save(update_fields=['late_check_out_date', 'check_out_date'])
            elif not instance.late_checkout and original_late_checkout:
                instance.check_out_date = instance.late_check_out_date
                instance.late_check_out_date = None
                instance.save(update_fields=['check_out_date', 'late_check_out_date'])

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
    serializer_class = CalendarReservationSerializer # Usar el nuevo serializer ligero
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

                # Aquí se debe agregar el filtro para 'pending'
                if from_param == 'pending':
                    queryset = queryset.filter(status='pending')

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
            return CalendarReservationSerializer

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
                enum=["today", "in_progress", "pending"]
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

            # Para reservas de cliente, establecer status pending y deadline
            status = 'approved'
            if self.request.POST.get('origin', '').lower() == 'client':
                status = 'pending'

            instance = serializer.save(seller=user_seller, status=status)

            # Si es reserva de cliente, establecer deadline de 1 hora
            if instance.origin == 'client':
                from django.utils import timezone
                instance.payment_voucher_deadline = timezone.now() + timedelta(hours=1)
                instance.save()
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


class MonthlyReservationsExportAPIView(APIView):
    """
    Endpoint para exportar datos de reservas por mes
    """
    permission_classes = [AllowAny]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "year",
                OpenApiTypes.INT,
                required=True,
                description="Año de las reservas a exportar",
                location=OpenApiParameter.QUERY
            ),
            OpenApiParameter(
                "month",
                OpenApiTypes.INT,
                required=True,
                description="Mes de las reservas a exportar (1-12)",
                location=OpenApiParameter.QUERY
            ),
        ],
        responses={
            200: {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "data": {
                        "type": "object",
                        "properties": {
                            "period": {"type": "string"},
                            "total_reservations": {"type": "integer"},
                            "reservations": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "id": {"type": "integer"},
                                        "client_name": {"type": "string"},
                                        "client_email": {"type": "string"},
                                        "client_phone": {"type": "string"},
                                        "property_name": {"type": "string"},
                                        "check_in_date": {"type": "string", "format": "date"},
                                        "check_out_date": {"type": "string", "format": "date"},
                                        "guests": {"type": "integer"},
                                        "price_usd": {"type": "number"},
                                        "price_sol": {"type": "number"},
                                        "advance_payment": {"type": "number"},
                                        "advance_payment_currency": {"type": "string"},
                                        "full_payment": {"type": "boolean"},
                                        "temperature_pool": {"type": "boolean"},
                                        "origin": {"type": "string"},
                                        "status": {"type": "string"},
                                        "seller_name": {"type": "string"},
                                        "created": {"type": "string", "format": "date-time"},
                                        "number_nights": {"type": "integer"},
                                        "points_redeemed": {"type": "number"},
                                        "discount_code_used": {"type": "string"}
                                    }
                                }
                            }
                        }
                    }
                }
            },
            400: {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "error": {"type": "string"}
                }
            }
        }
    )
    def get(self, request):
        try:
            # Validar parámetros requeridos
            year_param = request.query_params.get('year')
            month_param = request.query_params.get('month')

            if not year_param or not month_param:
                return Response({
                    "success": False,
                    "error": "Los parámetros 'year' y 'month' son requeridos"
                }, status=400)

            # Validar año
            try:
                year = int(year_param)
                if year < 2020 or year > 2030:
                    raise ValueError()
            except ValueError:
                return Response({
                    "success": False,
                    "error": "El parámetro 'year' debe ser un número válido entre 2020 y 2030"
                }, status=400)

            # Validar mes
            try:
                month = int(month_param)
                if month < 1 or month > 12:
                    raise ValueError()
            except ValueError:
                return Response({
                    "success": False,
                    "error": "El parámetro 'month' debe ser un número entre 1 y 12"
                }, status=400)

            # Calcular rango de fechas para el mes
            last_day_month = calendar.monthrange(year, month)[1]
            start_date = datetime(year, month, 1).date()
            end_date = datetime(year, month, last_day_month).date()

            # Obtener reservas del mes
            reservations = Reservation.objects.filter(
                check_in_date__gte=start_date,
                check_in_date__lte=end_date,
                deleted=False
            ).select_related('client', 'property', 'seller').order_by('check_in_date')

            # Formatear datos de reservas
            reservations_data = []
            for reservation in reservations:
                # Calcular número de noches
                if reservation.check_in_date and reservation.check_out_date:
                    delta = reservation.check_out_date - reservation.check_in_date
                    number_nights = delta.days
                else:
                    number_nights = 0

                # Formatear nombre del cliente
                client_name = ""
                client_email = ""
                client_phone = ""
                if reservation.client:
                    first_name = reservation.client.first_name or ""
                    last_name = reservation.client.last_name or ""
                    client_name = f"{first_name} {last_name}".strip()
                    client_email = reservation.client.email or ""
                    client_phone = reservation.client.tel_number or ""

                # Formatear nombre del vendedor
                seller_name = ""
                if reservation.seller:
                    seller_first = reservation.seller.first_name or ""
                    seller_last = reservation.seller.last_name or ""
                    seller_name = f"{seller_first} {seller_last}".strip()

                # Mapear status para mejor legibilidad
                status_mapping = {
                    'approved': 'Aprobada',
                    'pending': 'Pendiente',
                    'incomplete': 'Incompleta',
                    'rejected': 'Rechazada',
                    'cancelled': 'Cancelada'
                }
                status_display = status_mapping.get(reservation.status, reservation.status)

                # Mapear origen para mejor legibilidad
                origin_mapping = {
                    'air': 'Airbnb',
                    'aus': 'Austin',
                    'man': 'Mantenimiento',
                    'client': 'Cliente Web'
                }
                origin_display = origin_mapping.get(reservation.origin, reservation.origin)

                reservations_data.append({
                    "id": reservation.id,
                    "client_name": client_name,
                    "client_email": client_email,
                    "client_phone": client_phone,
                    "property_name": reservation.property.name if reservation.property else "",
                    "check_in_date": reservation.check_in_date.strftime('%Y-%m-%d'),
                    "check_out_date": reservation.check_out_date.strftime('%Y-%m-%d'),
                    "guests": reservation.guests,
                    "price_usd": float(reservation.price_usd or 0),
                    "price_sol": float(reservation.price_sol or 0),
                    "advance_payment": float(reservation.advance_payment or 0),
                    "advance_payment_currency": reservation.advance_payment_currency,
                    "full_payment": reservation.full_payment,
                    "temperature_pool": reservation.temperature_pool,
                    "origin": origin_display,
                    "status": status_display,
                    "seller_name": seller_name,
                    "created": reservation.created.isoformat() if reservation.created else "",
                    "number_nights": number_nights,
                    "points_redeemed": float(reservation.points_redeemed or 0),
                    "discount_code_used": reservation.discount_code_used or "",
                    "tel_contact_number": reservation.tel_contact_number or "",
                    "comentarios_reservas": reservation.comentarios_reservas or ""
                })

            # Formatear nombre del período
            month_names = {
                1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril',
                5: 'Mayo', 6: 'Junio', 7: 'Julio', 8: 'Agosto',
                9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre'
            }
            period_name = f"{month_names[month]} {year}"

            return Response({
                "success": True,
                "data": {
                    "period": period_name,
                    "total_reservations": len(reservations_data),
                    "reservations": reservations_data
                }
            })

        except Exception as e:
            return Response({
                "success": False,
                "error": f"Error interno del servidor: {str(e)}"
            }, status=500)


class PropertyCalendarOccupancyAPIView(APIView):
    """
    Endpoint para obtener la ocupación del calendario de una propiedad
    """
    permission_classes = [AllowAny]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "year",
                OpenApiTypes.INT,
                required=True,
                description="Año para filtrar las reservas",
                location=OpenApiParameter.QUERY
            ),
            OpenApiParameter(
                "month",
                OpenApiTypes.INT,
                required=False,
                description="Mes para filtrar las reservas (1-12). Si no se envía, devuelve todo el año",
                location=OpenApiParameter.QUERY
            ),
            OpenApiParameter(
                "day",
                OpenApiTypes.INT,
                required=False,
                description="Día para filtrar las reservas (1-31). Requiere que se especifique el mes",
                location=OpenApiParameter.QUERY
            ),
        ],
        responses={
            200: {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "data": {
                        "type": "object",
                        "properties": {
                            "property_id": {"type": "string"},
                            "occupancy": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "start_date": {"type": "string", "format": "date"},
                                        "end_date": {"type": "string", "format": "date"},
                                        "guest_name": {"type": "string"},
                                        "status": {"type": "string", "enum": ["confirmed", "pending", "incomplete"]},
                                        "reservation_id": {"type": "string"}
                                    }
                                }
                            }
                        }
                    }
                }
            },
            404: {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "error": {"type": "string"}
                }
            }
        }
    )
    def get(self, request, property_id):
        try:
            # Buscar propiedad por ID o slug
            try:
                if property_id.isdigit():
                    property_obj = Property.objects.get(id=property_id, deleted=False)
                else:
                    property_obj = Property.objects.get(slug=property_id, deleted=False)
            except Property.DoesNotExist:
                return Response({
                    "success": False,
                    "error": "Propiedad no encontrada"
                }, status=404)

            # Validar parámetros
            year_param = request.query_params.get('year')
            month_param = request.query_params.get('month')
            day_param = request.query_params.get('day')

            if not year_param:
                return Response({
                    "success": False,
                    "error": "El parámetro 'year' es requerido"
                }, status=400)

            try:
                year = int(year_param)
                if year < 1:
                    raise ValueError()
            except ValueError:
                return Response({
                    "success": False,
                    "error": "El parámetro 'year' debe ser un número entero positivo"
                }, status=400)

            if month_param:
                try:
                    month = int(month_param)
                    if month < 1 or month > 12:
                        raise ValueError()
                except ValueError:
                    return Response({
                        "success": False,
                        "error": "El parámetro 'month' debe ser un número entre 1 y 12"
                    }, status=400)

            if day_param:
                if not month_param:
                    return Response({
                        "success": False,
                        "error": "El parámetro 'day' requiere que también se especifique 'month'"
                    }, status=400)

                try:
                    day = int(day_param)
                    if day < 1 or day > 31:
                        raise ValueError()

                    # Validar que el día sea válido para el mes y año especificados
                    max_day = calendar.monthrange(year, month)[1]
                    if day > max_day:
                        return Response({
                            "success": False,
                            "error": f"El día {day} no es válido para {month}/{year}. El mes tiene {max_day} días"
                        }, status=400)

                except ValueError:
                    return Response({
                        "success": False,
                        "error": "El parámetro 'day' debe ser un número entre 1 y 31"
                    }, status=400)

            # Construir filtro de fechas
            if day_param:
                # Filtrar por día específico
                start_date = datetime(year, month, day).date()
                end_date = datetime(year, month, day).date()
            elif month_param:
                # Filtrar por mes específico
                last_day_month = calendar.monthrange(year, month)[1]
                start_date = datetime(year, month, 1).date()
                end_date = datetime(year, month, last_day_month).date()
            else:
                # Filtrar por todo el año
                start_date = datetime(year, 1, 1).date()
                end_date = datetime(year, 12, 31).date()

            # Obtener reservas de la propiedad en el rango de fechas
            reservations = Reservation.objects.filter(
                property=property_obj,
                deleted=False,
                status__in=['approved', 'pending', 'incomplete']
            ).filter(
                Q(check_in_date__lte=end_date) & Q(check_out_date__gte=start_date)
            ).select_related('client').order_by('check_in_date')

            # Formatear datos de ocupación
            occupancy_data = []
            for reservation in reservations:
                # Formatear nombre del huésped
                if reservation.client:
                    first_name = reservation.client.first_name or ""
                    last_name = reservation.client.last_name or ""

                    # Crear formato con primer nombre e inicial del primer apellido
                    if first_name and last_name:
                        # Obtener solo el primer nombre y la inicial del primer apellido
                        primer_nombre = first_name.split()[0] if first_name else ""
                        guest_name = f"{primer_nombre} {last_name[0]}."
                    elif first_name:
                        primer_nombre = first_name.split()[0] if first_name else ""
                        guest_name = primer_nombre
                    elif last_name:
                        guest_name = f"{last_name[0]}."
                    else:
                        guest_name = "Cliente sin nombre"
                else:
                    guest_name = "Cliente sin datos"

                # Mapear status
                status_mapping = {
                    'approved': 'confirmed',
                    'pending': 'pending',
                    'incomplete': 'incomplete',
                    'rejected': 'rejected',
                    'cancelled': 'cancelled'
                }

                status = status_mapping.get(reservation.status, reservation.status)

                occupancy_data.append({
                    "start_date": reservation.check_in_date.strftime('%Y-%m-%d'),
                    "end_date": reservation.check_out_date.strftime('%Y-%m-%d'),
                    "guest_name": guest_name,
                    "status": status,
                    "reservation_id": str(reservation.id),
                    "origin": reservation.origin
                })

            return Response({
                "success": True,
                "data": {
                    "property_id": property_obj.slug or str(property_obj.id),
                    "occupancy": occupancy_data
                }
            })

        except Exception as e:
            return Response({
                "success": False,
                "error": f"Error interno del servidor: {str(e)}"
            }, status=500)


class QRReservationView(APIView):
    """
    Endpoint público para mostrar los datos de una reserva por su ID.
    Útil para códigos QR en recepción.
    """
    permission_classes = [AllowAny]
    
    def get(self, request, reservation_id):
        """
        Obtiene los datos de una reserva específica por su ID.
        """
        try:
            # Buscar la reserva por ID
            reservation = Reservation.objects.select_related('client', 'property').get(
                id=reservation_id,
                deleted=False
            )
            
            # Preparar datos del cliente
            client = reservation.client
            client_data = {
                "name": None,
                "facebook_photo": None,
                "facebook_link": False,
                "referral_code": None,
                "level": None,
                "level_icon": None,
                "referral_discount_percentage": None,
                "property_name": reservation.property.name
            }
            
            if client:
                # Nombre del cliente
                client_data["name"] = f"{client.first_name or ''} {client.last_name or ''}".strip() or "Cliente sin nombre"
                
                # Datos de Facebook
                if client.facebook_linked and client.facebook_profile_data:
                    client_data["facebook_photo"] = client.get_facebook_profile_picture()
                    client_data["facebook_link"] = True
                else:
                    client_data["facebook_link"] = False
                
                # Código de referido
                client_data["referral_code"] = client.get_referral_code() if hasattr(client, 'get_referral_code') else client.referral_code
                
                # Obtener nivel del cliente (achievement más alto)
                from apps.clients.models import ClientAchievement
                highest_achievement = ClientAchievement.objects.filter(
                    client=client,
                    deleted=False
                ).select_related('achievement').order_by(
                    '-achievement__required_reservations',
                    '-achievement__required_referrals',
                    '-achievement__required_referral_reservations'
                ).first()
                
                if highest_achievement:
                    client_data["level"] = highest_achievement.achievement.name
                    client_data["level_icon"] = highest_achievement.achievement.icon
                    
                    # Obtener descuento por referido de este nivel
                    from apps.property.models import ReferralDiscountByLevel
                    referral_discount = ReferralDiscountByLevel.objects.filter(
                        achievement=highest_achievement.achievement,
                        is_active=True,
                        deleted=False
                    ).first()
                    
                    if referral_discount:
                        client_data["referral_discount_percentage"] = float(referral_discount.discount_percentage)
            
            return Response({
                "success": True,
                "data": client_data
            })
            
        except Reservation.DoesNotExist:
            return Response({
                "success": False,
                "error": "Reserva no encontrada"
            }, status=404)
        except Exception as e:
            return Response({
                "success": False,
                "error": f"Error interno: {str(e)}"
            }, status=500)


class ActiveReservationsView(APIView):
    """
    GET /api/v1/active/
    Devuelve todas las reservas activas en este momento.
    Valida horarios de check-in (12 PM) y check-out (11 AM) en horario de Perú.
    """
    permission_classes = [AllowAny]
    
    def get(self, request):
        try:
            from django.utils import timezone
            
            # Obtener hora actual en horario de Perú
            local_now = timezone.localtime(timezone.now())
            now_date = local_now.date()
            now_time = local_now.time()
            
            checkin_time = time(12, 0)  # 12 PM (mediodía)
            checkout_time = time(11, 0)  # 11 AM
            
            # Obtener todas las reservas aprobadas que podrían estar activas
            reservations = Reservation.objects.filter(
                deleted=False,
                status='approved',
                check_in_date__lte=now_date,  # Ya empezó o empieza hoy
                check_out_date__gte=now_date   # No ha terminado o termina hoy
            ).select_related('property', 'client')
            
            active_reservations = []
            
            for res in reservations:
                # Verificar si la reserva está activa en este momento
                is_active = True
                
                # Si es el día de check-in, debe ser después de las 12 PM
                if now_date == res.check_in_date and now_time < checkin_time:
                    is_active = False
                
                # Si es el día de check-out, debe ser antes de las 11 AM
                if now_date == res.check_out_date and now_time >= checkout_time:
                    is_active = False
                
                # Si está fuera del rango de fechas
                if now_date < res.check_in_date or now_date > res.check_out_date:
                    is_active = False
                
                if is_active:
                    client = res.client
                    
                    active_reservations.append({
                        'id': str(res.id),
                        'property': res.property.name if res.property else 'Sin propiedad',
                        'property_id': res.property.player_id if res.property else None,
                        'client_name': f"{client.first_name or ''} {client.last_name or ''}".strip() or "Sin nombre",
                        'referral_code': client.get_referral_code() if hasattr(client, 'get_referral_code') else client.referral_code,
                        'check_in_date': res.check_in_date.isoformat(),
                        'check_out_date': res.check_out_date.isoformat(),
                        'is_currently_active': True
                    })
            
            return Response({
                "success": True,
                "count": len(active_reservations),
                "active_reservations": active_reservations
            })
            
        except Exception as e:
            return Response({
                "success": False,
                "error": f"Error interno: {str(e)}"
            }, status=500)
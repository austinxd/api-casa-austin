import calendar
from datetime import datetime

from django.db import transaction
from django.db.models import Q

from rest_framework import generics, viewsets
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError

from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema

from .models import Reservation, RentalReceipt
from .serializers import ReservationSerializer, ReservationListSerializer, ReservationRetrieveSerializer, ReciptSerializer


class ReservationsApiView(viewsets.ModelViewSet):
    serializer_class = ReservationSerializer
    queryset = Reservation.objects.all().order_by("created")

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
                            raise ValidationError({"error":"Month param must be a number between 1-12"})

                    except Exception:
                        raise ValidationError({"error_month_param": "Month param must be a number between 1-12"})
                        
                    try: 
                        year_param = int(self.request.query_params['year'])
                        if year_param < 1:
                            raise ValidationError({"error":"Month param must be a number between 1-12"})
                    
                    except Exception:
                        raise ValidationError({"error_year_param": "Year param must be a postive integer number"})

                    last_day_month = calendar.monthrange(year_param, month_param)[1]

                    range_evaluate = (datetime(year_param, month_param, 1), datetime(year_param, month_param, last_day_month))
                    queryset = queryset.filter(
                        Q(check_in_date__range=range_evaluate) |
                        Q(check_out_date__range=range_evaluate)
                    )

        return queryset

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
        ],
        responses={200: ReservationListSerializer(many=True)},
        methods=["GET"],
    )
    def list(self, request):
        return super().list(request)

    def perform_create(self, serializer):
        with transaction.atomic():
            serializer.save(seller=self.request.user)

            for file in self.request.FILES.getlist('file'):
                RentalReceipt.objects.create(
                    reservation=serializer.instance,
                    file=file
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
        
        return Response(serializer.data)
    
class DeleteRecipeApiView(generics.DestroyAPIView):
    queryset = RentalReceipt.objects.all()
    serializer_class = ReciptSerializer

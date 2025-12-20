from datetime import date
from django.utils import timezone
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from drf_spectacular.utils import extend_schema, OpenApiParameter

from apps.reservation.models import Reservation
from apps.property.models import Property
from .models import TVDevice, TVSession
from .serializers import (
    TVSessionResponseSerializer,
    TVHeartbeatSerializer,
    TVCheckoutSerializer,
    TVGuestSerializer,
    TVPropertySerializer
)


class TVSessionView(APIView):
    """
    Get the current active session for a TV device.

    Returns guest information if there's an active reservation,
    or indicates no active session (standby mode).
    """
    permission_classes = [AllowAny]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name='room_id',
                type=str,
                location=OpenApiParameter.PATH,
                description='Unique room/TV identifier'
            )
        ],
        responses={200: TVSessionResponseSerializer}
    )
    def get(self, request, room_id):
        """Get current session for a TV device."""

        # Find TV device by room_id
        try:
            tv_device = TVDevice.objects.select_related('property').get(
                room_id=room_id,
                is_active=True
            )
        except TVDevice.DoesNotExist:
            # If no TV device exists, try to find property directly by room_id
            # This allows using property ID as room_id for simpler setup
            try:
                property_obj = Property.objects.get(id=room_id, deleted=False)
            except (Property.DoesNotExist, ValueError):
                return Response(
                    {'active': False, 'message': 'Device not found'},
                    status=status.HTTP_404_NOT_FOUND
                )

            # Create a virtual TV device for this property
            tv_device = None
            property_for_search = property_obj
        else:
            property_for_search = tv_device.property

        # Find active reservation for this property
        today = date.today()

        active_reservation = Reservation.objects.select_related(
            'client', 'property'
        ).filter(
            property=property_for_search,
            check_in_date__lte=today,
            check_out_date__gte=today,
            status__in=['approved', 'pending'],
            deleted=False
        ).order_by('-check_in_date').first()

        if active_reservation and active_reservation.client:
            # Active session with guest
            serializer_context = {'request': request}
            response_data = {
                'active': True,
                'guest': TVGuestSerializer(active_reservation.client).data,
                'check_in_date': active_reservation.check_in_date,
                'check_out_date': active_reservation.check_out_date,
                'property': TVPropertySerializer(active_reservation.property, context=serializer_context).data,
                'message': None
            }

            # Log check-in event if TV device exists
            if tv_device:
                TVSession.objects.create(
                    tv_device=tv_device,
                    reservation=active_reservation,
                    event_type=TVSession.EventType.CHECK_IN
                )
        else:
            # No active session - standby mode
            serializer_context = {'request': request}
            response_data = {
                'active': False,
                'guest': None,
                'check_in_date': None,
                'check_out_date': None,
                'property': TVPropertySerializer(property_for_search, context=serializer_context).data if property_for_search else None,
                'message': 'No active session'
            }

        return Response(response_data, status=status.HTTP_200_OK)


class TVHeartbeatView(APIView):
    """
    Send a heartbeat from TV device to indicate it's still active.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name='room_id',
                type=str,
                location=OpenApiParameter.PATH,
                description='Unique room/TV identifier'
            )
        ],
        request=TVHeartbeatSerializer,
        responses={200: {'type': 'object', 'properties': {'status': {'type': 'string'}}}}
    )
    def post(self, request, room_id):
        """Record a heartbeat from TV device."""

        try:
            tv_device = TVDevice.objects.get(room_id=room_id, is_active=True)
        except TVDevice.DoesNotExist:
            return Response(
                {'status': 'ok', 'message': 'Device not registered'},
                status=status.HTTP_200_OK
            )

        # Update last heartbeat
        tv_device.last_heartbeat = timezone.now()
        tv_device.save(update_fields=['last_heartbeat'])

        # Log heartbeat event
        serializer = TVHeartbeatSerializer(data=request.data)
        if serializer.is_valid():
            TVSession.objects.create(
                tv_device=tv_device,
                event_type=TVSession.EventType.HEARTBEAT,
                event_data=serializer.validated_data
            )

        return Response({'status': 'ok'}, status=status.HTTP_200_OK)


class TVCheckoutView(APIView):
    """
    Signal checkout from TV device.
    This clears the session and returns TV to standby mode.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name='room_id',
                type=str,
                location=OpenApiParameter.PATH,
                description='Unique room/TV identifier'
            )
        ],
        request=TVCheckoutSerializer,
        responses={200: {'type': 'object', 'properties': {'status': {'type': 'string'}}}}
    )
    def post(self, request, room_id):
        """Record checkout event from TV device."""

        try:
            tv_device = TVDevice.objects.get(room_id=room_id, is_active=True)
        except TVDevice.DoesNotExist:
            return Response(
                {'status': 'ok', 'message': 'Device not registered'},
                status=status.HTTP_200_OK
            )

        # Log checkout event
        serializer = TVCheckoutSerializer(data=request.data)
        event_data = None
        if serializer.is_valid():
            event_data = serializer.validated_data

        TVSession.objects.create(
            tv_device=tv_device,
            event_type=TVSession.EventType.CHECK_OUT,
            event_data=event_data
        )

        return Response({'status': 'ok'}, status=status.HTTP_200_OK)


class TVAppLaunchView(APIView):
    """
    Log when an external app is launched from the TV.
    """
    permission_classes = [AllowAny]

    def post(self, request, room_id):
        """Record app launch event."""

        app_name = request.data.get('app_name')

        try:
            tv_device = TVDevice.objects.get(room_id=room_id, is_active=True)
        except TVDevice.DoesNotExist:
            return Response(
                {'status': 'ok'},
                status=status.HTTP_200_OK
            )

        TVSession.objects.create(
            tv_device=tv_device,
            event_type=TVSession.EventType.APP_LAUNCH,
            event_data={'app_name': app_name}
        )

        return Response({'status': 'ok'}, status=status.HTTP_200_OK)

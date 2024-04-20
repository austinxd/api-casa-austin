from django.utils import timezone
from datetime import timedelta

from django.test import TestCase

from apps.property.models import Property
from apps.reservation.models import Reservation

class ReservationTest(TestCase):
    def setUp(self):
        current_date = timezone.now().date()

        self.property = Property.objects.create(name="CA1")
        self.reservation = Reservation.objects.create(
            property=self.property,
            check_in_date = current_date + timedelta(days=1),
            check_out_date = current_date + timedelta(days=2)
        )


    def test_reservation_default_creation(self):
        reservation_query = Reservation.objects.all()
        reservation_instance = reservation_query.last()

        self.assertEqual(reservation_query.count(), 1)
        self.assertEqual(reservation_instance.guests, 1)
        self.assertEqual(reservation_instance.origin, 'aus')
        self.assertEqual(reservation_instance.client, None)
        self.assertEqual(reservation_instance.seller, None)
        self.assertEqual(reservation_instance.price_sol, 0)
        self.assertEqual(reservation_instance.price_usd, 0)
        self.assertEqual(reservation_instance.advance_payment, 0)
        self.assertEqual(reservation_instance.advance_payment_currency, 'sol')
        self.assertEqual(reservation_instance.uuid_external, None)
        self.assertEqual(reservation_instance.tel_contact_number, None)
        self.assertEqual(reservation_instance.full_payment, False)
        self.assertEqual(reservation_instance.temperature_pool, False)

        
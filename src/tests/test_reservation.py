from django.utils import timezone
from datetime import timedelta

from django.test import TestCase
from rest_framework.test import APIClient

from django.urls import reverse

from apps.property.models import Property
from apps.reservation.models import Reservation

from django.contrib.auth.hashers import make_password

from apps.clients.models import Clients
from django.contrib.auth.models import Group
from apps.accounts.models import CustomUser


def create_group(group_name):
    """
    Funcion Auxiliar para crear grupo en caso que no exista
    """
    if not Group.objects.filter(name=group_name).exists():
        group = Group.objects.create(name=group_name)
        return group
    else:
        print(f"El grupo '{group_name}' ya existe.")

class ReservationTest(TestCase):
    def setUp(self):
        current_date = timezone.now().date()

        self.property = Property.objects.create(name="CA1")
        self.reservation = Reservation.objects.create(
            property=self.property,
            check_in_date = current_date + timedelta(days=1),
            check_out_date = current_date + timedelta(days=2)
        )

        grupo_admin_instance = create_group('admin')
        create_group('vendedor')
        create_group('mantenimiento')

        if not CustomUser.objects.filter(is_staff=True):
            try:
                usuario = CustomUser.objects.create(
                    first_name='Admin',
                    last_name='Sistema',
                    username=f"admin@mail.com",
                    email=f"admin@mail.com",
                    password=make_password("paloma227")
                )

                usuario.is_staff = True
                usuario.is_superuser = True
                usuario.save()

            except Exception as e:
                print('ERROR AL CREAR SUPER USER: ', str(e))

        for us in CustomUser.objects.filter(is_staff=True):
            us.groups.add(grupo_admin_instance)


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

    def test_reservation_mantenimiento_api_creation(self):
        client = APIClient()
        response = client.post(
            reverse('login_jwt'),
            {
                'email':'admin@mail.com',
                'password':'paloma227'
            }
        )

        self.assertEqual(response.status_code, 200)  # Logueo exitoso

        # Obtener el token de la response anterior
        token = response.json()['access']

        client.credentials(HTTP_AUTHORIZATION='Bearer ' + token)
        response = client.get(reverse('test_token'))

        self.assertEqual(response.response.status_code, 200)
        self.assertContains(
            response.json()['message'],
            'Bienvenido/a a Casa Austin. API y Token Funcionando ok!'
        )
        
from django.test import TestCase
from rest_framework.test import APITestCase, APIClient

from django.urls import reverse

from tests.utils.functions import create_group, create_user


class APIGeneralTest(APITestCase):
    """ Testear respuestas de todas las apis LISTView
    - Desc: Probar que algun cambio no haya afectado al funcionamiento general de otras apis.
    La sola respuesta 200 indica que todo funciona a grandes razgos
    """
    def setUp(self):
        group_instance = create_group("admin")
        self.user = create_user(True, group_instance)

        self.client.force_authenticate(user=self.user)

    def test_dashboard_response(self):
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)

    def test_token_rutificador_response(self):
        response = self.client.get(reverse('token_rutificador'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual("token" in response.data, True)

    def test_mensaje_fidelidad_response(self):
        response = self.client.get(reverse('mensaje_fidelidad'))
        self.assertEqual(response.status_code, 200)        

    def test_property_response(self):
        url = reverse('property-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_clients_response(self):
        url = reverse('clients-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_reservation_response(self):
        url = reverse('reservations-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

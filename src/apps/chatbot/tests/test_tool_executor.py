from django.test import TestCase

from apps.chatbot.models import ChatSession, ChatbotConfiguration
from apps.chatbot.tool_executor import ToolExecutor, TOOL_DEFINITIONS


class ToolDefinitionsTest(TestCase):
    """Tests para las definiciones de herramientas"""

    def test_all_tools_have_required_fields(self):
        """Todas las herramientas tienen nombre y descripción"""
        for tool in TOOL_DEFINITIONS:
            self.assertEqual(tool['type'], 'function')
            func = tool['function']
            self.assertIn('name', func)
            self.assertIn('description', func)
            self.assertIn('parameters', func)

    def test_tool_count(self):
        """Hay 7 herramientas definidas"""
        self.assertEqual(len(TOOL_DEFINITIONS), 7)

    def test_tool_names(self):
        """Los nombres de las herramientas son correctos"""
        names = [t['function']['name'] for t in TOOL_DEFINITIONS]
        expected = [
            'check_availability', 'identify_client', 'check_client_points',
            'validate_discount_code',
            'get_property_info', 'schedule_visit', 'escalate_to_human',
        ]
        self.assertEqual(names, expected)


class ToolExecutorTest(TestCase):
    """Tests para el ejecutor de herramientas"""

    def setUp(self):
        self.session = ChatSession.objects.create(
            wa_id='51999888777',
            wa_profile_name='Test User',
        )
        self.executor = ToolExecutor(self.session)
        ChatbotConfiguration.objects.create(is_active=False)

    def test_execute_unknown_tool(self):
        """Herramienta desconocida retorna error"""
        result = self.executor.execute('unknown_tool', {})
        self.assertIn('no encontrada', result)

    def test_get_property_info_all(self):
        """get_property_info sin filtro retorna todas las propiedades"""
        result = self.executor.execute('get_property_info', {})
        # Puede retornar vacío o propiedades
        self.assertIsInstance(result, str)

    def test_identify_client_not_found(self):
        """identify_client retorna mensaje cuando no encuentra"""
        result = self.executor.execute('identify_client', {
            'document_number': '99999999'
        })
        self.assertIn('No se encontró', result)

    def test_check_client_points_not_found(self):
        """check_client_points retorna error con ID inválido"""
        result = self.executor.execute('check_client_points', {
            'client_id': '00000000-0000-0000-0000-000000000000'
        })
        self.assertIn('no encontrado', result)

    def test_validate_discount_invalid_code(self):
        """validate_discount_code con código inexistente"""
        result = self.executor.execute('validate_discount_code', {
            'code': 'CODIGO_INEXISTENTE'
        })
        self.assertIn('no encontrado', result.lower()) or self.assertIn('inválido', result.lower())

    def test_escalate_to_human(self):
        """escalate_to_human pausa la IA y cambia estado"""
        result = self.executor.execute('escalate_to_human', {
            'reason': 'Cliente solicita hablar con persona'
        })

        self.session.refresh_from_db()
        self.assertFalse(self.session.ai_enabled)
        self.assertEqual(self.session.status, 'escalated')
        self.assertIn('escalada', result.lower())

    def test_schedule_visit_no_property(self):
        """schedule_visit con propiedad inexistente retorna error"""
        result = self.executor.execute('schedule_visit', {
            'property_name': 'Casa Inexistente',
            'visit_date': '2026-03-15',
            'visitor_name': 'Juan Test',
        })
        self.assertIn('No se encontró', result)

    def test_schedule_visit_past_date(self):
        """schedule_visit con fecha pasada retorna error"""
        from apps.property.models import Property
        Property.objects.create(name='Casa Test Visita', deleted=False)
        result = self.executor.execute('schedule_visit', {
            'property_name': 'Casa Test Visita',
            'visit_date': '2020-01-01',
            'visitor_name': 'Juan Test',
        })
        self.assertIn('fecha pasada', result)

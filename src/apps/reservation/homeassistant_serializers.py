from rest_framework import serializers
from apps.property.models import HomeAssistantDevice


class ClientDeviceSerializer(serializers.Serializer):
    """
    Serializer para mostrar dispositivos a clientes
    """
    id = serializers.UUIDField(read_only=True)
    entity_id = serializers.CharField(read_only=True)
    friendly_name = serializers.CharField(read_only=True)
    location = serializers.CharField(read_only=True, allow_null=True)
    device_type = serializers.CharField(read_only=True)
    icon = serializers.CharField(read_only=True, allow_null=True)
    description = serializers.CharField(read_only=True, allow_null=True)
    display_order = serializers.IntegerField(read_only=True)
    
    # Estado actual del dispositivo (obtenido de Home Assistant)
    current_state = serializers.CharField(read_only=True)
    
    # Capacidades del dispositivo
    supports_brightness = serializers.BooleanField(read_only=True)
    supports_temperature = serializers.BooleanField(read_only=True)
    
    # Atributos adicionales del estado
    attributes = serializers.DictField(read_only=True, required=False)


class DeviceActionSerializer(serializers.Serializer):
    """
    Serializer para validar acciones de control de dispositivos
    """
    ACTION_CHOICES = [
        ('turn_on', 'Encender'),
        ('turn_off', 'Apagar'),
        ('toggle', 'Alternar'),
        ('set_brightness', 'Ajustar brillo'),
        ('set_temperature', 'Ajustar temperatura'),
    ]
    
    action = serializers.ChoiceField(
        choices=ACTION_CHOICES,
        required=True,
        help_text="Acción a realizar en el dispositivo"
    )
    
    value = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Valor para acciones que lo requieren (brightness: 0-255, temperature: grados)"
    )
    
    def validate(self, data):
        """
        Validación personalizada para asegurar que las acciones tengan los parámetros correctos
        """
        action = data.get('action')
        value = data.get('value')
        
        # Acciones que requieren un valor
        if action in ['set_brightness', 'set_temperature']:
            if value is None:
                raise serializers.ValidationError({
                    'value': f'La acción {action} requiere un valor'
                })
        
        # Validar rango de brillo
        if action == 'set_brightness':
            if not isinstance(value, int) or value < 0 or value > 255:
                raise serializers.ValidationError({
                    'value': 'El brillo debe ser un número entre 0 y 255'
                })
        
        # Validar temperatura (rango razonable)
        if action == 'set_temperature':
            if not isinstance(value, (int, float)) or value < 10 or value > 40:
                raise serializers.ValidationError({
                    'value': 'La temperatura debe estar entre 10 y 40 grados'
                })
        
        return data
    
    def validate_device_compatibility(self, device, action):
        """
        Valida que la acción sea compatible con el tipo de dispositivo
        
        Args:
            device: HomeAssistantDevice instance
            action: Acción a validar
            
        Raises:
            serializers.ValidationError: Si la acción no es compatible
        """
        if action == 'set_brightness' and device.device_type != 'light':
            raise serializers.ValidationError(
                f"La acción 'set_brightness' solo está disponible para luces. "
                f"Este dispositivo es de tipo '{device.device_type}'"
            )
        
        if action == 'set_temperature' and device.device_type != 'climate':
            raise serializers.ValidationError(
                f"La acción 'set_temperature' solo está disponible para dispositivos de clima. "
                f"Este dispositivo es de tipo '{device.device_type}'"
            )


class DeviceActionResponseSerializer(serializers.Serializer):
    """
    Serializer para la respuesta de acciones de control
    """
    status = serializers.CharField(read_only=True)
    message = serializers.CharField(read_only=True)
    device_id = serializers.UUIDField(read_only=True)
    device_name = serializers.CharField(read_only=True)
    action = serializers.CharField(read_only=True)
    entity_state = serializers.DictField(read_only=True)

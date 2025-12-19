import uuid
from django.db import models
from django.utils import timezone


class DNICache(models.Model):
    """
    Cache de consultas de DNI a RENIEC.
    Almacena los datos para evitar consultas repetidas a la API externa.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dni = models.CharField(max_length=8, unique=True, db_index=True)

    # Datos personales básicos
    nombres = models.CharField(max_length=200, null=True, blank=True)
    apellido_paterno = models.CharField(max_length=100, null=True, blank=True)
    apellido_materno = models.CharField(max_length=100, null=True, blank=True)
    apellido_casada = models.CharField(max_length=100, null=True, blank=True)

    # Datos adicionales
    fecha_nacimiento = models.DateField(null=True, blank=True)
    sexo = models.CharField(max_length=1, null=True, blank=True)  # M/F
    estado_civil = models.CharField(max_length=50, null=True, blank=True)

    # Ubicación de nacimiento
    departamento = models.CharField(max_length=100, null=True, blank=True)
    provincia = models.CharField(max_length=100, null=True, blank=True)
    distrito = models.CharField(max_length=100, null=True, blank=True)

    # Dirección actual
    departamento_direccion = models.CharField(max_length=100, null=True, blank=True)
    provincia_direccion = models.CharField(max_length=100, null=True, blank=True)
    distrito_direccion = models.CharField(max_length=100, null=True, blank=True)
    direccion = models.TextField(null=True, blank=True)

    # Datos del documento
    fecha_emision = models.DateField(null=True, blank=True)
    fecha_caducidad = models.DateField(null=True, blank=True)
    digito_verificacion = models.CharField(max_length=1, null=True, blank=True)

    # Ubigeo
    ubigeo_reniec = models.CharField(max_length=10, null=True, blank=True)
    ubigeo_inei = models.CharField(max_length=10, null=True, blank=True)

    # Imagen (base64 o URL)
    foto = models.TextField(null=True, blank=True)

    # Datos completos de la API (JSON para campos adicionales)
    raw_data = models.JSONField(null=True, blank=True, help_text="Datos completos de la API")

    # Metadatos
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)
    source = models.CharField(
        max_length=20,
        choices=[
            ('api', 'API Externa'),
            ('manual', 'Ingreso Manual'),
        ],
        default='api'
    )

    class Meta:
        db_table = 'reniec_dni_cache'
        verbose_name = 'DNI Cache'
        verbose_name_plural = 'DNI Cache'
        ordering = ['-created']

    def __str__(self):
        return f"{self.dni} - {self.nombres} {self.apellido_paterno}"

    @property
    def nombre_completo(self):
        """Retorna el nombre completo formateado"""
        partes = [self.nombres, self.apellido_paterno, self.apellido_materno]
        return ' '.join(p for p in partes if p)

    @classmethod
    def get_or_none(cls, dni: str):
        """Obtiene el registro de cache o None si no existe"""
        try:
            return cls.objects.get(dni=dni)
        except cls.DoesNotExist:
            return None


class DNIQueryLog(models.Model):
    """
    Log de consultas de DNI para auditoría y rate limiting.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Consulta
    dni = models.CharField(max_length=8, db_index=True)

    # Origen de la consulta
    source_app = models.CharField(
        max_length=50,
        db_index=True,
        help_text="Identificador de la aplicación que hizo la consulta"
    )
    source_ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, null=True, blank=True)

    # Usuario que hizo la consulta (si está autenticado)
    user = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='dni_queries'
    )
    client = models.ForeignKey(
        'clients.Clients',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='dni_queries'
    )

    # Resultado
    success = models.BooleanField(default=False)
    from_cache = models.BooleanField(default=False, help_text="Si el resultado vino del cache")
    error_message = models.TextField(null=True, blank=True)
    response_time_ms = models.IntegerField(null=True, blank=True, help_text="Tiempo de respuesta en ms")

    # Timestamp
    created = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'reniec_query_log'
        verbose_name = 'DNI Query Log'
        verbose_name_plural = 'DNI Query Logs'
        ordering = ['-created']
        indexes = [
            models.Index(fields=['source_app', 'created']),
            models.Index(fields=['dni', 'created']),
        ]

    def __str__(self):
        return f"{self.dni} - {self.source_app} - {self.created}"

    @classmethod
    def count_queries_today(cls, source_app: str = None, source_ip: str = None) -> int:
        """Cuenta las consultas realizadas hoy para rate limiting"""
        today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        qs = cls.objects.filter(created__gte=today_start)

        if source_app:
            qs = qs.filter(source_app=source_app)
        if source_ip:
            qs = qs.filter(source_ip=source_ip)

        return qs.count()

    @classmethod
    def count_queries_last_minute(cls, source_ip: str) -> int:
        """Cuenta las consultas del último minuto para rate limiting"""
        one_minute_ago = timezone.now() - timezone.timedelta(minutes=1)
        return cls.objects.filter(
            source_ip=source_ip,
            created__gte=one_minute_ago
        ).count()


class APIKey(models.Model):
    """
    API Keys para autenticar aplicaciones que consumen el servicio de DNI.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    name = models.CharField(max_length=100, help_text="Nombre de la aplicación")
    key = models.CharField(max_length=64, unique=True, db_index=True)

    # Configuración
    is_active = models.BooleanField(default=True)
    rate_limit_per_day = models.IntegerField(
        default=1000,
        help_text="Límite de consultas por día"
    )
    rate_limit_per_minute = models.IntegerField(
        default=10,
        help_text="Límite de consultas por minuto"
    )

    # Permisos
    can_view_photo = models.BooleanField(
        default=False,
        help_text="Puede ver la foto del DNI"
    )
    can_view_full_data = models.BooleanField(
        default=False,
        help_text="Puede ver todos los datos (direccion, padres, etc)"
    )

    # Metadatos
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)
    last_used = models.DateTimeField(null=True, blank=True)

    # Notas
    notes = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'reniec_api_keys'
        verbose_name = 'API Key'
        verbose_name_plural = 'API Keys'

    def __str__(self):
        return f"{self.name} - {'Activa' if self.is_active else 'Inactiva'}"

    @classmethod
    def generate_key(cls) -> str:
        """Genera una nueva API key"""
        import secrets
        return secrets.token_hex(32)

    def save(self, *args, **kwargs):
        if not self.key:
            self.key = self.generate_key()
        super().save(*args, **kwargs)

    def update_last_used(self):
        """Actualiza el timestamp de último uso"""
        self.last_used = timezone.now()
        self.save(update_fields=['last_used'])

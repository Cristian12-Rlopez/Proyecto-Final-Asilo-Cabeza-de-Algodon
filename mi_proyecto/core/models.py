from decimal import Decimal, ROUND_HALF_UP

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Sum
from django.utils import timezone

CERO = Decimal('0.00')


def hoy():
    return timezone.localdate()


def q2(valor):
    return Decimal(valor).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


# ------------------------------------------------------------------ MÓDULO 1
class Interno(models.Model):
    ESTADOS = [('Activo', 'Activo'), ('Inactivo', 'Inactivo')]

    nombre_completo = models.CharField('Nombre completo', max_length=150)
    fecha_nacimiento = models.DateField('Fecha de nacimiento', null=True, blank=True)
    motivo_reclusion = models.TextField('Motivo de reclusión')
    psicopatologias = models.TextField('Psicopatologías', blank=True)
    medicinas_de_cajon = models.TextField('Medicinas de cajón (tratamiento fijo)', blank=True)
    estado = models.CharField('Estado', max_length=20, choices=ESTADOS, default='Activo')

    class Meta:
        ordering = ['nombre_completo']

    def __str__(self):
        return self.nombre_completo


class FamiliarResponsable(models.Model):
    interno = models.ForeignKey(Interno, on_delete=models.CASCADE, related_name='familiares',
                                verbose_name='Interno')
    nombre_completo = models.CharField('Nombre completo', max_length=150)
    parentesco = models.CharField('Parentesco', max_length=50)
    telefono = models.CharField('Teléfono', max_length=20)
    correo_electronico = models.EmailField('Correo electrónico')

    def __str__(self):
        return f'{self.nombre_completo} ({self.parentesco})'


# ------------------------------------------------------------------ CATÁLOGOS
class MedicoEspecialista(models.Model):
    nombre = models.CharField('Nombre', max_length=150)
    especialidad = models.CharField('Especialidad', max_length=100)
    telefono = models.CharField('Teléfono', max_length=20, blank=True)

    def __str__(self):
        return f'Dr(a). {self.nombre} - {self.especialidad}'


class Enfermero(models.Model):
    nombre = models.CharField('Nombre', max_length=150)
    telefono = models.CharField('Teléfono', max_length=20, blank=True)

    def __str__(self):
        return self.nombre


# ------------------------------------------------------------------ MÓDULO 2
class SolicitudRemision(models.Model):
    ESTADOS = [
        ('Evaluada', 'Evaluada (sin remitir)'),
        ('Pendiente', 'Remitida - pendiente de agenda'),
        ('Agendada', 'Cita agendada'),
        ('Atendida', 'Atendida'),
    ]
    interno = models.ForeignKey(Interno, on_delete=models.CASCADE, related_name='solicitudes',
                                verbose_name='Interno')
    fecha_emision = models.DateField('Fecha de emisión', default=hoy)
    evaluacion_inicial = models.TextField('Evaluación inicial del médico general')
    especialidad_requerida = models.CharField('Especialidad requerida', max_length=100, blank=True)
    enfermero_asignado = models.ForeignKey(Enfermero, on_delete=models.SET_NULL, null=True, blank=True,
                                           verbose_name='Enfermero(a) acompañante')
    estado = models.CharField('Estado', max_length=30, choices=ESTADOS, default='Evaluada')

    class Meta:
        ordering = ['-id']

    def __str__(self):
        return f'Remisión #{self.pk} - {self.interno}'


class AgendaCita(models.Model):
    ESTADOS = [('Agendada', 'Agendada'), ('Realizada', 'Realizada'), ('Cancelada', 'Cancelada')]
    solicitud = models.OneToOneField(SolicitudRemision, on_delete=models.CASCADE,
                                     verbose_name='Solicitud de remisión')
    fecha_hora_cita = models.DateTimeField('Fecha y hora de la cita')
    medico_especialista = models.ForeignKey(MedicoEspecialista, on_delete=models.PROTECT,
                                            verbose_name='Médico especialista')
    estado_cita = models.CharField('Estado de la cita', max_length=30, choices=ESTADOS, default='Agendada')

    class Meta:
        ordering = ['-fecha_hora_cita']

    def __str__(self):
        return f'Cita {self.fecha_hora_cita:%d/%m/%Y %H:%M} - {self.medico_especialista.nombre}'


class NotificacionCorreo(models.Model):
    solicitud = models.ForeignKey(SolicitudRemision, on_delete=models.CASCADE, related_name='notificaciones')
    destinatario = models.EmailField()
    asunto = models.CharField(max_length=200)
    cuerpo = models.TextField()
    enviado = models.BooleanField(default=False)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-id']


# ------------------------------------------------------------------ MÓDULO 4 (descuentos)
class DescuentoFundacion(models.Model):
    RUBROS = [('Consulta', 'Consulta médica'), ('Laboratorio', 'Laboratorio'), ('Farmacia', 'Farmacia')]
    rubro = models.CharField('Rubro', max_length=20, choices=RUBROS)
    porcentaje = models.DecimalField('Descuento (%)', max_digits=5, decimal_places=2,
                                     validators=[MinValueValidator(0), MaxValueValidator(100)])
    activo = models.BooleanField('Vigente', default=True)

    def __str__(self):
        return f'{self.rubro}: {self.porcentaje}%'


def porcentaje_descuento(rubro):
    d = DescuentoFundacion.objects.filter(rubro=rubro, activo=True).order_by('-id').first()
    return d.porcentaje if d else CERO


# ------------------------------------------------------------------ MÓDULO 3
class VisitaMedica(models.Model):
    ESTADOS = [('Abierta', 'Abierta'), ('Cerrada', 'Cerrada')]
    ESTADOS_PAGO = [
        ('Sin cargos', 'Sin cargos'),
        ('Pendiente de pago', 'Pendiente de pago'),
        ('Pago parcial', 'Pago parcial'),
        ('Cancelada', 'Cancelada (pagada)'),
    ]
    solicitud = models.OneToOneField(SolicitudRemision, on_delete=models.SET_NULL, null=True, blank=True,
                                     verbose_name='Solicitud de remisión')
    interno = models.ForeignKey(Interno, on_delete=models.CASCADE, related_name='visitas',
                                verbose_name='Interno')
    medico_especialista = models.ForeignKey(MedicoEspecialista, on_delete=models.SET_NULL, null=True,
                                            verbose_name='Médico tratante')
    fecha_visita = models.DateField('Fecha de visita', default=hoy)
    motivo_visita = models.CharField('Motivo de visita', max_length=250)
    diagnostico = models.TextField('Diagnóstico', blank=True)
    observaciones = models.TextField('Observaciones médicas', blank=True)
    costo_consulta = models.DecimalField('Costo de la consulta (Q)', max_digits=10, decimal_places=2,
                                         default=CERO)
    estado = models.CharField('Estado', max_length=20, choices=ESTADOS, default='Abierta')
    estado_pago = models.CharField('Estado de pago', max_length=30, choices=ESTADOS_PAGO,
                                   default='Sin cargos')
    total_bruto = models.DecimalField(max_digits=10, decimal_places=2, default=CERO, editable=False)
    total_neto = models.DecimalField('Total neto (Q)', max_digits=10, decimal_places=2, default=CERO,
                                     editable=False)

    class Meta:
        ordering = ['-fecha_visita', '-id']

    def __str__(self):
        return f'Visita #{self.pk} - {self.interno} ({self.fecha_visita:%d/%m/%Y})'

    # --- costos --------------------------------------------------------
    def desglose(self):
        """Devuelve ([(rubro, bruto, % descuento, neto)], bruto total, neto total)."""
        labs = sum((o.costo for o in self.ordenes.all()), CERO)
        farm = sum((r.costo for r in self.recetas.all()), CERO)
        filas, tb, tn = [], CERO, CERO
        for rubro, bruto in (('Consulta', self.costo_consulta), ('Laboratorio', labs), ('Farmacia', farm)):
            pct = porcentaje_descuento(rubro)
            neto = q2(bruto * (Decimal(100) - pct) / Decimal(100))
            filas.append((rubro, q2(bruto), pct, neto))
            tb += q2(bruto)
            tn += neto
        return filas, tb, tn

    @property
    def bruto(self):
        return self.total_bruto if self.estado == 'Cerrada' else self.desglose()[1]

    @property
    def neto(self):
        return self.total_neto if self.estado == 'Cerrada' else self.desglose()[2]

    @property
    def total_pagado(self):
        return self.pagos.aggregate(t=Sum('monto'))['t'] or CERO

    @property
    def saldo(self):
        return self.neto - self.total_pagado

    def actualizar_estado_pago(self):
        if self.estado != 'Cerrada':
            return
        pagado = self.total_pagado
        if self.total_neto <= 0:
            nuevo = 'Sin cargos'
        elif pagado >= self.total_neto:
            nuevo = 'Cancelada'
        elif pagado > 0:
            nuevo = 'Pago parcial'
        else:
            nuevo = 'Pendiente de pago'
        if nuevo != self.estado_pago:
            self.estado_pago = nuevo
            self.save(update_fields=['estado_pago'])


class OrdenLaboratorio(models.Model):
    ESTADOS = [('Pendiente', 'Pendiente'), ('Completada', 'Completada')]
    visita = models.ForeignKey(VisitaMedica, on_delete=models.CASCADE, related_name='ordenes',
                               verbose_name='Visita médica')
    tipo_examen = models.CharField('Examen solicitado', max_length=150)
    costo = models.DecimalField('Costo del examen (Q)', max_digits=10, decimal_places=2, default=CERO)
    resultado = models.TextField('Resultado digital', blank=True)
    estado = models.CharField('Estado', max_length=20, choices=ESTADOS, default='Pendiente')
    fecha_solicitud = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-id']

    def __str__(self):
        return f'{self.tipo_examen} - {self.visita.interno}'


class RecetaFarmacia(models.Model):
    visita = models.ForeignKey(VisitaMedica, on_delete=models.CASCADE, related_name='recetas',
                               verbose_name='Visita médica')
    medicamento = models.CharField('Medicamento', max_length=150)
    cantidad = models.PositiveIntegerField('Cantidad', default=1)
    tiempo_aplicacion = models.CharField('Tiempo de aplicación', max_length=100)
    indicaciones = models.TextField('Cómo tomarlo', blank=True)
    costo = models.DecimalField('Costo (Q)', max_digits=10, decimal_places=2, default=CERO)
    despachado = models.BooleanField('Despachado', default=False)

    class Meta:
        ordering = ['-id']

    def __str__(self):
        return f'{self.medicamento} x{self.cantidad}'


# ------------------------------------------------------------------ MÓDULO 4
class PagoFundacion(models.Model):
    FORMAS = [('Efectivo', 'Efectivo'), ('Transferencia', 'Transferencia'), ('Cheque', 'Cheque')]
    visita = models.ForeignKey(VisitaMedica, on_delete=models.CASCADE, related_name='pagos',
                               verbose_name='Visita médica')
    fecha = models.DateField('Fecha de pago', default=hoy)
    monto = models.DecimalField('Monto (Q)', max_digits=10, decimal_places=2)
    forma_pago = models.CharField('Forma de pago', max_length=30, choices=FORMAS, default='Transferencia')

    class Meta:
        ordering = ['-fecha', '-id']

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.visita.actualizar_estado_pago()

    def delete(self, *args, **kwargs):
        visita = self.visita
        resultado = super().delete(*args, **kwargs)
        visita.actualizar_estado_pago()
        return resultado

    def __str__(self):
        return f'Pago Q{self.monto} - visita #{self.visita_id}'


class CuotaFamiliar(models.Model):
    interno = models.ForeignKey(Interno, on_delete=models.CASCADE, verbose_name='Interno')
    mes_correspondiente = models.CharField('Mes (AAAA-MM)', max_length=7)
    monto_cuota = models.DecimalField('Cuota mensual fija (Q)', max_digits=10, decimal_places=2)
    cargos_medicos = models.DecimalField('Cargos médicos (Q)', max_digits=10, decimal_places=2,
                                         default=CERO, editable=False)
    pagado = models.BooleanField('¿Pagado?', default=False)
    fecha_pago = models.DateField('Fecha de pago', null=True, blank=True)

    class Meta:
        ordering = ['-mes_correspondiente', 'interno']
        unique_together = [('interno', 'mes_correspondiente')]

    @property
    def total(self):
        return self.monto_cuota + self.cargos_medicos

    def __str__(self):
        return f'Cuota {self.mes_correspondiente} - {self.interno}'


class Donacion(models.Model):
    TIPOS = [
        ('Empresa Internacional', 'Empresa Internacional'),
        ('Empresa Nacional', 'Empresa Nacional'),
        ('Gobierno', 'Gobierno'),
        ('Particular', 'Particular'),
    ]
    donante = models.CharField('Donante', max_length=150)
    tipo_donacion = models.CharField('Tipo de donante', max_length=50, choices=TIPOS, default='Particular')
    monto = models.DecimalField('Monto (Q)', max_digits=10, decimal_places=2)
    fecha = models.DateField('Fecha', default=hoy)

    class Meta:
        ordering = ['-fecha', '-id']

    def __str__(self):
        return f'{self.donante} - Q{self.monto}'


class GastoOperativo(models.Model):
    CATEGORIAS = [('Luz', 'Luz'), ('Agua', 'Agua'), ('Otros', 'Otros')]
    concepto = models.CharField('Concepto', max_length=150)
    categoria = models.CharField('Categoría', max_length=50, choices=CATEGORIAS)
    monto = models.DecimalField('Monto (Q)', max_digits=10, decimal_places=2)
    fecha = models.DateField('Fecha', default=hoy)

    class Meta:
        ordering = ['-fecha', '-id']

    def __str__(self):
        return f'{self.concepto} - Q{self.monto}'

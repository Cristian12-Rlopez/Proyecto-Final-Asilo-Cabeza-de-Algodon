"""Lógica de negocio: cierre de visita, cargos a familiares y notificaciones por correo."""
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction

from .models import CERO, CuotaFamiliar, NotificacionCorreo


@transaction.atomic
def cerrar_visita(visita):
    """RF-10/11/12: aplica descuentos, fija totales, genera la deuda con la Fundación
    y carga el costo neto a la cuota mensual del familiar."""
    if visita.estado == 'Cerrada':
        raise ValueError('La visita ya está cerrada.')
    if not visita.diagnostico.strip():
        raise ValueError('Registra el diagnóstico antes de cerrar la visita.')

    _, bruto, neto = visita.desglose()
    visita.total_bruto, visita.total_neto = bruto, neto
    visita.estado = 'Cerrada'
    visita.estado_pago = 'Pendiente de pago' if neto > 0 else 'Sin cargos'
    visita.save()

    if neto > 0:
        mes = visita.fecha_visita.strftime('%Y-%m')
        ultima = CuotaFamiliar.objects.filter(interno=visita.interno).order_by('-mes_correspondiente').first()
        cuota, _ = CuotaFamiliar.objects.get_or_create(
            interno=visita.interno, mes_correspondiente=mes,
            defaults={'monto_cuota': ultima.monto_cuota if ultima else CERO})
        cuota.cargos_medicos += neto
        cuota.save()

    if visita.solicitud_id:
        cita = getattr(visita.solicitud, 'agendacita', None)
        if cita and cita.estado_cita == 'Agendada':
            cita.estado_cita = 'Realizada'
            cita.save(update_fields=['estado_cita'])
    return visita


def texto_remision(s):
    return (f'Estimado(a) familiar de {s.interno.nombre_completo}:\n\n'
            f'Le informamos que el médico general del Asilo Cabeza de Algodón evaluó al interno y '
            f'emitió una remisión a la especialidad de {s.especialidad_requerida}.\n\n'
            f'Evaluación inicial: {s.evaluacion_inicial}\n'
            f'Enfermero(a) acompañante: {s.enfermero_asignado or "por asignar"}\n'
            f'Estado de la solicitud: {s.get_estado_display()}\n\n'
            f'Le avisaremos cuando la Fundación confirme la fecha y hora de la cita.\n\n'
            f'Asilo Cabeza de Algodón')


def texto_cita(cita):
    s = cita.solicitud
    return (f'Estimado(a) familiar de {s.interno.nombre_completo}:\n\n'
            f'La Fundación confirmó la cita médica:\n'
            f'  - Especialista: {cita.medico_especialista}\n'
            f'  - Fecha y hora: {cita.fecha_hora_cita:%d/%m/%Y %H:%M}\n'
            f'  - Enfermero(a) acompañante: {s.enfermero_asignado or "por asignar"}\n\n'
            f'Asilo Cabeza de Algodón')


def notificar_familiares(solicitud, asunto, cuerpo):
    """Envía el correo a todos los familiares registrados y deja bitácora (RF-06).
    Devuelve (enviados, total_destinatarios)."""
    familiares = list(solicitud.interno.familiares.all())
    enviados = 0
    for fam in familiares:
        try:
            send_mail(asunto, cuerpo, settings.DEFAULT_FROM_EMAIL, [fam.correo_electronico],
                      fail_silently=False)
            ok = True
            enviados += 1
        except Exception:
            ok = False
        NotificacionCorreo.objects.create(solicitud=solicitud, destinatario=fam.correo_electronico,
                                          asunto=asunto, cuerpo=cuerpo, enviado=ok)
    return enviados, len(familiares)

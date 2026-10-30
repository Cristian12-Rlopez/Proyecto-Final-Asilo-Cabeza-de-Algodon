"""Módulo 5: cada reporte devuelve un dict con titulo, subtitulo, columnas, filas y totales."""
from decimal import Decimal

from django.db.models import Sum

from .models import (
    CERO, CuotaFamiliar, Donacion, GastoOperativo, OrdenLaboratorio, PagoFundacion,
    RecetaFarmacia, VisitaMedica,
)


def Q(valor):
    return f'Q{(valor or CERO):,.2f}'


def fmt(fecha):
    return fecha.strftime('%d/%m/%Y') if fecha else '—'


def _subtitulo(desde, hasta, interno=None):
    lineas = []
    if desde or hasta:
        lineas.append(f'Período: {fmt(desde) if desde else "inicio"} al {fmt(hasta) if hasta else "hoy"}')
    else:
        lineas.append('Período: todos los registros')
    if interno:
        lineas.append(f'Paciente: {interno.nombre_completo}')
    return lineas


def _rango(qs, campo, desde, hasta):
    if desde:
        qs = qs.filter(**{f'{campo}__gte': desde})
    if hasta:
        qs = qs.filter(**{f'{campo}__lte': hasta})
    return qs


def _visitas(desde, hasta, interno):
    qs = VisitaMedica.objects.select_related('interno', 'medico_especialista')
    if interno:
        qs = qs.filter(interno=interno)
    return _rango(qs, 'fecha_visita', desde, hasta).order_by('fecha_visita', 'id')


# ------------------------------------------------------------------ Reportes clínicos
def rep_clinico(desde, hasta, interno):
    """Ficha médica por paciente: motivo de reclusión, tratamiento fijo y visitas (RF-14)."""
    filas = []
    for v in _visitas(desde, hasta, interno).prefetch_related('ordenes', 'recetas'):
        medico = f'{v.medico_especialista.nombre} ({v.medico_especialista.especialidad})' \
            if v.medico_especialista else '—'
        examenes = '; '.join(o.tipo_examen for o in v.ordenes.all()) or '—'
        resultados = '; '.join(f'{o.tipo_examen}: {o.resultado or "pendiente"}' for o in v.ordenes.all()) or '—'
        meds = '; '.join(f'{r.medicamento} x{r.cantidad} ({r.tiempo_aplicacion})' for r in v.recetas.all()) or '—'
        filas.append([fmt(v.fecha_visita), v.interno.nombre_completo, v.motivo_visita, medico, examenes,
                      resultados, v.diagnostico or '—', meds, v.observaciones or '—'])
    sub = _subtitulo(desde, hasta, interno)
    if interno:
        sub += [f'Motivo de reclusión: {interno.motivo_reclusion}',
                f'Psicopatologías: {interno.psicopatologias or "—"}',
                f'Medicinas de cajón: {interno.medicinas_de_cajon or "—"}']
    return {'titulo': 'Reporte clínico / ficha médica por paciente', 'subtitulo': sub,
            'columnas': ['Fecha', 'Paciente', 'Motivo de visita', 'Médico (especialidad)', 'Exámenes',
                         'Resultados', 'Diagnóstico', 'Medicamentos (cantidad, tiempo)', 'Observaciones'],
            'filas': filas, 'totales': [('Visitas registradas', len(filas))]}


def rep_examenes(desde, hasta, interno):
    qs = OrdenLaboratorio.objects.select_related('visita__interno')
    if interno:
        qs = qs.filter(visita__interno=interno)
    qs = _rango(qs, 'visita__fecha_visita', desde, hasta).order_by('visita__fecha_visita', 'id')
    filas = [[fmt(o.visita.fecha_visita), o.visita.interno.nombre_completo, o.tipo_examen, o.estado,
              o.resultado or '—', Q(o.costo)] for o in qs]
    return {'titulo': 'Exámenes de laboratorio realizados por paciente',
            'subtitulo': _subtitulo(desde, hasta, interno),
            'columnas': ['Fecha', 'Paciente', 'Examen', 'Estado', 'Resultado', 'Costo base'],
            'filas': filas, 'totales': [('Exámenes', len(filas))]}


def rep_medicamentos(desde, hasta, interno):
    qs = RecetaFarmacia.objects.select_related('visita__interno')
    if interno:
        qs = qs.filter(visita__interno=interno)
    qs = _rango(qs, 'visita__fecha_visita', desde, hasta).order_by('visita__fecha_visita', 'id')
    filas = [[fmt(r.visita.fecha_visita), r.visita.interno.nombre_completo, r.medicamento, r.cantidad,
              r.tiempo_aplicacion, 'Sí' if r.despachado else 'No', Q(r.costo)] for r in qs]
    return {'titulo': 'Medicamentos aplicados por paciente',
            'subtitulo': _subtitulo(desde, hasta, interno),
            'columnas': ['Fecha', 'Paciente', 'Medicamento', 'Cantidad', 'Tiempo de aplicación',
                         'Despachado', 'Costo base'],
            'filas': filas, 'totales': [('Medicamentos recetados', len(filas))]}


# ------------------------------------------------------------------ Costos
def rep_costos(desde, hasta, interno):
    """Costo de cada cita por paciente: consulta + laboratorio + farmacia, con descuento (RF-15)."""
    filas, tb, tn = [], CERO, CERO
    for v in _visitas(desde, hasta, interno).prefetch_related('ordenes', 'recetas'):
        det, bruto, neto = v.desglose()
        if v.estado == 'Cerrada':
            bruto, neto = v.total_bruto, v.total_neto
        cons, lab, farm = (d[1] for d in det)
        filas.append([fmt(v.fecha_visita), f'#{v.pk}', v.interno.nombre_completo, Q(cons), Q(lab), Q(farm),
                      Q(bruto), Q(bruto - neto), Q(neto), v.estado, v.estado_pago])
        tb += bruto
        tn += neto
    return {'titulo': 'Control de costos por cita y paciente',
            'subtitulo': _subtitulo(desde, hasta, interno),
            'columnas': ['Fecha', 'Visita', 'Paciente', 'Consulta', 'Laboratorio', 'Farmacia', 'Total base',
                         'Descuento Fundación', 'Total neto', 'Estado visita', 'Estado de pago'],
            'filas': filas,
            'totales': [('Total base', Q(tb)), ('Descuento total', Q(tb - tn)), ('Total neto', Q(tn))]}


def rep_cobros(desde, hasta, interno):
    """Cobros por paciente (cuota fija + gastos médicos) por rango de fechas."""
    qs = CuotaFamiliar.objects.select_related('interno')
    if interno:
        qs = qs.filter(interno=interno)
    if desde:
        qs = qs.filter(mes_correspondiente__gte=desde.strftime('%Y-%m'))
    if hasta:
        qs = qs.filter(mes_correspondiente__lte=hasta.strftime('%Y-%m'))
    filas, total, cobrado = [], CERO, CERO
    for c in qs.order_by('mes_correspondiente', 'interno__nombre_completo'):
        filas.append([c.mes_correspondiente, c.interno.nombre_completo, Q(c.monto_cuota), Q(c.cargos_medicos),
                      Q(c.total), 'Pagado' if c.pagado else 'Pendiente'])
        total += c.total
        if c.pagado:
            cobrado += c.total
    return {'titulo': 'Cobros a familiares por paciente (con gastos médicos)',
            'subtitulo': _subtitulo(desde, hasta, interno),
            'columnas': ['Mes', 'Paciente', 'Cuota fija', 'Gastos médicos (con descuento)', 'Total a cobrar',
                         'Estado'],
            'filas': filas,
            'totales': [('Total a cobrar', Q(total)), ('Total cobrado', Q(cobrado)),
                        ('Por cobrar', Q(total - cobrado))]}


# ------------------------------------------------------------------ Financieros
def _total_ingresos(desde, hasta):
    don = _rango(Donacion.objects.all(), 'fecha', desde, hasta).aggregate(t=Sum('monto'))['t'] or CERO
    cuo = _rango(CuotaFamiliar.objects.filter(pagado=True), 'fecha_pago', desde, hasta)
    cuotas = sum((c.total for c in cuo), CERO)
    return don, cuotas


def rep_ingresos(desde, hasta, interno=None):
    """Entradas: donaciones (por tipo de donante) y cuotas cobradas a familiares (RF-13)."""
    filas = []
    for d in _rango(Donacion.objects.all(), 'fecha', desde, hasta).order_by('fecha'):
        filas.append([fmt(d.fecha), 'Donación', d.tipo_donacion, d.donante, Q(d.monto)])
    for c in _rango(CuotaFamiliar.objects.filter(pagado=True).select_related('interno'),
                    'fecha_pago', desde, hasta).order_by('fecha_pago'):
        filas.append([fmt(c.fecha_pago), 'Cobro a familiar', f'Cuota {c.mes_correspondiente}',
                      c.interno.nombre_completo, Q(c.total)])
    don, cuotas = _total_ingresos(desde, hasta)
    return {'titulo': 'Entradas: donaciones y cobros', 'subtitulo': _subtitulo(desde, hasta),
            'columnas': ['Fecha', 'Origen', 'Tipo / detalle', 'Donante / paciente', 'Monto'],
            'filas': filas,
            'totales': [('Total donaciones', Q(don)), ('Total cobros a familiares', Q(cuotas)),
                        ('Total entradas', Q(don + cuotas))]}


def rep_egresos(desde, hasta, interno=None):
    """Salidas: gastos operativos y pagos a la Fundación, con balance."""
    filas = []
    for g in _rango(GastoOperativo.objects.all(), 'fecha', desde, hasta).order_by('fecha'):
        filas.append([fmt(g.fecha), 'Gasto operativo', g.categoria, g.concepto, Q(g.monto)])
    for p in _rango(PagoFundacion.objects.select_related('visita__interno'), 'fecha', desde, hasta).order_by('fecha'):
        filas.append([fmt(p.fecha), 'Pago a Fundación', p.forma_pago,
                      f'Visita #{p.visita_id} - {p.visita.interno.nombre_completo}', Q(p.monto)])
    gastos = _rango(GastoOperativo.objects.all(), 'fecha', desde, hasta).aggregate(t=Sum('monto'))['t'] or CERO
    pagos = _rango(PagoFundacion.objects.all(), 'fecha', desde, hasta).aggregate(t=Sum('monto'))['t'] or CERO
    don, cuotas = _total_ingresos(desde, hasta)
    egresos = gastos + pagos
    return {'titulo': 'Salidas: gastos operativos y pagos a la Fundación', 'subtitulo': _subtitulo(desde, hasta),
            'columnas': ['Fecha', 'Origen', 'Categoría / forma', 'Detalle', 'Monto'],
            'filas': filas,
            'totales': [('Gastos operativos', Q(gastos)), ('Pagos a la Fundación', Q(pagos)),
                        ('Total egresos', Q(egresos)), ('Total entradas del período', Q(don + cuotas)),
                        ('Balance (entradas - egresos)', Q(don + cuotas - egresos))]}


def rep_pagos_fundacion(desde, hasta, interno=None):
    """Pagos a la Fundación y deuda pendiente (RF-11)."""
    filas = []
    for p in _rango(PagoFundacion.objects.select_related('visita__interno'), 'fecha', desde, hasta).order_by('fecha'):
        filas.append([fmt(p.fecha), f'#{p.visita_id}', p.visita.interno.nombre_completo, p.forma_pago, Q(p.monto)])
    pagado = sum((p.monto for p in PagoFundacion.objects.filter(
        **({'fecha__gte': desde} if desde else {}), **({'fecha__lte': hasta} if hasta else {}))), CERO)
    deuda = sum((v.saldo for v in VisitaMedica.objects.filter(estado='Cerrada')
                 .exclude(estado_pago__in=['Sin cargos', 'Cancelada'])), CERO)
    return {'titulo': 'Pagos a la Fundación y cuentas pendientes', 'subtitulo': _subtitulo(desde, hasta),
            'columnas': ['Fecha', 'Visita', 'Paciente', 'Forma de pago', 'Monto'],
            'filas': filas,
            'totales': [('Pagado en el período', Q(pagado)), ('Saldo pendiente con la Fundación (a hoy)', Q(deuda))]}


REPORTES = {
    'clinico': ('Ficha médica por paciente', rep_clinico),
    'examenes': ('Exámenes por paciente', rep_examenes),
    'medicamentos': ('Medicamentos por paciente', rep_medicamentos),
    'costos': ('Costos por cita', rep_costos),
    'cobros': ('Cobros por paciente', rep_cobros),
    'ingresos': ('Entradas (donaciones y cobros)', rep_ingresos),
    'egresos': ('Salidas y balance', rep_egresos),
    'pagos_fundacion': ('Pagos a la Fundación', rep_pagos_fundacion),
}

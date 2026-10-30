from datetime import datetime
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import ProtectedError, Sum
from django.forms import modelform_factory
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils import formats, timezone
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from . import forms as f
from . import servicios
from .exportes import exportar_pdf, exportar_xlsx
from .models import (
    CERO, AgendaCita, CuotaFamiliar, DescuentoFundacion, Donacion, Enfermero, FamiliarResponsable,
    GastoOperativo, Interno, MedicoEspecialista, NotificacionCorreo, OrdenLaboratorio, PagoFundacion,
    RecetaFarmacia, SolicitudRemision, VisitaMedica,
)
from .reportes import REPORTES

# Colores por módulo (clases Tailwind completas, tal como están en el dashboard)
MODULOS = {
    1: ('Módulo 1: Gestión de Internos', 'bg-emerald-700', 'bg-emerald-600 hover:bg-emerald-700'),
    2: ('Módulo 2: Solicitudes y Agenda', 'bg-blue-700', 'bg-blue-600 hover:bg-blue-700'),
    3: ('Módulo 3: Visita Médica y Servicios', 'bg-purple-700', 'bg-purple-600 hover:bg-purple-700'),
    4: ('Módulo 4: Gestión Financiera', 'bg-amber-600', 'bg-amber-600 hover:bg-amber-700'),
    5: ('Módulo 5: Sistema de Reportes', 'bg-rose-700', 'bg-rose-600 hover:bg-rose-700'),
}


def _ctx_modulo(modulo):
    titulo, barra, boton = MODULOS[modulo]
    return {'modulo_titulo': titulo, 'clase_barra': barra, 'clase_boton': boton}


# ======================================================================================
#  Utilidades de presentación
# ======================================================================================
def valor(obj, atributo):
    """Texto de una celda: soporta 'campo', 'rel.campo', propiedades y campos con choices."""
    actual = obj
    for parte in atributo.split('.'):
        if actual is None:
            return '—'
        try:
            campo = actual._meta.get_field(parte)
            if getattr(campo, 'choices', None):
                actual = getattr(actual, f'get_{parte}_display')()
                continue
        except Exception:
            pass
        actual = getattr(actual, parte, None)
        if callable(actual):
            actual = actual()
    if actual is None or actual == '':
        return '—'
    if isinstance(actual, bool):
        return 'Sí' if actual else 'No'
    if isinstance(actual, datetime) and timezone.is_aware(actual):
        actual = timezone.localtime(actual)
    if isinstance(actual, Decimal):
        return f'{actual:,.2f}'
    return formats.localize(actual)


# ======================================================================================
#  Fábrica CRUD
# ======================================================================================
class Pagina:
    """Describe una pantalla del sistema: listado + crear/editar/eliminar + acciones por fila."""

    def __init__(self, nombre, modelo, titulo, modulo, columnas, descripcion='', form_crear=None,
                 form_editar=None, puede_eliminar=False, queryset=None, acciones=(), enlaces=(),
                 resumen=None, etiqueta_crear='+ Nuevo', etiqueta_editar='Editar',
                 despues_guardar=None, antes_eliminar=None, texto_eliminar=''):
        self.nombre, self.modelo, self.titulo, self.modulo = nombre, modelo, titulo, modulo
        self.columnas, self.descripcion = columnas, descripcion
        self.form_crear, self.form_editar = form_crear, form_editar
        self.puede_eliminar = puede_eliminar
        self.queryset = queryset
        self.acciones, self.enlaces, self.resumen = acciones, enlaces, resumen
        self.etiqueta_crear, self.etiqueta_editar = etiqueta_crear, etiqueta_editar
        self.despues_guardar, self.antes_eliminar = despues_guardar, antes_eliminar
        self.texto_eliminar = texto_eliminar

    @staticmethod
    def _clase_form(spec, modelo):
        if spec is None:
            return None
        if isinstance(spec, (list, tuple)):
            return modelform_factory(modelo, form=f.BaseForm, fields=list(spec))
        return spec

    def clase_crear(self):
        return self._clase_form(self.form_crear, self.modelo)

    def clase_editar(self):
        return self._clase_form(self.form_editar, self.modelo)

    def obtener_queryset(self):
        return self.queryset() if self.queryset else self.modelo.objects.all()

    # URLs ------------------------------------------------------------
    def urls(self, prefijo):
        n = self.nombre
        rutas = [path(f'{prefijo}/', self._lista(), name=n)]
        if self.form_crear:
            rutas.append(path(f'{prefijo}/nuevo/', self._crear(), name=f'{n}_nuevo'))
        if self.form_editar:
            rutas.append(path(f'{prefijo}/<int:pk>/editar/', self._editar(), name=f'{n}_editar'))
        if self.puede_eliminar:
            rutas.append(path(f'{prefijo}/<int:pk>/eliminar/', self._eliminar(), name=f'{n}_eliminar'))
        return rutas

    # Vistas ----------------------------------------------------------
    def _lista(self):
        pagina = self

        class Lista(LoginRequiredMixin, ListView):
            template_name = 'core/crud_list.html'
            context_object_name = 'objetos'

            def get_queryset(self):
                return pagina.obtener_queryset()

            def get_context_data(self, **kw):
                ctx = super().get_context_data(**kw)
                filas = []
                for obj in ctx['objetos']:
                    celdas = [valor(obj, attr) for _, attr in pagina.columnas]
                    acciones = []
                    for a in pagina.acciones:
                        cond = a.get('cuando')
                        if cond and not cond(obj):
                            continue
                        url = reverse(a['url'], args=[obj.pk]) if not a.get('query') \
                            else f"{reverse(a['url'])}?{a['query']}={obj.pk}"
                        acciones.append({'label': a['label'], 'url': url, 'post': a.get('post', False),
                                         'peligro': a.get('peligro', False)})
                    filas.append({'obj': obj, 'celdas': celdas, 'acciones': acciones})
                ctx.update(_ctx_modulo(pagina.modulo))
                ctx.update({
                    'pagina': pagina, 'encabezados': [c for c, _ in pagina.columnas], 'filas': filas,
                    'url_nuevo': reverse(f'{pagina.nombre}_nuevo') if pagina.form_crear else None,
                    'tiene_editar': bool(pagina.form_editar),
                    'tiene_eliminar': pagina.puede_eliminar,
                    'resumen': pagina.resumen() if pagina.resumen else [],
                    'enlaces': [(t, reverse(u)) for t, u in pagina.enlaces],
                })
                return ctx

        return Lista.as_view()

    def _formulario_base(self, base, creando):
        pagina = self

        class Formulario(LoginRequiredMixin, base):
            template_name = 'core/crud_form.html'
            model = pagina.modelo

            def get_form_class(self):
                return pagina.clase_crear() if creando else pagina.clase_editar()

            def get_initial(self):
                ini = super().get_initial()
                if creando:  # permite /nuevo/?visita=3 para precargar un campo
                    for clave, v in self.request.GET.items():
                        ini[clave] = v
                return ini

            def get_context_data(self, **kw):
                ctx = super().get_context_data(**kw)
                ctx.update(_ctx_modulo(pagina.modulo))
                ctx.update({'pagina': pagina, 'creando': creando,
                            'url_volver': reverse(pagina.nombre)})
                return ctx

            def get_success_url(self):
                return reverse(pagina.nombre)

            def form_valid(self, form):
                respuesta = super().form_valid(form)
                if pagina.despues_guardar:
                    pagina.despues_guardar(self.request, self.object, creando)
                messages.success(self.request, 'Registro creado correctamente.' if creando
                                 else 'Cambios guardados correctamente.')
                return respuesta

        return Formulario

    def _crear(self):
        return self._formulario_base(CreateView, True).as_view()

    def _editar(self):
        return self._formulario_base(UpdateView, False).as_view()

    def _eliminar(self):
        pagina = self

        class Eliminar(LoginRequiredMixin, DeleteView):
            template_name = 'core/crud_delete.html'
            model = pagina.modelo

            def get_context_data(self, **kw):
                ctx = super().get_context_data(**kw)
                ctx.update(_ctx_modulo(pagina.modulo))
                ctx.update({'pagina': pagina, 'url_volver': reverse(pagina.nombre)})
                return ctx

            def get_success_url(self):
                return reverse(pagina.nombre)

            def form_valid(self, form):
                try:
                    if pagina.antes_eliminar:
                        pagina.antes_eliminar(self.request, self.object)
                    respuesta = super().form_valid(form)
                except ProtectedError:
                    messages.error(self.request, 'No se puede eliminar: el registro está siendo usado por '
                                                 'otros datos (por ejemplo, citas ya agendadas).')
                    return redirect(reverse(pagina.nombre))
                messages.success(self.request, 'Registro eliminado.')
                return respuesta

        return Eliminar.as_view()


# ======================================================================================
#  Acciones (hooks) de negocio
# ======================================================================================
def _remision_guardada(request, solicitud, creando):
    """Al emitir la remisión pasa a 'Pendiente' y se avisa a los familiares (RF-04 / RF-06)."""
    if solicitud.estado == 'Evaluada':
        solicitud.estado = 'Pendiente'
        solicitud.save(update_fields=['estado'])
        enviados, total = servicios.notificar_familiares(
            solicitud, f'Remisión médica de {solicitud.interno.nombre_completo}',
            servicios.texto_remision(solicitud))
        _mensaje_correo(request, enviados, total)


def _mensaje_correo(request, enviados, total):
    if total == 0:
        messages.warning(request, 'No se envió correo: el interno no tiene familiares con correo registrado.')
    elif enviados == total:
        messages.info(request, f'Correo enviado a {enviados} familiar(es).')
    else:
        messages.warning(request, f'Solo se pudo enviar {enviados} de {total} correos. Revisa la bitácora.')


def _cita_guardada(request, cita, creando):
    sol = cita.solicitud
    if creando:
        sol.estado = 'Agendada'
        sol.save(update_fields=['estado'])
        enviados, total = servicios.notificar_familiares(
            sol, f'Cita médica confirmada para {sol.interno.nombre_completo}', servicios.texto_cita(cita))
        _mensaje_correo(request, enviados, total)


def _cita_por_eliminar(request, cita):
    sol = cita.solicitud
    if sol.estado == 'Agendada':
        sol.estado = 'Pendiente'
        sol.save(update_fields=['estado'])


def _visita_guardada(request, visita, creando):
    if creando and visita.solicitud_id:
        SolicitudRemision.objects.filter(pk=visita.solicitud_id).update(estado='Atendida')


def _resultado_guardado(request, orden, creando):
    if orden.resultado and orden.estado != 'Completada':
        orden.estado = 'Completada'
        orden.save(update_fields=['estado'])


# ======================================================================================
#  Definición de las pantallas
# ======================================================================================
def _resumen_cuentas():
    visitas = VisitaMedica.objects.filter(estado='Cerrada').exclude(estado_pago='Sin cargos')
    neto = visitas.aggregate(t=Sum('total_neto'))['t'] or CERO
    pagado = PagoFundacion.objects.filter(visita__in=visitas).aggregate(t=Sum('monto'))['t'] or CERO
    return [('Total facturado por la Fundación', f'Q{neto:,.2f}'), ('Total pagado', f'Q{pagado:,.2f}'),
            ('Saldo pendiente', f'Q{neto - pagado:,.2f}')]


PAGINAS = [
    # ---- Módulo 1 -----------------------------------------------------------------------------------
    Pagina('expedientes_generales', Interno, 'Expedientes Generales (RF-01)', 1,
           [('ID', 'id'), ('Nombre completo', 'nombre_completo'), ('Nacimiento', 'fecha_nacimiento'),
            ('Motivo de reclusión', 'motivo_reclusion'), ('Estado', 'estado')],
           'Alta, consulta, edición y baja de los expedientes de los internos.',
           form_crear=f.InternoForm, form_editar=f.InternoForm, puede_eliminar=True,
           etiqueta_crear='+ Registrar nuevo interno', enlaces=[('Familiares responsables', 'familiares')],
           texto_eliminar='Se borrarán también sus familiares, solicitudes, visitas y cuotas.'),
    Pagina('familiares', FamiliarResponsable, 'Familiares Responsables', 1,
           [('Interno', 'interno'), ('Nombre', 'nombre_completo'), ('Parentesco', 'parentesco'),
            ('Teléfono', 'telefono'), ('Correo', 'correo_electronico')],
           'Los correos de esta lista reciben las notificaciones automáticas de remisiones y citas.',
           form_crear=['interno', 'nombre_completo', 'parentesco', 'telefono', 'correo_electronico'],
           form_editar=['interno', 'nombre_completo', 'parentesco', 'telefono', 'correo_electronico'],
           puede_eliminar=True, etiqueta_crear='+ Agregar familiar'),
    Pagina('motivos_reclusion', Interno, 'Motivos de Reclusión', 1,
           [('Interno', 'nombre_completo'), ('Motivo de reclusión', 'motivo_reclusion')],
           'Causa por la cual cada interno fue recluido en el asilo.',
           form_editar=['motivo_reclusion'], etiqueta_editar='Editar motivo'),
    Pagina('ficha_medica', Interno, 'Ficha Médica y Medicinas de Cajón (RF-02)', 1,
           [('Interno', 'nombre_completo'), ('Medicinas de cajón', 'medicinas_de_cajon')],
           'Tratamientos fijos permanentes de cada interno.',
           form_editar=['medicinas_de_cajon'], etiqueta_editar='Editar medicinas'),
    Pagina('registro_psicopatologias', Interno, 'Registro de Psicopatologías (RF-02)', 1,
           [('Interno', 'nombre_completo'), ('Psicopatologías', 'psicopatologias')],
           'Psicopatologías diagnosticadas de cada interno.',
           form_editar=['psicopatologias'], etiqueta_editar='Editar psicopatologías'),
    Pagina('historial_clinico', Interno, 'Historial Clínico Digital (RF-03)', 1,
           [('Interno', 'nombre_completo'), ('Estado', 'estado'), ('Psicopatologías', 'psicopatologias')],
           'Vista cronológica de visitas, exámenes, diagnósticos y medicamentos de cada interno.',
           acciones=[{'label': 'Ver historial', 'url': 'historial_detalle'}]),

    # ---- Módulo 2 -----------------------------------------------------------------------------------
    Pagina('evaluaciones_iniciales', SolicitudRemision, 'Evaluaciones Iniciales (RF-04)', 2,
           [('ID', 'id'), ('Fecha', 'fecha_emision'), ('Interno', 'interno'),
            ('Evaluación inicial', 'evaluacion_inicial'), ('Estado', 'estado')],
           'El médico general registra su evaluación. Luego emite la remisión a un especialista.',
           form_crear=['interno', 'evaluacion_inicial'], form_editar=['interno', 'evaluacion_inicial'],
           etiqueta_crear='+ Registrar evaluación',
           acciones=[{'label': 'Emitir remisión', 'url': 'remisiones_web_editar',
                      'cuando': lambda s: s.estado == 'Evaluada'}]),
    Pagina('remisiones_web', SolicitudRemision, 'Solicitudes de Remisión Web (RF-04)', 2,
           [('ID', 'id'), ('Fecha', 'fecha_emision'), ('Interno', 'interno'),
            ('Especialidad', 'especialidad_requerida'), ('Enfermero(a)', 'enfermero_asignado'),
            ('Estado', 'estado')],
           'Remisiones emitidas hacia la Fundación. Al emitirlas se avisa por correo al familiar.',
           form_crear=f.RemisionForm, form_editar=f.RemisionForm, etiqueta_crear='+ Nueva remisión',
           queryset=lambda: SolicitudRemision.objects.exclude(estado='Evaluada'),
           despues_guardar=_remision_guardada),
    Pagina('asignacion_enfermeros', SolicitudRemision, 'Asignación de Enfermeros', 2,
           [('ID', 'id'), ('Interno', 'interno'), ('Especialidad', 'especialidad_requerida'),
            ('Enfermero(a) acompañante', 'enfermero_asignado'), ('Estado', 'estado')],
           'Enfermero(a) que acompaña al interno en el traslado.',
           form_editar=['enfermero_asignado'], etiqueta_editar='Asignar enfermero(a)',
           enlaces=[('Catálogo de enfermeros', 'enfermeros')]),
    Pagina('enfermeros', Enfermero, 'Catálogo de Enfermeros', 2,
           [('Nombre', 'nombre'), ('Teléfono', 'telefono')], '',
           form_crear=['nombre', 'telefono'], form_editar=['nombre', 'telefono'], puede_eliminar=True,
           etiqueta_crear='+ Agregar enfermero(a)'),
    Pagina('medicos', MedicoEspecialista, 'Catálogo de Médicos Especialistas (Fundación)', 2,
           [('Nombre', 'nombre'), ('Especialidad', 'especialidad'), ('Teléfono', 'telefono')], '',
           form_crear=['nombre', 'especialidad', 'telefono'], form_editar=['nombre', 'especialidad', 'telefono'],
           puede_eliminar=True, etiqueta_crear='+ Agregar médico'),
    Pagina('agenda_citas', AgendaCita, 'Agenda de Citas en la Fundación (RF-05)', 2,
           [('ID', 'id'), ('Fecha y hora', 'fecha_hora_cita'), ('Interno', 'solicitud.interno'),
            ('Especialidad', 'solicitud.especialidad_requerida'), ('Médico', 'medico_especialista'),
            ('Estado', 'estado_cita')],
           'La Fundación asigna fecha, hora y médico a las solicitudes pendientes. Se notifica al familiar.',
           form_crear=f.AgendaCitaForm, form_editar=f.AgendaCitaForm, puede_eliminar=True,
           etiqueta_crear='+ Agendar cita', despues_guardar=_cita_guardada, antes_eliminar=_cita_por_eliminar,
           enlaces=[('Catálogo de médicos', 'medicos')]),

    # ---- Módulo 3 -----------------------------------------------------------------------------------
    Pagina('consultas_especializadas', VisitaMedica, 'Consultas Especializadas / Visitas Médicas (RF-07)', 3,
           [('ID', 'id'), ('Fecha', 'fecha_visita'), ('Interno', 'interno'), ('Médico', 'medico_especialista'),
            ('Motivo', 'motivo_visita'), ('Estado', 'estado'), ('Total neto (Q)', 'neto')],
           'La solicitud agendada se convierte en visita médica. Al terminar, cierra la visita para generar los cobros.',
           form_crear=f.VisitaForm, form_editar=f.VisitaForm, etiqueta_crear='+ Iniciar visita médica',
           despues_guardar=_visita_guardada,
           acciones=[{'label': 'Cerrar visita', 'url': 'visita_cerrar', 'post': True,
                      'cuando': lambda v: v.estado == 'Abierta'},
                     {'label': 'Ver historial', 'url': 'historial_detalle_visita'}]),
    Pagina('diagnostico_observaciones', VisitaMedica, 'Diagnóstico y Observaciones', 3,
           [('ID', 'id'), ('Fecha', 'fecha_visita'), ('Interno', 'interno'), ('Diagnóstico', 'diagnostico'),
            ('Observaciones', 'observaciones'), ('Estado', 'estado')],
           'Registro del diagnóstico oficial y las observaciones médicas de cada visita.',
           form_editar=f.DiagnosticoForm, etiqueta_editar='Registrar diagnóstico'),
    Pagina('ordenes_laboratorio', OrdenLaboratorio, 'Órdenes de Laboratorio (RF-08)', 3,
           [('ID', 'id'), ('Visita', 'visita'), ('Examen', 'tipo_examen'), ('Costo base (Q)', 'costo'),
            ('Estado', 'estado')],
           'Exámenes que el especialista ordena durante la visita.',
           form_crear=f.OrdenForm, form_editar=f.OrdenForm, puede_eliminar=True,
           etiqueta_crear='+ Ordenar examen'),
    Pagina('carga_resultados', OrdenLaboratorio, 'Carga de Resultados Digitales (RF-08)', 3,
           [('ID', 'id'), ('Interno', 'visita.interno'), ('Examen', 'tipo_examen'), ('Estado', 'estado'),
            ('Resultado', 'resultado')],
           'El laboratorio registra el resultado para que el médico lo consulte en la visita.',
           form_editar=f.ResultadoForm, etiqueta_editar='Cargar resultado',
           despues_guardar=_resultado_guardado),
    Pagina('recetas_farmacia', RecetaFarmacia, 'Recetas y Despacho de Farmacia (RF-09)', 3,
           [('ID', 'id'), ('Visita', 'visita'), ('Medicamento', 'medicamento'), ('Cantidad', 'cantidad'),
            ('Tiempo', 'tiempo_aplicacion'), ('Costo base (Q)', 'costo'), ('Despachado', 'despachado')],
           'El especialista receta y la farmacia registra la entrega y el costo.',
           form_crear=f.RecetaForm, form_editar=f.RecetaForm, puede_eliminar=True,
           etiqueta_crear='+ Emitir receta',
           acciones=[{'label': 'Despachar', 'url': 'receta_despachar', 'post': True,
                      'cuando': lambda r: not r.despachado}]),

    # ---- Módulo 4 -----------------------------------------------------------------------------------
    Pagina('descuentos_fundacion', DescuentoFundacion, 'Descuentos de la Fundación (RF-10)', 4,
           [('Rubro', 'rubro'), ('Descuento (%)', 'porcentaje'), ('Vigente', 'activo')],
           'Porcentajes que se descuentan automáticamente al cerrar cada visita médica.',
           form_crear=['rubro', 'porcentaje', 'activo'], form_editar=['rubro', 'porcentaje', 'activo'],
           puede_eliminar=True, etiqueta_crear='+ Nuevo descuento'),
    Pagina('cuentas_pagar', VisitaMedica, 'Cuentas por Pagar a la Fundación (RF-11)', 4,
           [('Visita', 'id'), ('Fecha', 'fecha_visita'), ('Interno', 'interno'), ('Total neto (Q)', 'total_neto'),
            ('Pagado (Q)', 'total_pagado'), ('Saldo (Q)', 'saldo'), ('Estado de pago', 'estado_pago')],
           'Visitas cerradas con su deuda hacia la Fundación. Registra los pagos para cancelarlas.',
           queryset=lambda: VisitaMedica.objects.filter(estado='Cerrada').exclude(estado_pago='Sin cargos'),
           acciones=[{'label': 'Registrar pago', 'url': 'pagos_fundacion_nuevo', 'query': 'visita',
                      'cuando': lambda v: v.estado_pago != 'Cancelada'}],
           enlaces=[('Historial de pagos', 'pagos_fundacion')], resumen=_resumen_cuentas),
    Pagina('pagos_fundacion', PagoFundacion, 'Pagos a la Fundación', 4,
           [('ID', 'id'), ('Fecha', 'fecha'), ('Visita', 'visita'), ('Forma de pago', 'forma_pago'),
            ('Monto (Q)', 'monto')], '',
           form_crear=f.PagoFundacionForm, form_editar=f.PagoFundacionForm, puede_eliminar=True,
           etiqueta_crear='+ Registrar pago'),
    Pagina('cargos_cuotas', CuotaFamiliar, 'Cargos y Cuotas de Familiares (RF-12)', 4,
           [('Mes', 'mes_correspondiente'), ('Interno', 'interno'), ('Cuota fija (Q)', 'monto_cuota'),
            ('Cargos médicos (Q)', 'cargos_medicos'), ('Total (Q)', 'total'), ('Pagado', 'pagado'),
            ('Fecha de pago', 'fecha_pago')],
           'Cuota mensual fija + gastos médicos con descuento (se cargan solos al cerrar cada visita).',
           form_crear=f.CuotaForm, form_editar=f.CuotaForm, puede_eliminar=True,
           etiqueta_crear='+ Nueva cuota mensual'),
    Pagina('registro_donaciones', Donacion, 'Registro de Donaciones (RF-13)', 4,
           [('Fecha', 'fecha'), ('Donante', 'donante'), ('Tipo', 'tipo_donacion'), ('Monto (Q)', 'monto')],
           'Donaciones de empresas, gobierno y particulares.',
           form_crear=['donante', 'tipo_donacion', 'monto', 'fecha'],
           form_editar=['donante', 'tipo_donacion', 'monto', 'fecha'], puede_eliminar=True,
           etiqueta_crear='+ Registrar donación'),
    Pagina('gastos_operativos', GastoOperativo, 'Gastos Operativos del Asilo (RF-13)', 4,
           [('Fecha', 'fecha'), ('Concepto', 'concepto'), ('Categoría', 'categoria'), ('Monto (Q)', 'monto')],
           'Luz, agua y otros gastos de funcionamiento.',
           form_crear=['concepto', 'categoria', 'monto', 'fecha'],
           form_editar=['concepto', 'categoria', 'monto', 'fecha'], puede_eliminar=True,
           etiqueta_crear='+ Registrar gasto'),
]

# Se registran por nombre para poder ubicarlas desde urls.py
PAGINAS_POR_NOMBRE = {p.nombre: p for p in PAGINAS}


# ======================================================================================
#  Vistas especiales
# ======================================================================================
@login_required
def dashboard_view(request):
    return render(request, 'core/dashboard.html', {'usuario': request.user})


def _detalle_historial(request, interno, volver):
    visitas = interno.visitas.select_related('medico_especialista').prefetch_related('ordenes', 'recetas') \
        .order_by('fecha_visita', 'id')
    ctx = {'interno': interno, 'visitas': visitas, 'url_volver': volver}
    ctx.update(_ctx_modulo(1))
    return render(request, 'core/historial_detalle.html', ctx)


@login_required
def historial_detalle(request, pk):
    return _detalle_historial(request, get_object_or_404(Interno, pk=pk), reverse('historial_clinico'))


@login_required
def historial_detalle_visita(request, pk):
    """Atajo desde la lista de visitas: abre el historial del interno de esa visita."""
    visita = get_object_or_404(VisitaMedica, pk=pk)
    return _detalle_historial(request, visita.interno, reverse('consultas_especializadas'))


@login_required
@require_POST
def visita_cerrar(request, pk):
    visita = get_object_or_404(VisitaMedica, pk=pk)
    try:
        servicios.cerrar_visita(visita)
        messages.success(request, f'Visita #{visita.pk} cerrada. Total neto: Q{visita.total_neto:,.2f}. '
                                  f'Se cargó a la cuenta del familiar y a la deuda con la Fundación.')
    except ValueError as e:
        messages.error(request, str(e))
    return redirect('consultas_especializadas')


@login_required
@require_POST
def receta_despachar(request, pk):
    receta = get_object_or_404(RecetaFarmacia, pk=pk)
    receta.despachado = True
    receta.save(update_fields=['despachado'])
    messages.success(request, f'Medicamento "{receta.medicamento}" marcado como despachado.')
    return redirect('recetas_farmacia')


@login_required
def notificacion_smtp_view(request):
    ctx = {'solicitudes': SolicitudRemision.objects.exclude(estado='Evaluada').select_related('interno'),
           'bitacora': NotificacionCorreo.objects.select_related('solicitud__interno')[:50]}
    ctx.update(_ctx_modulo(2))
    return render(request, 'core/notificaciones.html', ctx)


@login_required
@require_POST
def notificacion_enviar(request, pk):
    sol = get_object_or_404(SolicitudRemision, pk=pk)
    cita = getattr(sol, 'agendacita', None)
    if cita:
        asunto, cuerpo = f'Cita médica de {sol.interno.nombre_completo}', servicios.texto_cita(cita)
    else:
        asunto, cuerpo = f'Remisión médica de {sol.interno.nombre_completo}', servicios.texto_remision(sol)
    enviados, total = servicios.notificar_familiares(sol, asunto, cuerpo)
    _mensaje_correo(request, enviados, total)
    return redirect('notificacion_smtp')


# ------------------------------------------------------------------ Reportes
def _fecha(texto):
    try:
        return datetime.strptime(texto, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


def pagina_reportes(titulo, claves, descripcion=''):
    @login_required
    def vista(request):
        clave = request.GET.get('r', claves[0])
        if clave not in claves:
            clave = claves[0]
        desde, hasta = _fecha(request.GET.get('desde')), _fecha(request.GET.get('hasta'))
        id_interno = request.GET.get('interno', '')
        interno = Interno.objects.filter(pk=int(id_interno)).first() if id_interno.isdigit() else None
        reporte = REPORTES[clave][1](desde, hasta, interno)

        formato = request.GET.get('formato')
        if formato == 'pdf':
            resp = HttpResponse(exportar_pdf(reporte), content_type='application/pdf')
            resp['Content-Disposition'] = f'attachment; filename="{clave}.pdf"'
            return resp
        if formato == 'xlsx':
            resp = HttpResponse(exportar_xlsx(reporte), content_type=(
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'))
            resp['Content-Disposition'] = f'attachment; filename="{clave}.xlsx"'
            return resp

        params = request.GET.copy()
        params.pop('formato', None)
        params['r'] = clave
        base = params.urlencode()
        ctx = {'titulo_pagina': titulo, 'descripcion': descripcion, 'reporte': reporte, 'clave': clave,
               'pestanas': [(k, REPORTES[k][0]) for k in claves], 'internos': Interno.objects.all(),
               'desde': request.GET.get('desde', ''), 'hasta': request.GET.get('hasta', ''),
               'interno_sel': request.GET.get('interno', ''), 'qs_base': base}
        ctx.update(_ctx_modulo(5))
        return render(request, 'core/reporte.html', ctx)

    return vista


reportes_clinicos_view = pagina_reportes('Reportes Clínicos por Paciente (RF-14)',
                                         ['clinico', 'examenes', 'medicamentos'],
                                         'Ficha médica, exámenes y medicamentos aplicados.')
balance_ingresos_view = pagina_reportes('Balance de Ingresos y Donaciones (RF-15)', ['ingresos', 'cobros'],
                                        'Entradas por donaciones y cobros a familiares.')
estado_egreso_view = pagina_reportes('Estado de Egresos Operativos (RF-15)', ['egresos', 'pagos_fundacion'],
                                     'Gastos operativos, pagos a la Fundación y balance.')
control_costos_view = pagina_reportes('Control de Costos por Cita (RF-15)', ['costos'],
                                      'Costo de cada cita: consulta, laboratorio y farmacia con descuento.')
exportacion_pdf_excel_view = pagina_reportes('Exportación a PDF y Excel (RF-15)', list(REPORTES.keys()),
                                             'Elige el reporte, el período y descárgalo.')

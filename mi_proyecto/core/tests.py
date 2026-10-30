from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    AgendaCita, CuotaFamiliar, DescuentoFundacion, FamiliarResponsable, Enfermero, Interno,
    MedicoEspecialista, OrdenLaboratorio, PagoFundacion, RecetaFarmacia, SolicitudRemision, VisitaMedica,
)


class FlujoCompletoTest(TestCase):
    """Recorre el flujo del enunciado: evaluación -> remisión -> cita -> visita -> cobros -> pago."""

    def setUp(self):
        User.objects.create_user('admin', password='clave12345')
        self.client.login(username='admin', password='clave12345')
        self.interno = Interno.objects.create(nombre_completo='Juan Pérez', motivo_reclusion='Abandono familiar')
        FamiliarResponsable.objects.create(interno=self.interno, nombre_completo='Ana Pérez', parentesco='Hija',
                                           telefono='5555-0000', correo_electronico='ana@example.com')
        self.enf = Enfermero.objects.create(nombre='Elena Gómez')
        self.medico = MedicoEspecialista.objects.create(nombre='Carlos Herrera', especialidad='Cardiología')
        for rubro, pct in (('Consulta', 20), ('Laboratorio', 10), ('Farmacia', 50)):
            DescuentoFundacion.objects.create(rubro=rubro, porcentaje=pct)

    def test_todas_las_pantallas_cargan(self):
        for nombre in ['dashboard', 'expedientes_generales', 'familiares', 'motivos_reclusion', 'ficha_medica',
                       'registro_psicopatologias', 'historial_clinico', 'evaluaciones_iniciales', 'remisiones_web',
                       'asignacion_enfermeros', 'agenda_citas', 'notificacion_smtp', 'consultas_especializadas',
                       'diagnostico_observaciones', 'ordenes_laboratorio', 'carga_resultados', 'recetas_farmacia',
                       'descuentos_fundacion', 'cuentas_pagar', 'cargos_cuotas', 'registro_donaciones',
                       'gastos_operativos', 'reportes_clinicos', 'balance_ingresos', 'estado_egreso',
                       'control_costos', 'exportacion_pdf_excel']:
            self.assertEqual(self.client.get(reverse(nombre)).status_code, 200, nombre)

    def test_flujo(self):
        # Evaluación + remisión (RF-04) -> correo al familiar (RF-06)
        sol = SolicitudRemision.objects.create(interno=self.interno, evaluacion_inicial='Arritmia')
        r = self.client.post(reverse('remisiones_web_editar', args=[sol.pk]), {
            'interno': self.interno.pk, 'evaluacion_inicial': 'Arritmia',
            'especialidad_requerida': 'Cardiología', 'enfermero_asignado': self.enf.pk})
        self.assertEqual(r.status_code, 302)
        sol.refresh_from_db()
        self.assertEqual(sol.estado, 'Pendiente')
        self.assertEqual(len(mail.outbox), 1)

        # Agenda de la Fundación (RF-05) -> segundo correo
        cuando = (timezone.localtime() + timedelta(days=3)).strftime('%Y-%m-%dT%H:%M')
        r = self.client.post(reverse('agenda_citas_nuevo'), {
            'solicitud': sol.pk, 'fecha_hora_cita': cuando, 'medico_especialista': self.medico.pk,
            'estado_cita': 'Agendada'})
        self.assertEqual(r.status_code, 302, getattr(r, 'context', None) and r.context['form'].errors)
        sol.refresh_from_db()
        self.assertEqual(sol.estado, 'Agendada')
        self.assertEqual(len(mail.outbox), 2)

        # Visita médica (RF-07)
        r = self.client.post(reverse('consultas_especializadas_nuevo'), {
            'solicitud': sol.pk, 'fecha_visita': timezone.localdate().isoformat(), 'costo_consulta': '200.00'})
        self.assertEqual(r.status_code, 302, getattr(r, 'context', None) and r.context['form'].errors)
        visita = VisitaMedica.objects.get()
        self.assertEqual(visita.interno, self.interno)
        OrdenLaboratorio.objects.create(visita=visita, tipo_examen='Perfil lipídico', costo=Decimal('100'))
        RecetaFarmacia.objects.create(visita=visita, medicamento='Losartán', cantidad=30,
                                      tiempo_aplicacion='30 días', costo=Decimal('50'))
        visita.diagnostico = 'Hipertensión'
        visita.save()

        # Cierre (RF-10/11/12): 200*0.8 + 100*0.9 + 50*0.5 = 160 + 90 + 25 = 275
        self.client.post(reverse('visita_cerrar', args=[visita.pk]))
        visita.refresh_from_db()
        self.assertEqual(visita.estado, 'Cerrada')
        self.assertEqual(visita.total_neto, Decimal('275.00'))
        self.assertEqual(visita.estado_pago, 'Pendiente de pago')
        self.assertEqual(CuotaFamiliar.objects.get().cargos_medicos, Decimal('275.00'))

        # No se puede cerrar dos veces (no duplica cargos)
        self.client.post(reverse('visita_cerrar', args=[visita.pk]))
        self.assertEqual(CuotaFamiliar.objects.get().cargos_medicos, Decimal('275.00'))

        # Pago parcial y total a la Fundación
        PagoFundacion.objects.create(visita=visita, monto=Decimal('100'))
        visita.refresh_from_db()
        self.assertEqual(visita.estado_pago, 'Pago parcial')
        PagoFundacion.objects.create(visita=visita, monto=Decimal('175'))
        visita.refresh_from_db()
        self.assertEqual(visita.estado_pago, 'Cancelada')

    def test_exportaciones(self):
        for formato, tipo in (('pdf', 'application/pdf'), ('xlsx', 'spreadsheetml')):
            r = self.client.get(reverse('exportacion_pdf_excel'), {'r': 'costos', 'formato': formato})
            self.assertEqual(r.status_code, 200)
            self.assertIn(tipo, r['Content-Type'])

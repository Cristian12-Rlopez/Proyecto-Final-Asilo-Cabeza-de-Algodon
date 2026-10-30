import re

from django import forms
from django.utils import timezone

from .models import (
    AgendaCita, CuotaFamiliar, Interno, OrdenLaboratorio, PagoFundacion,
    RecetaFarmacia, SolicitudRemision, VisitaMedica,
)

CLASE = ('w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none '
         'focus:ring-2 focus:ring-emerald-500')


class BaseForm(forms.ModelForm):
    """Aplica estilo Tailwind y widgets de fecha a todos los formularios."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in self.fields.values():
            w = campo.widget
            if isinstance(w, forms.CheckboxInput):
                w.attrs['class'] = 'h-4 w-4'
                continue
            if isinstance(campo, forms.DateTimeField):
                campo.widget = w = forms.DateTimeInput(attrs={'type': 'datetime-local'},
                                                       format='%Y-%m-%dT%H:%M')
                campo.input_formats = ['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M']
            elif isinstance(campo, forms.DateField):
                campo.widget = w = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')
            if isinstance(w, forms.Textarea):
                w.attrs['rows'] = 3
            w.attrs['class'] = CLASE


def _bloquear_si_cerrada(visita):
    if visita is not None and visita.estado == 'Cerrada':
        raise forms.ValidationError('La visita médica ya está cerrada; no se pueden agregar ni '
                                    'modificar cargos.')


# ------------------------------------------------------------------ Módulo 1
class InternoForm(BaseForm):
    class Meta:
        model = Interno
        fields = ['nombre_completo', 'fecha_nacimiento', 'motivo_reclusion', 'psicopatologias',
                  'medicinas_de_cajon', 'estado']


# ------------------------------------------------------------------ Módulo 2
class RemisionForm(BaseForm):
    """Emisión de la solicitud de remisión web (RF-04)."""

    class Meta:
        model = SolicitudRemision
        fields = ['interno', 'evaluacion_inicial', 'especialidad_requerida', 'enfermero_asignado']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['especialidad_requerida'].required = True
        self.fields['enfermero_asignado'].required = True

    def clean(self):
        datos = super().clean()
        if self.instance.pk and self.instance.estado in ('Agendada', 'Atendida'):
            raise forms.ValidationError('La solicitud ya tiene cita agendada; no puede modificarse.')
        return datos


class AgendaCitaForm(BaseForm):
    class Meta:
        model = AgendaCita
        fields = ['solicitud', 'fecha_hora_cita', 'medico_especialista', 'estado_cita']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['solicitud'].queryset = SolicitudRemision.objects.filter(pk=self.instance.solicitud_id)
            self.fields['solicitud'].disabled = True
        else:
            self.fields['solicitud'].queryset = SolicitudRemision.objects.filter(estado='Pendiente')
            self.fields['estado_cita'].initial = 'Agendada'
        self.fields['solicitud'].label_from_instance = (
            lambda s: f'#{s.pk} - {s.interno} ({s.especialidad_requerida})')


# ------------------------------------------------------------------ Módulo 3
class VisitaForm(BaseForm):
    class Meta:
        model = VisitaMedica
        fields = ['solicitud', 'interno', 'medico_especialista', 'fecha_visita', 'motivo_visita',
                  'costo_consulta']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['solicitud'].required = False
        self.fields['interno'].required = False
        self.fields['medico_especialista'].required = False
        self.fields['motivo_visita'].required = False
        self.fields['solicitud'].help_text = ('Elige la solicitud con cita agendada: el interno, el médico '
                                              'y el motivo se completan solos.')
        if self.instance.pk:
            self.fields['solicitud'].queryset = SolicitudRemision.objects.filter(pk=self.instance.solicitud_id)
        else:
            self.fields['solicitud'].queryset = SolicitudRemision.objects.filter(estado='Agendada')
            self.fields['fecha_visita'].initial = timezone.localdate()
        self.fields['solicitud'].label_from_instance = (
            lambda s: f'#{s.pk} - {s.interno} ({s.especialidad_requerida})')

    def clean(self):
        datos = super().clean()
        if self.instance.pk and self.instance.estado == 'Cerrada':
            raise forms.ValidationError('La visita está cerrada y no puede modificarse.')
        sol = datos.get('solicitud')
        if sol:
            datos['interno'] = sol.interno
            cita = getattr(sol, 'agendacita', None)
            if not datos.get('medico_especialista') and cita:
                datos['medico_especialista'] = cita.medico_especialista
            if not datos.get('motivo_visita'):
                datos['motivo_visita'] = f'Remisión a {sol.especialidad_requerida}: {sol.evaluacion_inicial}'[:250]
        if not datos.get('interno'):
            self.add_error('interno', 'Selecciona una solicitud o indica el interno.')
        if not datos.get('motivo_visita'):
            self.add_error('motivo_visita', 'Indica el motivo de la visita.')
        if not datos.get('medico_especialista'):
            self.add_error('medico_especialista', 'Indica el médico tratante.')
        return datos

    def _post_clean(self):
        # copiar a la instancia los valores deducidos en clean()
        for campo in ('interno', 'medico_especialista', 'motivo_visita'):
            if campo in self.cleaned_data:
                setattr(self.instance, campo, self.cleaned_data[campo])
        super()._post_clean()


class DiagnosticoForm(BaseForm):
    class Meta:
        model = VisitaMedica
        fields = ['diagnostico', 'observaciones']

    def clean(self):
        datos = super().clean()
        if self.instance.estado == 'Cerrada':
            raise forms.ValidationError('La visita está cerrada y no puede modificarse.')
        return datos


class OrdenForm(BaseForm):
    class Meta:
        model = OrdenLaboratorio
        fields = ['visita', 'tipo_examen', 'costo']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['visita'].queryset = VisitaMedica.objects.filter(estado='Abierta')
        if self.instance.pk:
            self.fields['visita'].queryset = VisitaMedica.objects.filter(pk=self.instance.visita_id)
        self.fields['costo'].help_text = 'Tarifa base; el descuento de la Fundación se aplica al cerrar la visita.'

    def clean_visita(self):
        v = self.cleaned_data['visita']
        _bloquear_si_cerrada(v)
        return v


class ResultadoForm(BaseForm):
    class Meta:
        model = OrdenLaboratorio
        fields = ['resultado']

    def clean_resultado(self):
        r = self.cleaned_data['resultado'].strip()
        if not r:
            raise forms.ValidationError('Escribe el resultado del examen.')
        return r


class RecetaForm(BaseForm):
    class Meta:
        model = RecetaFarmacia
        fields = ['visita', 'medicamento', 'cantidad', 'tiempo_aplicacion', 'indicaciones', 'costo']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['visita'].queryset = VisitaMedica.objects.filter(pk=self.instance.visita_id)
        else:
            self.fields['visita'].queryset = VisitaMedica.objects.filter(estado='Abierta')

    def clean_visita(self):
        v = self.cleaned_data['visita']
        _bloquear_si_cerrada(v)
        return v


# ------------------------------------------------------------------ Módulo 4
class PagoFundacionForm(BaseForm):
    class Meta:
        model = PagoFundacion
        fields = ['visita', 'fecha', 'monto', 'forma_pago']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['visita'].queryset = VisitaMedica.objects.filter(estado='Cerrada').exclude(
            estado_pago__in=['Sin cargos'])

    def clean_monto(self):
        m = self.cleaned_data['monto']
        if m <= 0:
            raise forms.ValidationError('El monto debe ser mayor que cero.')
        return m

    def clean(self):
        datos = super().clean()
        visita, monto = datos.get('visita'), datos.get('monto')
        if visita and monto:
            saldo = visita.saldo + (self.instance.monto if self.instance.pk else 0)
            if monto > saldo:
                self.add_error('monto', f'El monto excede el saldo pendiente de la visita (Q{saldo:,.2f}).')
        return datos


class CuotaForm(BaseForm):
    class Meta:
        model = CuotaFamiliar
        fields = ['interno', 'mes_correspondiente', 'monto_cuota', 'pagado', 'fecha_pago']

    def clean_mes_correspondiente(self):
        mes = self.cleaned_data['mes_correspondiente'].strip()
        if not re.match(r'^\d{4}-(0[1-9]|1[0-2])$', mes):
            raise forms.ValidationError('Usa el formato AAAA-MM, por ejemplo 2026-10.')
        return mes

    def clean(self):
        datos = super().clean()
        if datos.get('pagado') and not datos.get('fecha_pago'):
            datos['fecha_pago'] = timezone.localdate()
        return datos

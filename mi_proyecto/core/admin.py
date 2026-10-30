from django.contrib import admin

from . import models

admin.site.site_header = 'Administración Asilo Cabeza de Algodón'
admin.site.site_title = 'Asilo Cabeza de Algodón'
admin.site.index_title = 'Gestión Integral del Sistema'

for modelo in (models.Interno, models.FamiliarResponsable, models.MedicoEspecialista, models.Enfermero,
               models.SolicitudRemision, models.AgendaCita, models.VisitaMedica, models.OrdenLaboratorio,
               models.RecetaFarmacia, models.DescuentoFundacion, models.PagoFundacion, models.CuotaFamiliar,
               models.Donacion, models.GastoOperativo, models.NotificacionCorreo):
    admin.site.register(modelo)

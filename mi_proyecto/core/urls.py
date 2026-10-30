from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path('login/', auth_views.LoginView.as_view(template_name='core/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('dashboard/', views.dashboard_view, name='dashboard'),

    # Historial clínico (detalle) y acciones de negocio
    path('historial-clinico/interno/<int:pk>/', views.historial_detalle, name='historial_detalle'),
    path('visitas/<int:pk>/historial/', views.historial_detalle_visita, name='historial_detalle_visita'),
    path('visitas/<int:pk>/cerrar/', views.visita_cerrar, name='visita_cerrar'),
    path('recetas/<int:pk>/despachar/', views.receta_despachar, name='receta_despachar'),
    path('notificacion-smtp/', views.notificacion_smtp_view, name='notificacion_smtp'),
    path('notificacion-smtp/<int:pk>/enviar/', views.notificacion_enviar, name='notificacion_enviar'),

    # Reportes (Módulo 5)
    path('reportes-clinicos/', views.reportes_clinicos_view, name='reportes_clinicos'),
    path('balance-ingresos/', views.balance_ingresos_view, name='balance_ingresos'),
    path('estado-egreso/', views.estado_egreso_view, name='estado_egreso'),
    path('control-costos/', views.control_costos_view, name='control_costos'),
    path('exportacion-pdf-excel/', views.exportacion_pdf_excel_view, name='exportacion_pdf_excel'),
]

# Pantallas CRUD generadas desde views.PAGINAS (listar / nuevo / editar / eliminar)
for _pagina in views.PAGINAS:
    urlpatterns += _pagina.urls(_pagina.nombre.replace('_', '-'))

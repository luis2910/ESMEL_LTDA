from django.urls import path
from django.contrib.auth import views as auth_views
from .views import (
    inicio, nosotros, registro_view, login_view, logout_view, perfil_view,
    perfil_editar, admin_dashboard, admin_dashboard_stats, agenda_visitas, agenda_visita_editar, agenda_visita_eliminar, tecnicos_panel,
    servicios_list, servicio_detalle,
    contacto, cotizacion_create, cotizacion_mis, cotizaciones_admin_list, cotizaciones_registro, gestion_insumos, agenda_calendario,
    cotizacion_rechazar, cotizacion_aceptar, cotizacion_enviar, cotizacion_responder, cotizacion_informe, cotizacion_pagar,
    tb_return,
    documentos_admin, documentos_list,
    password_code_request, password_code_verify,
    password_question_start, password_question_answer,
    documento_editar, documento_eliminar,
    servicios_admin_list, servicio_crear, servicio_editar, servicio_eliminar,
    login_2fa_verify, login_2fa_approve,
)

urlpatterns = [
    path("", inicio, name="index"),
    path("nosotros/", nosotros, name="nosotros"),

    # Auth
    path("registro/", registro_view, name="registro"),
    path("login/", login_view, name="login"),
    path("login/verify/", login_2fa_verify, name="login_2fa_verify"),
    path("login/approve/<str:token>/", login_2fa_approve, name="login_2fa_approve"),
    path("logout/", logout_view, name="logout"),
    path("perfil/", perfil_view, name="perfil"),
    path("perfil/editar/", perfil_editar, name="perfil_editar"),
    path("administrar/", admin_dashboard, name="admin_dashboard"),
    path("administrar/stats/", admin_dashboard_stats, name="admin_stats_api"),
    path("agenda/", agenda_visitas, name="agenda_visitas"),
    path("agenda/<int:pk>/editar/", agenda_visita_editar, name="agenda_visita_editar"),
    path("agenda/<int:pk>/eliminar/", agenda_visita_eliminar, name="agenda_visita_eliminar"),
    path("agenda/calendario/", agenda_calendario, name="agenda_calendario"),
    path("tecnicos/", tecnicos_panel, name="tecnicos_panel"),

    # Servicios públicos
    # Servicios admin CRUD (antes del slug)
    path("servicios/admin/", servicios_admin_list, name="servicios_admin_crud"),
    path("servicios/admin/nuevo/", servicio_crear, name="servicio_crear"),
    path("servicios/admin/<int:pk>/editar/", servicio_editar, name="servicio_editar"),
    path("servicios/admin/<int:pk>/eliminar/", servicio_eliminar, name="servicio_eliminar"),
    # Servicios públicos
    path("servicios/", servicios_list, name="servicios"),
    path("servicios/<slug:slug>/", servicio_detalle, name="servicio_detalle"),

    # Cotizaciones (requiere login)
    path("cotizacion/nueva/", cotizacion_create, name="cotizacion_nueva"),
    path("cotizaciones/mis/", cotizacion_mis, name="cotizacion_mis"),
    path("cotizaciones/mis/<int:pk>/responder/", cotizacion_responder, name="cotizacion_responder"),
    path("cotizaciones/admin/", cotizaciones_admin_list, name="cotizaciones_admin"),
    path("cotizaciones/registro/", cotizaciones_registro, name="cotizaciones_registro"),
    path("insumos/gestion/", gestion_insumos, name="gestion_insumos"),
    path("cotizaciones/<int:pk>/enviar/", cotizacion_enviar, name="cotizacion_enviar"),
    path("cotizaciones/<int:pk>/rechazar/", cotizacion_rechazar, name="cotizacion_rechazar"),
    path("cotizaciones/<int:pk>/aceptar/", cotizacion_aceptar, name="cotizacion_aceptar"),
    path("cotizaciones/<int:pk>/informe/", cotizacion_informe, name="cotizacion_informe"),
    path("cotizaciones/<int:pk>/pagar/", cotizacion_pagar, name="cotizacion_pagar"),
    path("pagos/tb/return/", tb_return, name="tb_return"),

    # Contacto
    path("contacto/", contacto, name="contacto"),
    # Sección solo para administradores
    path("documentos/", documentos_admin, name="documentos_admin"),
    # Listado público de documentos
    path("documentos/lista/", documentos_list, name="documentos_list"),
    path("documentos/editar/<int:pk>/", documento_editar, name="documento_editar"),
    path("documentos/eliminar/<int:pk>/", documento_eliminar, name="documento_eliminar"),
    
    # Recuperar / restablecer contraseña (Django auth views)
    path("password-reset/", auth_views.PasswordResetView.as_view(
        template_name="menu/password_reset.html",
        email_template_name="registration/password_reset_email.html",
        subject_template_name="registration/password_reset_subject.txt",
    ), name="password_reset"),
    path("password-reset/done/", auth_views.PasswordResetDoneView.as_view(
        template_name="menu/password_reset_done.html"
    ), name="password_reset_done"),
    path("reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(
        template_name="menu/password_reset_confirm.html"
    ), name="password_reset_confirm"),
    path("reset/done/", auth_views.PasswordResetCompleteView.as_view(
        template_name="menu/password_reset_complete.html"
    ), name="password_reset_complete"),

    # Recuperación por código (alternativa)
    path("password-code/", password_code_request, name="password_code_request"),
    path("password-code/verify/", password_code_verify, name="password_code_verify"),

    # Recuperacion por pregunta
    path("password-question/", password_question_start, name="password_question_start"),
    path("password-question/answer/", password_question_answer, name="password_question_answer"),
]


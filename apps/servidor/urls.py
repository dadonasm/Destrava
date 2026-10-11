from django.urls import path, re_path

from . import views

# caminhos com segmento livre (<str:>) e validação nas regras (MID_RE / ARQ_RE), como no servidor antigo
urlpatterns = [
    path("healthz", views.healthz),
    path("iniciar.sh", views.script, {"nome": "iniciar.sh"}),
    path("iniciar.ps1", views.script, {"nome": "iniciar.ps1"}),
    path("api/quem", views.quem),
    path("pacote/info", views.pacote_info),
    path("pacote/Destrava.zip", views.pacote_zip),
    re_path(r"^runtime/(?P<nome>[^/]+)$", views.runtime),
    path("api/maquinas", views.maquinas),
    re_path(r"^api/maquina/(?P<mid>[^/]+)$", views.maquina),
    re_path(r"^api/maquina/(?P<mid>[^/]+)/(?P<arquivo>.+)$", views.maquina_arquivo),  # nome com "/" ou "..": ARQ_RE recusa com 400
    path("api/log", views.log_view),
    path("api/log/verificar", views.log_verificar),
    path("api/resolver", views.resolver),
]

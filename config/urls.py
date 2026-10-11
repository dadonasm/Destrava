from django.urls import include, path

# erros em JSON, nunca a página HTML de erro do Django (R2)
handler404 = "apps.servidor.views.nao_encontrado"
handler500 = "apps.servidor.views.erro_interno"

urlpatterns = [
    path("", include("apps.servidor.urls")),
    path("", include("apps.home.urls")),
]

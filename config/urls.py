from django.urls import include, path

urlpatterns = [
    path("", include("apps.servidor.urls")),
    path("", include("apps.home.urls")),
]

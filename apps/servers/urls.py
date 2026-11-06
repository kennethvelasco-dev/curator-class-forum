from django.urls import path

from apps.servers import views


app_name = "servers"
urlpatterns = [
    path("request/", views.server_request, name="server_request"),
    path(
        "request/<int:request_id>/cor/",
        views.server_request_cor,
        name="server_request_cor",
    ),
]

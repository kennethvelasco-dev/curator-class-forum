from django.urls import path

from apps.servers import views


app_name = "servers"
urlpatterns = [
    path("request/", views.server_request, name="server_request"),
    path(
        "admin/server-requests/",
        views.admin_server_request_queue,
        name="admin_server_request_queue",
    ),
    path(
        "admin/server-requests/<int:request_id>/decision/",
        views.decide_server_request_view,
        name="decide_server_request",
    ),
    path(
        "request/<int:request_id>/cor/",
        views.server_request_cor,
        name="server_request_cor",
    ),
]

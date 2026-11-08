from django.urls import path

from apps.servers import views


app_name = "servers"
urlpatterns = [
    path("request/", views.server_request, name="server_request"),
    path("join/", views.join_request, name="join_request"),
    path("join/queue/", views.join_request_queue, name="join_request_queue"),
    path(
        "join/<int:request_id>/decision/",
        views.decide_join_request_view,
        name="decide_join_request",
    ),
    path(
        "join/<int:request_id>/cor/",
        views.join_request_cor,
        name="join_request_cor",
    ),
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
    path("switch/", views.switch_server, name="switch_server"),
    path(
        "<int:server_id>/transfer-presidency/",
        views.transfer_presidency_view,
        name="transfer_presidency",
    ),
]

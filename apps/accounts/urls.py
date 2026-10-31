from django.urls import path

from apps.accounts import views

app_name = "accounts"
urlpatterns = [
    path("register/", views.register, name="register"),
    path(
        "registration/complete/",
        views.registration_complete,
        name="registration_complete",
    ),
    path(
        "verify/<int:user_id>/<str:token>/",
        views.verify_email,
        name="verify_email",
    ),
]

"""Views for account pages and authentication."""

from django.conf import settings
from django.core.mail import send_mail
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from apps.accounts.forms import RegistrationForm
from apps.accounts.models import User
from apps.accounts.tokens import (
    consume_email_verification_token,
    is_email_verification_token_valid,
    issue_email_verification_token,
)


def register(request):
    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            verification_url = request.build_absolute_uri(
                reverse(
                    "accounts:verify_email",
                    args=[user.pk, issue_email_verification_token(user)],
                )
            )
            send_mail(
                subject="Verify your Curator email address",
                message=(
                    f"Hello {user.full_name},\n\n"
                    "Confirm your email address by opening this link:\n"
                    f"{verification_url}\n\n"
                    "The link expires in 24 hours. Opening it will not verify "
                    "your account; you must confirm on the page."
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
            )
            return redirect("accounts:registration_complete")
    else:
        form = RegistrationForm()

    return render(request, "accounts/register.html", {"form": form})


def registration_complete(request):
    return render(request, "accounts/registration_complete.html")


@never_cache
@require_http_methods(["GET", "POST"])
def verify_email(request, user_id, token):
    user = User.objects.filter(pk=user_id).first()
    valid_token = (
        user is not None
        and not user.is_email_verified
        and is_email_verification_token_valid(user_id, token)
    )
    if not valid_token:
        response = render(
            request,
            "accounts/verification_result.html",
            {
                "success": False,
                "message": "This verification link is invalid or expired.",
            },
            status=400,
        )
        response["Referrer-Policy"] = "no-referrer"
        return response

    if request.method == "POST":
        if consume_email_verification_token(user_id, token):
            response = render(
                request,
                "accounts/verification_result.html",
                {
                    "success": True,
                    "message": "Your email address is verified. You can now sign in.",
                },
            )
            response["Referrer-Policy"] = "no-referrer"
            return response
        message = "This verification link is invalid, expired, or has already been used."
        status = 400
    else:
        message = "Confirm that you want to verify this email address."
        status = 200

    response = render(
        request,
        (
            "accounts/verify_email.html"
            if request.method == "GET"
            else "accounts/verification_result.html"
        ),
        {"user": user, "token": token, "success": False, "message": message},
        status=status,
    )
    response["Referrer-Policy"] = "no-referrer"
    return response

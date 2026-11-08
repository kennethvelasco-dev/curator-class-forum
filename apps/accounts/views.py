"""Views for account pages and authentication."""

import hashlib
import smtplib
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.views import LoginView, LogoutView
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from apps.accounts.decorators import verified_required
from apps.accounts.forms import (
    EmailAuthenticationForm,
    RegistrationEmailForm,
    RegistrationForm,
)
from apps.accounts.models import PendingRegistration, User
from apps.accounts.tokens import (
    consume_email_verification_token_hash,
    email_verification_token_hash,
    is_email_verification_token_hash_valid,
    is_email_verification_token_valid,
    issue_email_verification_token,
    issue_registration_token,
)
from apps.servers.models import Membership, MembershipRole, MembershipStatus

REGISTRATION_VERIFICATION_SESSION_KEY = "accounts.registration_verification"
EMAIL_VERIFICATION_SESSION_KEY = "accounts.email_verification"
# Form pages use tokenless URLs, so same-origin Referer headers cannot expose link tokens.
CLEAN_FORM_REFERRER_POLICY = "same-origin"


def _store_verification_state(request, session_key, object_id, token_hash):
    request.session.cycle_key()
    states = request.session.get(session_key, {})
    if not isinstance(states, dict):
        states = {}
    states[str(object_id)] = token_hash
    request.session[session_key] = states


def _get_verification_state(request, session_key, object_id):
    states = request.session.get(session_key, {})
    if not isinstance(states, dict):
        return None
    token_hash = states.get(str(object_id))
    return token_hash if isinstance(token_hash, str) else None


def _clear_verification_state(request, session_key, object_id):
    states = request.session.get(session_key, {})
    if not isinstance(states, dict):
        request.session.pop(session_key, None)
        return
    states.pop(str(object_id), None)
    if states:
        request.session[session_key] = states
    else:
        request.session.pop(session_key, None)


def register(request):
    if request.method == "POST":
        form = RegistrationEmailForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data["email"]
            if User.objects.filter(email=email, is_email_verified=True).exists():
                return redirect("accounts:registration_complete")

            email_failed = False
            with transaction.atomic():
                pending = (
                    PendingRegistration.objects.select_for_update()
                    .filter(email=email)
                    .first()
                )
                expires_at = timezone.now() - timedelta(
                    seconds=settings.EMAIL_VERIFICATION_TOKEN_TTL
                )
                if pending is not None and pending.created_at < expires_at:
                    pending.delete()
                    pending = None

                raw_token = None
                if pending is None:
                    pending, raw_token = issue_registration_token(email)

                if raw_token is not None:
                    verification_url = request.build_absolute_uri(
                        reverse(
                            "accounts:complete_registration",
                            args=[pending.pk, raw_token],
                        )
                    )
                    try:
                        sent_count = send_mail(
                            subject="Complete your Curator registration",
                            message=(
                                "To continue creating a Curator account for "
                                f"{email}, open this link:\n{verification_url}\n\n"
                                "The link expires in 24 hours. Opening it will not "
                                "create an account; submit the form on the page to "
                                "verify your email, set your password, and record "
                                "your consent."
                            ),
                            from_email=settings.DEFAULT_FROM_EMAIL,
                            recipient_list=[email],
                        )
                    except (smtplib.SMTPException, OSError):
                        sent_count = 0

                    if sent_count != 1:
                        transaction.set_rollback(True)
                        form.add_error(
                            None,
                            "We could not send the verification email. Please try again.",
                        )
                        email_failed = True

            if not email_failed:
                return redirect("accounts:registration_complete")
    else:
        form = RegistrationEmailForm()

    return render(request, "accounts/register.html", {"form": form})


def registration_complete(request):
    return render(request, "accounts/registration_complete.html")


@verified_required
def dashboard(request):
    has_active_president_membership = Membership.objects.filter(
        user=request.user,
        role=MembershipRole.PRESIDENT,
        status=MembershipStatus.ACTIVE,
    ).exists()
    return render(
        request,
        "accounts/dashboard.html",
        {"has_active_president_membership": has_active_president_membership},
    )


@never_cache
@require_http_methods(["GET"])
def complete_registration(request, registration_id, token):
    expires_at = timezone.now() - timedelta(
        seconds=settings.EMAIL_VERIFICATION_TOKEN_TTL
    )
    pending = PendingRegistration.objects.filter(
        pk=registration_id,
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        created_at__gte=expires_at,
    ).first()
    if pending is None:
        return _verification_failure(
            request,
            "This registration link is invalid or expired.",
        )

    _store_verification_state(
        request,
        REGISTRATION_VERIFICATION_SESSION_KEY,
        registration_id,
        pending.token_hash,
    )
    response = redirect(
        "accounts:complete_registration_form",
        registration_id=registration_id,
    )
    response["Referrer-Policy"] = "no-referrer"
    return response


@never_cache
@require_http_methods(["GET", "POST"])
def complete_registration_form(request, registration_id):
    token_hash = _get_verification_state(
        request,
        REGISTRATION_VERIFICATION_SESSION_KEY,
        registration_id,
    )
    if token_hash is None:
        return _verification_failure(
            request,
            "This registration link is invalid or expired.",
        )

    expires_at = timezone.now() - timedelta(
        seconds=settings.EMAIL_VERIFICATION_TOKEN_TTL
    )
    pending = PendingRegistration.objects.filter(
        pk=registration_id,
        token_hash=token_hash,
        created_at__gte=expires_at,
    ).first()
    if pending is None:
        _clear_verification_state(
            request,
            REGISTRATION_VERIFICATION_SESSION_KEY,
            registration_id,
        )
        return _verification_failure(
            request,
            "This registration link is invalid or expired.",
        )

    form = RegistrationForm(
        request.POST if request.method == "POST" else None,
        email=pending.email,
    )
    if request.method == "GET":
        return _render_registration_completion(
            request,
            pending,
            form,
        )

    if not form.is_valid():
        return _render_registration_completion(
            request,
            pending,
            form,
        )

    try:
        with transaction.atomic():
            pending = (
                PendingRegistration.objects.select_for_update()
                .filter(
                    pk=registration_id,
                    token_hash=token_hash,
                    created_at__gte=timezone.now()
                    - timedelta(seconds=settings.EMAIL_VERIFICATION_TOKEN_TTL),
                )
                .first()
            )
            if pending is None:
                _clear_verification_state(
                    request,
                    REGISTRATION_VERIFICATION_SESSION_KEY,
                    registration_id,
                )
                return _verification_failure(
                    request,
                    "This registration link is invalid, expired, or has already "
                    "been used.",
                )

            existing_user = (
                User.objects.select_for_update()
                .filter(email=pending.email)
                .first()
            )
            if existing_user is not None and existing_user.is_email_verified:
                _clear_verification_state(
                    request,
                    REGISTRATION_VERIFICATION_SESSION_KEY,
                    registration_id,
                )
                return _verification_failure(
                    request,
                    "This registration link is invalid or has already been used.",
                )

            form.create_user(pending.email)
            pending.delete()
            _clear_verification_state(
                request,
                REGISTRATION_VERIFICATION_SESSION_KEY,
                registration_id,
            )
    except IntegrityError:
        _clear_verification_state(
            request,
            REGISTRATION_VERIFICATION_SESSION_KEY,
            registration_id,
        )
        return _verification_failure(
            request,
            "This registration link is invalid or has already been used.",
        )

    response = render(
        request,
        "accounts/verification_result.html",
        {
            "success": True,
            "message": "Your email is verified and your account is ready. You can now sign in.",
        },
    )
    response["Referrer-Policy"] = "no-referrer"
    return response


def _render_registration_completion(request, pending, form):
    response = render(
        request,
        "accounts/complete_registration.html",
        {
            "form": form,
            "verification_email": pending.email,
        },
    )
    response["Referrer-Policy"] = CLEAN_FORM_REFERRER_POLICY
    return response


def _verification_failure(request, message):
    response = render(
        request,
        "accounts/verification_result.html",
        {"success": False, "message": message},
        status=400,
    )
    response["Referrer-Policy"] = "no-referrer"
    return response


login_view = LoginView.as_view(
    authentication_form=EmailAuthenticationForm,
    template_name="accounts/login.html",
    redirect_authenticated_user=True,
)
logout_view = LogoutView.as_view(next_page="accounts:login")


@never_cache
@require_http_methods(["GET"])
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

    _store_verification_state(
        request,
        EMAIL_VERIFICATION_SESSION_KEY,
        user_id,
        email_verification_token_hash(token),
    )
    response = redirect("accounts:verify_email_form", user_id=user_id)
    response["Referrer-Policy"] = "no-referrer"
    return response


@never_cache
@require_http_methods(["GET", "POST"])
def verify_email_form(request, user_id):
    token_hash = _get_verification_state(
        request,
        EMAIL_VERIFICATION_SESSION_KEY,
        user_id,
    )
    user = User.objects.filter(pk=user_id, is_email_verified=False).first()
    valid_token = (
        user is not None
        and token_hash is not None
        and is_email_verification_token_hash_valid(user_id, token_hash)
    )
    if not valid_token:
        _clear_verification_state(
            request,
            EMAIL_VERIFICATION_SESSION_KEY,
            user_id,
        )
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
        if consume_email_verification_token_hash(user_id, token_hash):
            _clear_verification_state(
                request,
                EMAIL_VERIFICATION_SESSION_KEY,
                user_id,
            )
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
        _clear_verification_state(
            request,
            EMAIL_VERIFICATION_SESSION_KEY,
            user_id,
        )
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
        {
            "verification_email": user.email,
            "success": False,
            "message": message,
        },
        status=status,
    )
    response["Referrer-Policy"] = CLEAN_FORM_REFERRER_POLICY
    return response

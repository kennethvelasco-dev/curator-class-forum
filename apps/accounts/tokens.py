"""Email-verification token generation and validation."""

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import EmailVerificationToken, PendingRegistration


def _token_digest(raw_token):
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _valid_tokens(raw_token):
    expires_at = timezone.now() - timedelta(
        seconds=settings.EMAIL_VERIFICATION_TOKEN_TTL
    )
    return EmailVerificationToken.objects.filter(
        token_hash=_token_digest(raw_token),
        used_at__isnull=True,
        created_at__gte=expires_at,
    )


def issue_email_verification_token(user):
    raw_token = secrets.token_urlsafe(32)

    EmailVerificationToken.objects.filter(
        user=user,
        used_at__isnull=True,
    ).update(used_at=timezone.now())
    EmailVerificationToken.objects.create(
        user=user,
        token_hash=_token_digest(raw_token),
    )
    return raw_token


def issue_registration_token(email):
    raw_token = secrets.token_urlsafe(32)
    pending, created = PendingRegistration.objects.get_or_create(
        email=email,
        defaults={"token_hash": _token_digest(raw_token)},
    )
    return pending, raw_token if created else None


def is_email_verification_token_valid(user_id, raw_token):
    return _valid_tokens(raw_token).filter(user_id=user_id).exists()


@transaction.atomic
def consume_email_verification_token(user_id, raw_token):
    verification = (
        _valid_tokens(raw_token)
        .select_related("user")
        .select_for_update()
        .filter(user_id=user_id)
        .first()
    )
    if verification is None or verification.user.is_email_verified:
        return False

    verification.used_at = timezone.now()
    verification.save(update_fields=["used_at"])
    verification.user.is_email_verified = True
    verification.user.save(update_fields=["is_email_verified"])
    return True

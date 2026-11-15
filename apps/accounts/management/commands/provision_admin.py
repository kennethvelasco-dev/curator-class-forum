"""Provision a new Platform Admin account (initial setup only)."""

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from getpass import getpass

from apps.accounts.models import User


class Command(BaseCommand):
    help = "Provision a new Platform Admin account (initial setup only)."

    def add_arguments(self, parser):
        parser.add_argument("email", help="Admin email address.")
        parser.add_argument("full_name", help="Admin full name.")

    def handle(self, *args, **options):
        email = User.objects.normalize_email(options["email"])
        full_name = options["full_name"].strip()
        if not full_name:
            raise CommandError("A full name is required.")

        if User.objects.filter(email__iexact=email).exists():
            raise CommandError(
                "An account with this email address already exists."
            )

        password1 = getpass("Password: ")
        password2 = getpass("Confirm password: ")
        if password1 != password2:
            raise CommandError("The passwords do not match.")

        try:
            validate_password(
                password1,
                user=User(email=email, full_name=full_name),
            )
        except ValidationError as errors:
            messages = "; ".join(errors.messages)
            raise CommandError(f"Invalid password: {messages}")

        with transaction.atomic():
            user = User.objects.create_user(
                email=email,
                password=password1,
                full_name=full_name,
                is_staff=True,
                is_superuser=False,
                is_active=True,
                is_email_verified=True,
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Platform Admin provisioned: {user.email} ({user.full_name})"
            )
        )
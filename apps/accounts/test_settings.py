import os
import subprocess
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONSOLE_BACKEND = "django.core.mail.backends.console.EmailBackend"
SMTP_BACKEND = "django.core.mail.backends.smtp.EmailBackend"


class EmailBackendSettingsTests(unittest.TestCase):
    def run_settings_import(self, *, debug, email_backend=None):
        environment = os.environ.copy()
        environment["DJANGO_DEBUG"] = debug
        environment["DJANGO_SECRET_KEY"] = "settings-test-key"
        environment["DJANGO_ALLOWED_HOSTS"] = "localhost"
        environment["DJANGO_SETTINGS_MODULE"] = "config.settings"
        if email_backend is None:
            environment.pop("EMAIL_BACKEND", None)
        else:
            environment["EMAIL_BACKEND"] = email_backend

        return subprocess.run(
            [
                sys.executable,
                "-c",
                "import config.settings; print(config.settings.EMAIL_BACKEND)",
            ],
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_development_defaults_to_console_backend(self):
        result = self.run_settings_import(debug="True")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(CONSOLE_BACKEND, result.stdout + result.stderr)

    def test_production_rejects_default_and_explicit_console_backend(self):
        for backend in (None, CONSOLE_BACKEND):
            with self.subTest(backend=backend):
                result = self.run_settings_import(
                    debug="False",
                    email_backend=backend,
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ImproperlyConfigured", result.stderr)
                self.assertIn("non-console email backend", result.stderr)

    def test_production_accepts_configured_smtp_backend(self):
        environment = os.environ.copy()
        environment.update(
            {
                "DJANGO_DEBUG": "False",
                "DJANGO_SECRET_KEY": "settings-test-key",
                "DJANGO_ALLOWED_HOSTS": "localhost",
                "DJANGO_SETTINGS_MODULE": "config.settings",
                "EMAIL_BACKEND": SMTP_BACKEND,
                "EMAIL_HOST": "smtp.example.test",
                "EMAIL_PORT": "587",
                "EMAIL_HOST_USER": "test@example.test",
                "EMAIL_HOST_PASSWORD": "test-password",
            }
        )
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import config.settings; "
                    "from django.conf import settings; "
                    "from django.core.mail import get_connection; "
                    "connection = get_connection(); "
                    "assert connection.__class__.__module__ == "
                    "'django.core.mail.backends.smtp'; "
                    "assert settings.EMAIL_BACKEND == "
                    "'django.core.mail.backends.smtp.EmailBackend'; "
                    "assert settings.EMAIL_HOST == 'smtp.example.test'; "
                    "assert settings.EMAIL_HOST_USER == 'test@example.test'; "
                    "assert settings.EMAIL_HOST_PASSWORD == 'test-password'"
                ),
            ],
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONSOLE_BACKEND = "django.core.mail.backends.console.EmailBackend"
SMTP_BACKEND = "django.core.mail.backends.smtp.EmailBackend"


class EmailBackendSettingsTests(unittest.TestCase):
    def run_settings_import(
        self,
        *,
        debug,
        email_backend=None,
        private_cor_storage_root="",
    ):
        environment = os.environ.copy()
        environment["DJANGO_DEBUG"] = debug
        environment["DJANGO_SECRET_KEY"] = "settings-test-key"
        environment["DJANGO_ALLOWED_HOSTS"] = "localhost"
        environment["DJANGO_SETTINGS_MODULE"] = "config.settings"
        environment["PRIVATE_COR_STORAGE_ROOT"] = private_cor_storage_root
        if email_backend is None:
            environment.pop("EMAIL_BACKEND", None)
        else:
            environment["EMAIL_BACKEND"] = email_backend

        return subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import config.settings; "
                    "print(config.settings.EMAIL_BACKEND); "
                    "print(config.settings.PRIVATE_COR_STORAGE_ROOT)"
                ),
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
        self.assertIn(
            str(PROJECT_ROOT.parent / "private_cor_storage"),
            result.stdout + result.stderr,
        )

    def test_production_requires_private_storage_root(self):
        for root in ("", "   "):
            with self.subTest(root=repr(root)):
                result = self.run_settings_import(
                    debug="False",
                    email_backend=SMTP_BACKEND,
                    private_cor_storage_root=root,
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ImproperlyConfigured", result.stderr)
                self.assertIn("PRIVATE_COR_STORAGE_ROOT", result.stderr)
                self.assertIn("explicitly configured", result.stderr)

    def test_production_rejects_default_and_explicit_console_backend(self):
        for backend in (None, CONSOLE_BACKEND):
            with self.subTest(backend=backend):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    result = self.run_settings_import(
                        debug="False",
                        email_backend=backend,
                        private_cor_storage_root=str(
                            Path(temporary_directory) / "private-cor"
                        ),
                    )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ImproperlyConfigured", result.stderr)
                self.assertIn("non-console email backend", result.stderr)

    def test_production_accepts_configured_smtp_backend(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            storage_root = Path(temporary_directory) / "private-cor"
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
                    "PRIVATE_COR_STORAGE_ROOT": str(storage_root),
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
                        "assert settings.EMAIL_HOST_PASSWORD == 'test-password'; "
                        "assert str(settings.PRIVATE_COR_STORAGE_ROOT) == "
                        f"{str(storage_root.resolve())!r}"
                    ),
                ],
                cwd=PROJECT_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)


class DatabaseSettingsTests(unittest.TestCase):
    def run_settings_import(self, **overrides):
        environment = os.environ.copy()
        for key in (
            "DATABASE_ENGINE",
            "POSTGRES_DB",
            "POSTGRES_USER",
            "POSTGRES_PASSWORD",
            "POSTGRES_HOST",
            "POSTGRES_PORT",
            "POSTGRES_TEST_DB",
            "POSTGRES_SSLMODE",
            "POSTGRES_SSLROOTCERT",
            "DJANGO_DEBUG",
            "DJANGO_SECRET_KEY",
            "DJANGO_ALLOWED_HOSTS",
            "EMAIL_BACKEND",
            "PRIVATE_COR_STORAGE_ROOT",
        ):
            environment.pop(key, None)

        environment.update(
            {
                "DJANGO_DEBUG": "True",
                "DJANGO_SECRET_KEY": "settings-test-key",
                "DJANGO_ALLOWED_HOSTS": "localhost",
                "PRIVATE_COR_STORAGE_ROOT": str(PROJECT_ROOT / "test-private-cor"),
            }
        )
        environment.update(overrides)

        return subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import json; "
                    "import dotenv; "
                    "dotenv.load_dotenv = lambda *args, **kwargs: None; "
                    "import config.settings as settings; "
                    "print(json.dumps("
                    "{'engine': settings.DATABASE_ENGINE, "
                    "'database': settings.DATABASES['default']}, "
                    "default=str))"
                ),
            ],
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def get_settings(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_database_engine_defaults_to_sqlite(self):
        settings = self.get_settings(self.run_settings_import())

        self.assertEqual(settings["engine"], "sqlite")
        self.assertEqual(
            settings["database"]["ENGINE"],
            "django.db.backends.sqlite3",
        )
        self.assertEqual(
            settings["database"]["NAME"],
            str(PROJECT_ROOT / "db.sqlite3"),
        )

    def test_explicit_sqlite_engine_uses_existing_database_path(self):
        settings = self.get_settings(
            self.run_settings_import(DATABASE_ENGINE="sqlite")
        )

        self.assertEqual(
            settings["database"]["NAME"],
            str(PROJECT_ROOT / "db.sqlite3"),
        )

    def test_explicit_postgresql_engine_is_supported(self):
        settings = self.get_settings(
            self.run_settings_import(DATABASE_ENGINE="postgresql")
        )

        self.assertEqual(settings["engine"], "postgresql")
        self.assertEqual(
            settings["database"]["ENGINE"],
            "django.db.backends.postgresql",
        )

    def test_invalid_database_engine_is_rejected(self):
        result = self.run_settings_import(DATABASE_ENGINE="mysql")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ImproperlyConfigured", result.stderr)
        self.assertIn("DATABASE_ENGINE must be either", result.stderr)

    def test_postgresql_test_database_must_differ_from_application_database(self):
        result = self.run_settings_import(
            DATABASE_ENGINE="postgresql",
            POSTGRES_DB="curator",
            POSTGRES_TEST_DB="curator",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ImproperlyConfigured", result.stderr)
        self.assertIn("must differ from POSTGRES_DB", result.stderr)

    def test_distinct_postgresql_test_database_is_accepted(self):
        settings = self.get_settings(
            self.run_settings_import(
                DATABASE_ENGINE="postgresql",
                POSTGRES_DB="curator",
                POSTGRES_TEST_DB="curator_test",
            )
        )

        self.assertEqual(settings["database"]["NAME"], "curator")
        self.assertEqual(settings["database"]["TEST"]["NAME"], "curator_test")

    def test_postgresql_test_database_keeps_existing_default_name(self):
        settings = self.get_settings(
            self.run_settings_import(DATABASE_ENGINE="postgresql")
        )

        self.assertEqual(
            settings["database"]["TEST"]["NAME"],
            "curator_forum_test",
        )

    def test_remote_postgresql_defaults_to_full_tls_verification(self):
        settings = self.get_settings(
            self.run_settings_import(
                DATABASE_ENGINE="postgresql",
                POSTGRES_HOST="db.example.test",
            )
        )

        self.assertEqual(
            settings["database"]["OPTIONS"]["sslmode"],
            "verify-full",
        )

    def test_postgresql_ca_certificate_is_passed_to_driver_options(self):
        certificate_path = str(PROJECT_ROOT / "test-ca.crt")
        settings = self.get_settings(
            self.run_settings_import(
                DATABASE_ENGINE="postgresql",
                POSTGRES_HOST="db.example.test",
                POSTGRES_SSLROOTCERT=certificate_path,
            )
        )

        self.assertEqual(
            settings["database"]["OPTIONS"]["sslrootcert"],
            certificate_path,
        )

    def test_loopback_postgresql_hosts_do_not_require_certificate_verification(self):
        for host in ("localhost", "127.0.0.1", "::1"):
            with self.subTest(host=host):
                settings = self.get_settings(
                    self.run_settings_import(
                        DATABASE_ENGINE="postgresql",
                        POSTGRES_HOST=host,
                    )
                )

                self.assertNotIn(
                    "sslmode",
                    settings["database"].get("OPTIONS", {}),
                )

    def test_production_remote_postgresql_rejects_non_full_tls_modes(self):
        for sslmode in ("require", "verify-ca"):
            with self.subTest(sslmode=sslmode):
                result = self.run_settings_import(
                    DATABASE_ENGINE="postgresql",
                    POSTGRES_HOST="db.example.test",
                    POSTGRES_SSLMODE=sslmode,
                    DJANGO_DEBUG="False",
                    EMAIL_BACKEND=SMTP_BACKEND,
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ImproperlyConfigured", result.stderr)
                self.assertIn(
                    "require POSTGRES_SSLMODE=verify-full",
                    result.stderr,
                )

    def test_production_remote_postgresql_accepts_full_tls_verification(self):
        settings = self.get_settings(
            self.run_settings_import(
                DATABASE_ENGINE="postgresql",
                POSTGRES_HOST="db.example.test",
                POSTGRES_SSLMODE="verify-full",
                DJANGO_DEBUG="False",
                EMAIL_BACKEND=SMTP_BACKEND,
            )
        )

        self.assertEqual(
            settings["database"]["OPTIONS"]["sslmode"],
            "verify-full",
        )

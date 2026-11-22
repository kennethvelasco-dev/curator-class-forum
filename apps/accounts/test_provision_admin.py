import io
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.accounts.models import User


class ProvisionAdminCommandTests(TestCase):
    def _run_command(self, email, full_name, password_value, stdout=None, stderr=None):
        if stdout is None:
            stdout = io.StringIO()
        if stderr is None:
            stderr = io.StringIO()
        with patch(
            "apps.accounts.management.commands.provision_admin.getpass",
            return_value=password_value,
        ):
            call_command(
                "provision_admin",
                email,
                full_name,
                stdout=stdout,
                stderr=stderr,
            )
        return stdout.getvalue(), stderr.getvalue()

    def test_successful_provisioning(self):
        out, err = self._run_command(
            "admin@example.com", "Platform Admin", "Str0ngP@ssw0rd"
        )
        self.assertEqual(User.objects.count(), 1)
        user = User.objects.get(email="admin@example.com")
        self.assertEqual(user.full_name, "Platform Admin")
        self.assertTrue(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.is_active)
        self.assertTrue(user.is_email_verified)
        self.assertTrue(user.check_password("Str0ngP@ssw0rd"))
        self.assertRegex(user.anonymous_id, r"^CSS-\d{5}$")
        self.assertIn("Platform Admin provisioned", out)
        self.assert_no_secrets(out, err)

    def test_password_is_hashed_and_usable(self):
        out, err = self._run_command(
            "admin@example.com", "Platform Admin", "Str0ngP@ssw0rd"
        )
        user = User.objects.get(email="admin@example.com")
        self.assertFalse(user.password.startswith("Str0ngP@ssw0rd"))
        self.assertTrue(user.check_password("Str0ngP@ssw0rd"))

    def test_password_confirmation_mismatch(self):
        with patch(
            "apps.accounts.management.commands.provision_admin.getpass",
            side_effect=["Str0ngP@ssw0rd", "DifferentPass"],
        ):
            with self.assertRaises(CommandError) as ctx:
                call_command(
                    "provision_admin",
                    "admin@example.com",
                    "Platform Admin",
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                )
            self.assertIn("passwords do not match", str(ctx.exception).lower())
        self.assertEqual(User.objects.count(), 0)

    def test_invalid_password_rejected(self):
        with patch(
            "apps.accounts.management.commands.provision_admin.getpass",
            return_value="weak",
        ):
            with self.assertRaises(CommandError) as ctx:
                call_command(
                    "provision_admin",
                    "admin@example.com",
                    "Platform Admin",
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                )
            self.assertIn("Invalid password", str(ctx.exception))
        self.assertEqual(User.objects.count(), 0)

    def test_duplicate_email_rejected_case_insensitively(self):
        User.objects.create_user(
            email="ADMIN@example.com",
            password="Str0ngP@ssw0rd",
            full_name="Existing Admin",
            is_staff=True,
            is_email_verified=True,
        )
        with patch(
            "apps.accounts.management.commands.provision_admin.getpass",
            return_value="Str0ngP@ssw0rd",
        ):
            with self.assertRaises(CommandError) as ctx:
                call_command(
                    "provision_admin",
                    "admin@example.com",
                    "Platform Admin",
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                )
            self.assertIn("already exists", str(ctx.exception).lower())
        self.assertEqual(User.objects.count(), 1)

    def test_existing_account_not_modified(self):
        existing = User.objects.create_user(
            email="admin@example.com",
            password="OldPassword123",
            full_name="Existing Admin",
            is_staff=False,
            is_active=False,
            is_email_verified=False,
        )
        old_password = existing.password
        old_is_staff = existing.is_staff
        old_is_active = existing.is_active
        old_is_verified = existing.is_email_verified

        with patch(
            "apps.accounts.management.commands.provision_admin.getpass",
            return_value="Str0ngP@ssw0rd",
        ):
            with self.assertRaises(CommandError):
                call_command(
                    "provision_admin",
                    "admin@example.com",
                    "Platform Admin",
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                )

        existing.refresh_from_db()
        self.assertEqual(existing.password, old_password)
        self.assertEqual(existing.is_staff, old_is_staff)
        self.assertEqual(existing.is_active, old_is_active)
        self.assertEqual(existing.is_email_verified, old_is_verified)
        self.assertEqual(User.objects.count(), 1)

    def test_secrets_never_appear_in_command_output(self):
        out = io.StringIO()
        err = io.StringIO()
        with patch(
            "apps.accounts.management.commands.provision_admin.getpass",
            return_value="Str0ngP@ssw0rd",
        ):
            call_command(
                "provision_admin",
                "admin@example.com",
                "Platform Admin",
                stdout=out,
                stderr=err,
            )
        combined = out.getvalue() + err.getvalue()
        self.assertNotIn("Str0ngP@ssw0rd", combined)
        self.assertNotIn("password", combined.lower())

    def assert_no_secrets(self, out, err):
        combined = out + err
        self.assertNotIn("Str0ngP@ssw0rd", combined)
        self.assertNotIn("password", combined.lower())

    @patch("apps.accounts.management.commands.provision_admin.getpass")
    def test_rejects_malformed_email(self, mocked_getpass):
        with self.assertRaises(CommandError):
            call_command(
                "provision_admin",
                "not-an-email",
                "Test Admin",
            )

        self.assertFalse(User.objects.exists())
        mocked_getpass.assert_not_called()
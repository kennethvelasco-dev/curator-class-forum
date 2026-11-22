from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase

from apps.accounts.admin import CuratorUserCreationForm
from apps.accounts.forms import RegistrationForm


User = get_user_model()
ANONYMOUS_ID_PATTERN = r"^CSS-\d{5}$"


class AnonymousIdentifierTests(TestCase):
    def create_user(self, email="member@example.com"):
        return User.objects.create_user(
            email=email,
            password="Secure!Random482",
            full_name="Test Member",
        )

    def test_create_user_generates_unique_five_digit_identifier(self):
        first = self.create_user("first@example.com")
        second = self.create_user("second@example.com")

        self.assertRegex(first.anonymous_id, ANONYMOUS_ID_PATTERN)
        self.assertRegex(second.anonymous_id, ANONYMOUS_ID_PATTERN)
        self.assertNotEqual(first.anonymous_id, second.anonymous_id)

    def test_collision_retries_with_a_new_identifier(self):
        existing = self.create_user("existing@example.com")

        with patch(
            "apps.accounts.models.generate_anonymous_identifier",
            side_effect=[existing.anonymous_id, "CSS-54321"],
        ) as generator:
            created = self.create_user("new@example.com")

        self.assertEqual(created.anonymous_id, "CSS-54321")
        self.assertEqual(generator.call_count, 2)

    def test_database_enforces_identifier_uniqueness(self):
        first = self.create_user("first@example.com")
        second = self.create_user("second@example.com")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                User.objects.filter(pk=second.pk).update(
                    anonymous_id=first.anonymous_id
                )

    def test_profile_update_preserves_identifier(self):
        user = self.create_user()
        anonymous_id = user.anonymous_id

        user.full_name = "Updated Name"
        user.save(update_fields=["full_name"])
        user.refresh_from_db()

        self.assertEqual(user.full_name, "Updated Name")
        self.assertEqual(user.anonymous_id, anonymous_id)

    def test_identifier_cannot_be_changed_after_creation(self):
        user = self.create_user()
        original_id = user.anonymous_id
        user.anonymous_id = "CSS-00001"

        with self.assertRaises(ValidationError):
            user.save()

        user.refresh_from_db()
        self.assertEqual(user.anonymous_id, original_id)

    def test_registration_form_creation_assigns_identifier(self):
        form = RegistrationForm(
            {
                "full_name": "Registration Member",
                "password1": "Secure!Random482",
                "password2": "Secure!Random482",
                "consent": "on",
            },
            email="registration@example.com",
        )
        self.assertTrue(form.is_valid(), form.errors)

        user = form.create_user("registration@example.com")

        self.assertRegex(user.anonymous_id, ANONYMOUS_ID_PATTERN)
        self.assertTrue(user.is_email_verified)
        self.assertTrue(user.consent_accepted)

    def test_admin_creation_form_assigns_identifier(self):
        form = CuratorUserCreationForm(
            {
                "email": "admin-form@example.com",
                "full_name": "Admin Form User",
                "password1": "Secure!Random482",
                "password2": "Secure!Random482",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

        user = form.save()

        self.assertRegex(user.anonymous_id, ANONYMOUS_ID_PATTERN)

    def test_create_superuser_assigns_identifier(self):
        user = User.objects.create_superuser(
            email="superuser@example.com",
            password="Secure!Random482",
            full_name="Test Superuser",
        )

        self.assertRegex(user.anonymous_id, ANONYMOUS_ID_PATTERN)


class AnonymousIdentifierMigrationTests(TransactionTestCase):
    migrate_from = ("accounts", "0006_user_full_name_not_blank")
    add_field_migration = ("accounts", "0007_add_anonymous_identifier")
    migrate_to = ("accounts", "0008_backfill_anonymous_identifiers")

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        old_apps = executor.loader.project_state([self.migrate_from]).apps
        HistoricalUser = old_apps.get_model("accounts", "User")

        self.existing_user_ids = [
            HistoricalUser.objects.create(
                email=f"existing-{index}@example.com",
                full_name=f"Existing User {index}",
                password="!",
            ).pk
            for index in range(2)
        ]

        executor = MigrationExecutor(connection)
        executor.migrate([self.add_field_migration])
        nullable_apps = executor.loader.project_state(
            [self.add_field_migration]
        ).apps
        NullableUser = nullable_apps.get_model("accounts", "User")
        self.late_legacy_user_id = NullableUser.objects.create(
            email="late-legacy@example.com",
            full_name="Late Legacy User",
            password="!",
            anonymous_id=None,
        ).pk

        MigrationExecutor(connection).migrate([self.migrate_to])

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_backfill_assigns_unique_identifiers_to_existing_users(self):
        migrated_apps = MigrationExecutor(connection).loader.project_state(
            [self.migrate_to]
        ).apps
        MigratedUser = migrated_apps.get_model("accounts", "User")
        user_ids = self.existing_user_ids + [self.late_legacy_user_id]
        identifiers = [
            MigratedUser.objects.get(pk=user_id).anonymous_id
            for user_id in user_ids
        ]

        self.assertEqual(len(set(identifiers)), len(user_ids))
        for anonymous_id in identifiers:
            self.assertRegex(anonymous_id, ANONYMOUS_ID_PATTERN)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MigratedUser.objects.create(
                    email="missing-id@example.com",
                    full_name="Missing Identifier",
                    password="!",
                    anonymous_id=None,
                )

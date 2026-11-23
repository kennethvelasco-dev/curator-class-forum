from unittest import mock

from django.contrib.auth import get_user_model
from django.db import DataError, IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase

from apps.discussions.anonymity import service
from apps.discussions.anonymity.factories import (
    make_channel,
    make_reply,
    make_thread,
    make_user,
)
from apps.discussions.anonymity.labels import generate_label, is_valid_label
from apps.discussions.anonymity.models import ThreadAlias
from apps.discussions.anonymity.service import (
    AliasAllocationError,
    ensure_alias_for_post,
    get_or_create_alias,
    thread_of,
)


def sequence(*numbers):
    """Label factory returning the given numbers in order."""
    values = iter(numbers)
    return lambda: f"CSS-{next(values):05d}"


class AliasStabilityTests(TestCase):
    def setUp(self):
        self.alice = make_user(40001, "Alice", "alice@example.edu")
        self.bob = make_user(40002, "Bob", "bob@example.edu")
        self.thread = make_thread(self.alice)

    def test_same_author_same_thread_gets_same_alias(self):
        first = get_or_create_alias(thread=self.thread, user=self.bob)
        second = get_or_create_alias(thread=self.thread, user=self.bob)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.label, second.label)
        self.assertEqual(ThreadAlias.objects.count(), 1)

    def test_label_is_persisted_and_valid(self):
        alias = get_or_create_alias(thread=self.thread, user=self.bob)
        alias.refresh_from_db()
        self.assertTrue(is_valid_label(alias.label))

    def test_different_authors_in_one_thread_get_different_labels(self):
        users = [make_user(50000 + i, f"U{i}", f"u{i}@example.edu") for i in range(60)]
        labels = {get_or_create_alias(thread=self.thread, user=u).label for u in users}
        self.assertEqual(len(labels), 60)

    def test_same_author_in_two_threads_has_independent_aliases(self):
        other = make_thread(self.alice, channel=self.thread.channel)
        a = get_or_create_alias(thread=self.thread, user=self.bob, label_factory=sequence(7))
        b = get_or_create_alias(thread=other, user=self.bob, label_factory=sequence(7))
        self.assertNotEqual(a.pk, b.pk)
        self.assertEqual(a.label, b.label)  # same number is allowed across threads
        self.assertEqual(ThreadAlias.objects.filter(user=self.bob).count(), 2)

    def test_unsaved_or_missing_thread_rejected(self):
        with self.assertRaises(ValueError):
            get_or_create_alias(thread=None, user=self.bob)
        gone = make_thread(self.alice)
        pk = gone.pk
        gone.delete()
        gone.pk = pk
        with self.assertRaises(ValueError):
            get_or_create_alias(thread=gone, user=self.bob)


class AliasCollisionTests(TestCase):
    def setUp(self):
        self.alice = make_user(40001, "Alice", "alice@example.edu")
        self.bob = make_user(40002, "Bob", "bob@example.edu")
        self.thread = make_thread(self.alice)
        get_or_create_alias(thread=self.thread, user=self.alice, label_factory=sequence(5))

    def test_collision_is_retried_with_a_new_label(self):
        alias = get_or_create_alias(
            thread=self.thread, user=self.bob, label_factory=sequence(5, 5, 6)
        )
        self.assertEqual(alias.label, "CSS-00006")

    def test_attempts_exhausted_raises_and_leaves_no_partial_row(self):
        with self.assertRaises(AliasAllocationError):
            get_or_create_alias(
                thread=self.thread, user=self.bob, label_factory=lambda: "CSS-00005"
            )
        self.assertFalse(ThreadAlias.objects.filter(user=self.bob).exists())
        # The connection is still usable after the failed allocation.
        self.assertEqual(ThreadAlias.objects.count(), 1)

    def test_label_space_exhaustion_fails_fast(self):
        with mock.patch.object(service, "LABEL_SPACE", 1):
            factory = mock.Mock()
            with self.assertRaises(AliasAllocationError):
                get_or_create_alias(
                    thread=self.thread, user=self.bob, label_factory=factory
                )
            factory.assert_not_called()

    def test_concurrent_winner_for_same_user_is_returned(self):
        # Simulate another request creating Bob's alias after our existence check.
        def racing_factory():
            ThreadAlias.objects.create(
                thread=self.thread, user=self.bob, label="CSS-00099"
            )
            return "CSS-00098"

        alias = get_or_create_alias(
            thread=self.thread, user=self.bob, label_factory=racing_factory
        )
        self.assertEqual(alias.label, "CSS-00099")
        self.assertEqual(ThreadAlias.objects.filter(user=self.bob).count(), 1)

    def test_unrelated_integrity_errors_are_not_swallowed(self):
        with mock.patch.object(
            ThreadAlias.objects, "create", side_effect=IntegrityError("boom")
        ):
            with self.assertRaises(IntegrityError):
                get_or_create_alias(
                    thread=self.thread, user=self.bob, label_factory=sequence(70)
                )


class AliasConstraintTests(TestCase):
    def setUp(self):
        self.alice = make_user(40001, "Alice", "alice@example.edu")
        self.bob = make_user(40002, "Bob", "bob@example.edu")
        self.thread = make_thread(self.alice)
        ThreadAlias.objects.create(thread=self.thread, user=self.alice, label="CSS-00001")

    def assert_rejected(self, **kwargs):
        # PostgreSQL rejects an over-long value with DataError before any
        # constraint is checked; SQLite reports IntegrityError. Both are rejections.
        with self.assertRaises((IntegrityError, DataError)), transaction.atomic():
            ThreadAlias.objects.create(thread=self.thread, **kwargs)

    def test_one_alias_per_user_per_thread(self):
        self.assert_rejected(user=self.alice, label="CSS-00002")

    def test_label_unique_within_thread(self):
        self.assert_rejected(user=self.bob, label="CSS-00001")

    def test_label_format_enforced_by_database(self):
        for bad in ("CSS-1", "css-00002", "CSS-0000A", "XXX-00002", "CSS-000022"):
            with self.subTest(bad=bad):
                self.assert_rejected(user=self.bob, label=bad)

    def test_user_with_alias_cannot_be_hard_deleted(self):
        # Alias is PROTECT; posts are PROTECT as well (Issue #31 contract).
        ThreadAlias.objects.filter(user=self.alice).exists()
        with self.assertRaises(ProtectedError):
            get_user_model().objects.get(pk=self.alice.pk).delete()

    def test_aliases_are_removed_with_their_thread(self):
        self.thread.delete()
        self.assertFalse(ThreadAlias.objects.exists())

    def test_str_never_contains_user_data(self):
        alias = ThreadAlias.objects.get(user=self.alice)
        self.assertEqual(str(alias), "CSS-00001")
        self.assertNotIn("Alice", repr(str(alias)))


class EnsureAliasForPostTests(TestCase):
    def setUp(self):
        self.alice = make_user(40001, "Alice", "alice@example.edu")
        self.bob = make_user(40002, "Bob", "bob@example.edu")

    def test_named_post_creates_no_alias(self):
        thread = make_thread(self.alice, anonymous=False)
        self.assertIsNone(ensure_alias_for_post(thread))
        self.assertEqual(ThreadAlias.objects.count(), 0)

    def test_anonymous_thread_creates_alias_for_its_author(self):
        thread = make_thread(self.alice, anonymous=True)
        alias = ensure_alias_for_post(thread)
        self.assertEqual((alias.thread_id, alias.user_id), (thread.pk, self.alice.pk))

    def test_anonymous_reply_uses_the_reply_thread_context(self):
        thread = make_thread(self.alice, anonymous=True)
        thread_alias = ensure_alias_for_post(thread)
        reply = make_reply(thread, self.alice, anonymous=True)
        self.assertEqual(ensure_alias_for_post(reply).pk, thread_alias.pk)

    def test_reply_in_another_thread_gets_a_separate_alias(self):
        t1 = make_thread(self.alice, anonymous=True)
        t2 = make_thread(self.alice, channel=t1.channel, anonymous=True)
        ensure_alias_for_post(t1, label_factory=sequence(1))
        ensure_alias_for_post(t2, label_factory=sequence(2))
        self.assertEqual(
            set(ThreadAlias.objects.values_list("thread_id", "label")),
            {(t1.pk, "CSS-00001"), (t2.pk, "CSS-00002")},
        )

    def test_thread_of_rejects_other_types(self):
        with self.assertRaises(TypeError):
            thread_of(object())

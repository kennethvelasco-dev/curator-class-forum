"""Concurrent alias allocation. Runs only on PostgreSQL.

SQLite ignores ``select_for_update`` and serialises writers differently, so a
SQLite pass would say nothing about real concurrency.
"""

import secrets
import threading
from unittest import skipUnless

from django.db import connection, connections
from django.test import TransactionTestCase

from apps.discussions.anonymity.factories import make_channel, make_thread, make_user
from apps.discussions.anonymity.models import ThreadAlias
from apps.discussions.anonymity.service import get_or_create_alias


def run_in_parallel(jobs):
    """Run callables in separate threads (each with its own DB connection)."""
    barrier = threading.Barrier(len(jobs))
    results = [None] * len(jobs)
    errors = [None] * len(jobs)

    def worker(index, job):
        try:
            barrier.wait(timeout=10)
            results[index] = job()
        except Exception as exc:  # noqa: BLE001 - reported to the test
            errors[index] = exc
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker, args=(i, j)) for i, j in enumerate(jobs)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    return results, errors


@skipUnless(connection.vendor == "postgresql", "PostgreSQL-only concurrency test")
class AliasConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.starter = make_user(None, "Starter Person")
        self.users = [make_user(None, f"Member {i}") for i in range(10)]
        self.channel = make_channel(members=[self.starter, *self.users])
        self.thread = make_thread(self.starter, channel=self.channel, anonymous=True)

    def test_simultaneous_first_posts_by_one_user_create_one_alias(self):
        user = self.users[0]
        jobs = [lambda: get_or_create_alias(thread=self.thread, user=user) for _ in range(8)]
        results, errors = run_in_parallel(jobs)
        self.assertEqual([e for e in errors if e], [])
        self.assertEqual(ThreadAlias.objects.filter(thread=self.thread, user=user).count(), 1)
        self.assertEqual({r.label for r in results}, {results[0].label})

    def test_simultaneous_first_posts_by_many_users_get_distinct_labels(self):
        # A deliberately tiny label space (20 values for 10 users) forces
        # frequent collisions, exercising the retry path under real locking.
        def small_space():
            return f"CSS-{secrets.randbelow(20):05d}"

        jobs = [
            (lambda u=u: get_or_create_alias(
                thread=self.thread, user=u, label_factory=small_space
            ))
            for u in self.users
        ]
        results, errors = run_in_parallel(jobs)
        self.assertEqual([e for e in errors if e], [])
        labels = list(
            ThreadAlias.objects.filter(thread=self.thread).values_list("label", flat=True)
        )
        self.assertEqual(len(labels), 10)
        self.assertEqual(len(set(labels)), 10)

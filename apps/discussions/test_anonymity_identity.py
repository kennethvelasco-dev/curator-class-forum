import dataclasses
import itertools

from django.test import SimpleTestCase

from apps.discussions.anonymity.identity import (
    ANONYMOUS_FALLBACK_NAME,
    NAMED_FALLBACK_NAME,
    PostIdentity,
    author_badge_applies,
    build_identity,
)


def badge(post_author, thread_author, post_anon, thread_anon):
    return author_badge_applies(
        post_author_id=post_author,
        thread_author_id=thread_author,
        post_is_anonymous=post_anon,
        thread_is_anonymous=thread_anon,
    )


class AuthorBadgeTests(SimpleTestCase):
    def test_default_policy_suppresses_mixed_mode(self):
        # Badge only when the thread starter's post mode matches the thread mode.
        self.assertTrue(badge(1, 1, False, False))  # named thread, named reply
        self.assertTrue(badge(1, 1, True, True))    # anonymous thread, anonymous reply
        self.assertFalse(badge(1, 1, False, True))  # named thread, anonymous reply
        self.assertFalse(badge(1, 1, True, False))  # anonymous thread, named reply

    def test_other_authors_never_get_the_badge_default(self):
        self.assertFalse(badge(2, 1, False, False))
        self.assertFalse(badge(2, 1, True, True))
        self.assertFalse(badge(2, 1, True, False))
        self.assertFalse(badge(2, 1, False, True))

    def test_override_false_badges_every_post_by_thread_author(self):
        # Explicitly passing suppress_in_mixed_mode=False restores the literal
        # behavior: every post by the thread starter is badged regardless of mode.
        for post_anon, thread_anon in itertools.product((True, False), repeat=2):
            with self.subTest(post_anon=post_anon, thread_anon=thread_anon):
                self.assertTrue(
                    author_badge_applies(
                        post_author_id=1,
                        thread_author_id=1,
                        post_is_anonymous=post_anon,
                        thread_is_anonymous=thread_anon,
                        suppress_in_mixed_mode=False,
                    )
                )

    def test_override_true_suppresses_mixed_mode(self):
        self.assertTrue(
            author_badge_applies(
                post_author_id=1,
                thread_author_id=1,
                post_is_anonymous=True,
                thread_is_anonymous=True,
                suppress_in_mixed_mode=True,
            )
        )
        self.assertTrue(
            author_badge_applies(
                post_author_id=1,
                thread_author_id=1,
                post_is_anonymous=False,
                thread_is_anonymous=False,
                suppress_in_mixed_mode=True,
            )
        )
        self.assertFalse(
            author_badge_applies(
                post_author_id=1,
                thread_author_id=1,
                post_is_anonymous=True,
                thread_is_anonymous=False,
                suppress_in_mixed_mode=True,
            )
        )
        self.assertFalse(
            author_badge_applies(
                post_author_id=1,
                thread_author_id=1,
                post_is_anonymous=False,
                thread_is_anonymous=True,
                suppress_in_mixed_mode=True,
            )
        )

    def test_missing_ids_never_badge(self):
        self.assertFalse(badge(None, None, False, False))
        self.assertFalse(badge(1, None, False, False))

    def test_decision_uses_ids_not_names(self):
        # Two different authors can share a display name; only ids matter.
        self.assertFalse(badge(2, 1, False, False))


class BuildIdentityTests(SimpleTestCase):
    def test_anonymous_uses_alias_not_real_name(self):
        identity = build_identity(
            is_anonymous=True,
            alias_label="CSS-00042",
            named_display_name="Real Name",
            show_author_badge=False,
        )
        self.assertEqual(identity.display_name, "CSS-00042")
        self.assertTrue(identity.is_anonymous)

    def test_anonymous_with_missing_or_malformed_alias_never_shows_name(self):
        for alias in (None, "", "Real Name", "CSS-1"):
            with self.subTest(alias=alias):
                identity = build_identity(
                    is_anonymous=True,
                    alias_label=alias,
                    named_display_name="Real Name",
                    show_author_badge=False,
                )
                self.assertEqual(identity.display_name, ANONYMOUS_FALLBACK_NAME)

    def test_named_uses_display_name_and_ignores_alias(self):
        identity = build_identity(
            is_anonymous=False,
            alias_label="CSS-00042",
            named_display_name="  Real Name ",
            show_author_badge=True,
        )
        self.assertEqual(identity.display_name, "Real Name")
        self.assertTrue(identity.show_author_badge)

    def test_named_without_a_name_has_a_neutral_fallback(self):
        identity = build_identity(
            is_anonymous=False,
            alias_label=None,
            named_display_name="",
            show_author_badge=False,
        )
        self.assertEqual(identity.display_name, NAMED_FALLBACK_NAME)

    def test_identity_exposes_only_three_safe_fields_and_is_frozen(self):
        names = {f.name for f in dataclasses.fields(PostIdentity)}
        self.assertEqual(names, {"display_name", "is_anonymous", "show_author_badge"})
        identity = PostIdentity("x", True, False)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            identity.display_name = "y"

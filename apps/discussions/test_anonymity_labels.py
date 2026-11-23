from django.test import SimpleTestCase

from apps.discussions.anonymity.labels import (
    LABEL_SPACE,
    format_label,
    generate_label,
    is_valid_label,
)


class LabelFormatTests(SimpleTestCase):
    def test_format_zero_pads_to_five_digits(self):
        self.assertEqual(format_label(7), "CSS-00007")
        self.assertEqual(format_label(0), "CSS-00000")
        self.assertEqual(format_label(99999), "CSS-99999")

    def test_format_rejects_out_of_range_and_non_integers(self):
        for bad in (-1, LABEL_SPACE, 1.5, "7", None, True):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                format_label(bad)

    def test_generate_uses_injected_source(self):
        self.assertEqual(generate_label(lambda n: 42), "CSS-00042")
        seen = []
        generate_label(lambda n: seen.append(n) or 0)
        self.assertEqual(seen, [LABEL_SPACE])

    def test_generated_labels_always_valid(self):
        for _ in range(2000):
            self.assertTrue(is_valid_label(generate_label()))

    def test_is_valid_label(self):
        self.assertTrue(is_valid_label("CSS-12345"))
        for bad in (
            "CSS-1234", "CSS-123456", "css-12345", "CSS-12a45", "CSS12345",
            "CSS-12345\n", " CSS-12345", "", None, 12345,
        ):
            with self.subTest(bad=bad):
                self.assertFalse(is_valid_label(bad))

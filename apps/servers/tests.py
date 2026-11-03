import io
import logging
import os
import stat
import tempfile
import unittest
import uuid
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings
from pypdf import PdfWriter

from apps.servers.storage import (
    CorDeletionError,
    CorDeletionResult,
    PrivateCorStorage,
    delete_cor,
    get_cor_storage,
)
from apps.servers.validators import MAX_COR_FILE_SIZE, validate_cor_file


def make_pdf_bytes():
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


VALID_PDF = make_pdf_bytes()


def make_upload(name="registration.pdf", content=VALID_PDF):
    return SimpleUploadedFile(name, content, content_type="application/pdf")


def normalized_path(path):
    return os.path.normcase(os.path.normpath(str(Path(path).resolve())))


class CorFileValidationTests(SimpleTestCase):
    def test_accepts_pdf_with_case_insensitive_extension(self):
        uploaded_file = make_upload("registration.PDF")

        validate_cor_file(uploaded_file)

        self.assertEqual(uploaded_file.tell(), 0)

    def test_accepts_file_at_size_limit(self):
        uploaded_file = make_upload(
            content=VALID_PDF + b" " * (MAX_COR_FILE_SIZE - len(VALID_PDF))
        )

        validate_cor_file(uploaded_file)

    def test_rejects_file_over_size_limit(self):
        uploaded_file = make_upload(
            content=VALID_PDF + b" " * (MAX_COR_FILE_SIZE + 1 - len(VALID_PDF))
        )

        with self.assertRaisesMessage(ValidationError, "6 MB"):
            validate_cor_file(uploaded_file)

    def test_rejects_non_pdf_extension(self):
        uploaded_file = make_upload("registration.txt")

        with self.assertRaisesMessage(ValidationError, "PDF"):
            validate_cor_file(uploaded_file)

    def test_rejects_file_without_pdf_signature(self):
        uploaded_file = make_upload(content=b"not a PDF")

        with self.assertRaisesMessage(ValidationError, "valid PDF"):
            validate_cor_file(uploaded_file)

    def test_rejects_pdf_header_without_a_valid_structure(self):
        uploaded_file = make_upload(content=b"%PDF-1.7\nnot a PDF")

        with self.assertRaisesMessage(ValidationError, "valid PDF"):
            validate_cor_file(uploaded_file)

    def test_accepts_valid_pdf_with_header_within_first_1024_bytes(self):
        uploaded_file = make_upload(content=b" " * 1000 + VALID_PDF)

        validate_cor_file(uploaded_file)

    def test_restores_original_position_after_pdf_parse_failure(self):
        uploaded_file = make_upload(content=b"%PDF-1.7\nnot a PDF")
        uploaded_file.seek(4)

        with self.assertRaises(ValidationError):
            validate_cor_file(uploaded_file)

        self.assertEqual(uploaded_file.tell(), 4)

    def test_restores_original_position_after_successful_validation(self):
        uploaded_file = make_upload()
        uploaded_file.seek(4)

        validate_cor_file(uploaded_file)

        self.assertEqual(uploaded_file.tell(), 4)


class PrivateCorStorageTests(SimpleTestCase):
    def test_private_storage_does_not_generate_public_urls(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "private"
            with override_settings(
                PRIVATE_COR_STORAGE_ROOT=root,
                MEDIA_ROOT=Path(temporary_directory) / "media",
                MEDIA_URL="/media/",
                STATIC_ROOT=Path(temporary_directory) / "static",
                STATICFILES_DIRS=[],
            ):
                storage = get_cor_storage()

                self.assertEqual(
                    normalized_path(storage.location),
                    normalized_path(root),
                )
                with self.assertRaises(ValueError):
                    storage.url("registration.pdf")

    def test_storage_rejects_a_root_inside_media_root(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            media_root = Path(temporary_directory) / "media"
            with override_settings(
                PRIVATE_COR_STORAGE_ROOT=media_root / "private",
                MEDIA_ROOT=media_root,
                STATIC_ROOT="",
                STATICFILES_DIRS=[],
            ):
                with self.assertRaises(ImproperlyConfigured):
                    PrivateCorStorage()

    def test_storage_rejects_project_root(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory) / "project"
            with override_settings(
                BASE_DIR=project_root,
                PRIVATE_COR_STORAGE_ROOT=project_root,
                MEDIA_ROOT="",
                STATIC_ROOT="",
                STATICFILES_DIRS=[],
            ):
                with self.assertRaisesMessage(
                    ImproperlyConfigured,
                    "BASE_DIR",
                ):
                    PrivateCorStorage()

    def test_storage_rejects_a_descendant_of_project_root(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory) / "project"
            with override_settings(
                BASE_DIR=project_root,
                PRIVATE_COR_STORAGE_ROOT=project_root / "private",
                MEDIA_ROOT="",
                STATIC_ROOT="",
                STATICFILES_DIRS=[],
            ):
                with self.assertRaisesMessage(
                    ImproperlyConfigured,
                    "BASE_DIR",
                ):
                    PrivateCorStorage()

    def test_storage_rejects_an_ancestor_of_project_root(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory) / "project" / "repo"
            with override_settings(
                BASE_DIR=project_root,
                PRIVATE_COR_STORAGE_ROOT=project_root.parent,
                MEDIA_ROOT="",
                STATIC_ROOT="",
                STATICFILES_DIRS=[],
            ):
                with self.assertRaisesMessage(
                    ImproperlyConfigured,
                    "BASE_DIR",
                ):
                    PrivateCorStorage()

    def test_storage_rejects_a_root_overlapping_static_files(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            static_root = Path(temporary_directory) / "static"
            with override_settings(
                PRIVATE_COR_STORAGE_ROOT=static_root / "private",
                MEDIA_ROOT="",
                STATIC_ROOT=static_root,
                STATICFILES_DIRS=[],
            ):
                with self.assertRaises(ImproperlyConfigured):
                    PrivateCorStorage()

    def test_storage_can_save_files_under_its_private_root(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            private_root = Path(temporary_directory) / "private"
            with override_settings(
                PRIVATE_COR_STORAGE_ROOT=private_root,
                MEDIA_ROOT=Path(temporary_directory) / "media",
                STATIC_ROOT="",
                STATICFILES_DIRS=[],
            ):
                storage = get_cor_storage()
                name = storage.save("registration.pdf", make_upload())

                self.assertTrue(storage.exists(name))
                self.assertTrue((private_root / name).is_file())

    def test_storage_uses_uuid_names_and_restrictive_creation_modes(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            private_root = Path(temporary_directory) / "private"
            with override_settings(
                PRIVATE_COR_STORAGE_ROOT=private_root,
                MEDIA_ROOT=Path(temporary_directory) / "media",
                STATIC_ROOT="",
                STATICFILES_DIRS=[],
            ):
                storage = get_cor_storage()
                first_name = storage.save(
                    "student-registration.pdf",
                    make_upload("student-registration.pdf"),
                )
                second_name = storage.save(
                    "student-registration.pdf",
                    make_upload("student-registration.pdf"),
                )

                self.assertEqual(Path(first_name).suffix, ".pdf")
                self.assertEqual(Path(second_name).suffix, ".pdf")
                uuid.UUID(Path(first_name).stem)
                uuid.UUID(Path(second_name).stem)
                self.assertNotEqual(first_name, second_name)
                self.assertEqual(storage.directory_permissions_mode, 0o700)
                self.assertEqual(storage.file_permissions_mode, 0o600)
                if os.name != "nt":
                    self.assertEqual(
                        stat.S_IMODE(private_root.stat().st_mode),
                        0o700,
                    )
                    self.assertEqual(
                        stat.S_IMODE((private_root / first_name).stat().st_mode),
                        0o600,
                    )

    def test_storage_rejects_a_root_overlapping_staticfiles_dirs(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            static_dir = Path(temporary_directory) / "assets"
            with override_settings(
                BASE_DIR=Path(temporary_directory) / "project",
                PRIVATE_COR_STORAGE_ROOT=static_dir / "private",
                MEDIA_ROOT="",
                STATIC_ROOT="",
                STATICFILES_DIRS=[("assets", static_dir)],
            ):
                with self.assertRaises(ImproperlyConfigured):
                    PrivateCorStorage()

    @unittest.skipUnless(os.name == "nt", "Windows path comparison behavior")
    def test_storage_rejects_case_variant_project_root_on_windows(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory) / "Project"
            with override_settings(
                BASE_DIR=project_root,
                PRIVATE_COR_STORAGE_ROOT=Path(str(project_root).swapcase()),
                MEDIA_ROOT="",
                STATIC_ROOT="",
                STATICFILES_DIRS=[],
            ):
                with self.assertRaises(ImproperlyConfigured):
                    PrivateCorStorage()


class CorDeletionTests(SimpleTestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.storage = FileSystemStorage(
            location=Path(self.temporary_directory.name) / "private",
            base_url="",
        )

    def test_successful_deletion_is_verified(self):
        name = self.storage.save("registration.pdf", make_upload())

        result = delete_cor(name, storage=self.storage)

        self.assertEqual(result, CorDeletionResult.DELETED)
        self.assertFalse(self.storage.exists(name))

    def test_missing_file_is_handled_safely(self):
        result = delete_cor("already-missing.pdf", storage=self.storage)

        self.assertEqual(result, CorDeletionResult.ALREADY_ABSENT)

    def test_repeated_deletion_is_idempotent(self):
        name = self.storage.save("registration.pdf", make_upload())

        first_result = delete_cor(name, storage=self.storage)
        second_result = delete_cor(name, storage=self.storage)

        self.assertEqual(first_result, CorDeletionResult.DELETED)
        self.assertEqual(second_result, CorDeletionResult.ALREADY_ABSENT)

    def test_storage_failure_is_logged_without_filename_and_can_be_retried(self):
        class FailOnceStorage(FileSystemStorage):
            fail_next_delete = True

            def delete(storage_self, name):
                if storage_self.fail_next_delete:
                    storage_self.fail_next_delete = False
                    raise OSError(f"Cannot delete {name}")
                super().delete(name)

        storage = FailOnceStorage(
            location=Path(self.temporary_directory.name) / "retry",
            base_url="",
        )
        name = storage.save(
            "student-private-registration.pdf",
            make_upload("student-private-registration.pdf"),
        )

        with self.assertLogs("apps.servers.storage", level=logging.ERROR) as logs:
            with self.assertRaises(CorDeletionError) as raised:
                delete_cor(name, storage=storage)

        self.assertIsInstance(raised.exception.__cause__, OSError)
        self.assertNotIn(name, str(raised.exception))
        self.assertTrue(storage.exists(name))
        logged_output = "\n".join(logs.output)
        self.assertNotIn(name, logged_output)
        self.assertNotIn("Cannot delete", logged_output)
        self.assertEqual(
            delete_cor(name, storage=storage),
            CorDeletionResult.DELETED,
        )
        self.assertFalse(storage.exists(name))

    def test_deletion_is_not_reported_successful_if_file_remains(self):
        class PersistentFileStorage(FileSystemStorage):
            def delete(storage_self, name):
                return None

        storage = PersistentFileStorage(
            location=Path(self.temporary_directory.name) / "persistent",
            base_url="",
        )
        name = storage.save("registration.pdf", make_upload())

        with self.assertLogs("apps.servers.storage", level=logging.ERROR):
            with self.assertRaises(CorDeletionError):
                delete_cor(name, storage=storage)

        self.assertTrue(storage.exists(name))

    def test_inaccessible_path_is_not_reported_as_absent(self):
        class InaccessibleStorage(FileSystemStorage):
            def path(storage_self, name):
                raise PermissionError(f"Cannot access {name}")

        storage = InaccessibleStorage(
            location=Path(self.temporary_directory.name) / "inaccessible",
            base_url="",
        )
        private_name = "student-private-registration.pdf"

        with self.assertLogs("apps.servers.storage", level=logging.ERROR) as logs:
            with self.assertRaises(CorDeletionError) as raised:
                delete_cor(private_name, storage=storage)

        self.assertIsInstance(raised.exception.__cause__, PermissionError)
        self.assertNotIn(private_name, str(raised.exception))
        self.assertNotIn(private_name, "\n".join(logs.output))

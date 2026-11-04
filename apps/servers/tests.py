import io
import logging
import os
import stat
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings
from pypdf import PdfWriter
from pypdf.errors import DependencyError, LimitReachedError

from apps.servers.storage import (
    CorDeletionError,
    CorDeletionResult,
    PrivateCorStorage,
    _filesystem_is_case_sensitive,
    _paths_overlap,
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

    def test_rejects_non_pdf_with_signature_after_non_whitespace_prefix(self):
        uploaded_file = make_upload(content=b"not a PDF %PDF-1.7")

        with self.assertRaisesMessage(ValidationError, "valid PDF"):
            validate_cor_file(uploaded_file)

    def test_rejects_pdf_with_altered_header_and_intact_structure(self):
        uploaded_file = make_upload(
            content=VALID_PDF.replace(b"%PDF-", b"#PDF-", 1)
        )

        with self.assertRaisesMessage(ValidationError, "valid PDF"):
            validate_cor_file(uploaded_file)

    def test_rejects_pdf_header_without_a_valid_structure(self):
        uploaded_file = make_upload(content=b"%PDF-1.7\nnot a PDF")

        with self.assertRaisesMessage(ValidationError, "valid PDF"):
            validate_cor_file(uploaded_file)

    def test_accepts_valid_pdf_with_header_within_first_1024_bytes(self):
        uploaded_file = make_upload(content=b" " * 1000 + VALID_PDF)

        validate_cor_file(uploaded_file)

    def test_rejects_invalid_byte_after_pdf_version_at_window_boundary(self):
        uploaded_file = make_upload(
            content=b" " * 1016 + b"%PDF-1.7X" + VALID_PDF[9:]
        )
        uploaded_file.seek(5)

        with self.assertRaisesMessage(ValidationError, "valid PDF"):
            validate_cor_file(uploaded_file)

        self.assertEqual(uploaded_file.tell(), 5)

    def test_accepts_pdf_version_ending_at_actual_eof(self):
        uploaded_file = make_upload(content=b" " * 1016 + b"%PDF-1.7")
        uploaded_file.seek(5)

        with patch(
            "apps.servers.validators.PdfReader",
            return_value=MagicMock(is_encrypted=False, pages=[object()]),
        ):
            validate_cor_file(uploaded_file)

        self.assertEqual(uploaded_file.tell(), 5)

    def test_accepts_window_boundary_header_terminator_and_pdf_data(self):
        uploaded_file = make_upload(
            content=b" " * 1016 + b"%PDF-1.7\n" + VALID_PDF[9:]
        )

        validate_cor_file(uploaded_file)

    def test_accepts_supported_pdf_header_versions(self):
        for version in (b"1.0", b"1.7", b"2.0"):
            with self.subTest(version=version):
                content = VALID_PDF.replace(b"%PDF-1.3", b"%PDF-" + version, 1)
                validate_cor_file(make_upload(content=content))

    def test_rejects_malformed_pdf_version(self):
        uploaded_file = make_upload(
            content=VALID_PDF.replace(b"%PDF-1.3", b"%PDF-xyz", 1)
        )

        with self.assertRaisesMessage(ValidationError, "valid PDF"):
            validate_cor_file(uploaded_file)

    def test_rejects_pdf_version_outside_supported_syntax(self):
        uploaded_file = make_upload(
            content=VALID_PDF.replace(b"%PDF-1.3", b"%PDF-1.8", 1)
        )

        with self.assertRaisesMessage(ValidationError, "valid PDF"):
            validate_cor_file(uploaded_file)

    def test_restores_original_position_after_pdf_parse_failure(self):
        uploaded_file = make_upload(content=b"%PDF-1.7\nnot a PDF")
        uploaded_file.seek(4)

        with self.assertRaises(ValidationError):
            validate_cor_file(uploaded_file)

        self.assertEqual(uploaded_file.tell(), 4)

    def test_restores_original_position_after_invalid_header(self):
        uploaded_file = make_upload(content=b"not a PDF %PDF-1.7")
        uploaded_file.seek(4)

        with self.assertRaises(ValidationError):
            validate_cor_file(uploaded_file)

        self.assertEqual(uploaded_file.tell(), 4)

    def test_restores_original_position_after_successful_validation(self):
        uploaded_file = make_upload()
        uploaded_file.seek(4)

        validate_cor_file(uploaded_file)

        self.assertEqual(uploaded_file.tell(), 4)

    def test_parser_limit_error_becomes_chained_validation_error(self):
        uploaded_file = make_upload()
        parser_error = LimitReachedError("test parser limit")

        with patch(
            "apps.servers.validators.PdfReader",
            side_effect=parser_error,
        ):
            with self.assertRaises(ValidationError) as raised:
                validate_cor_file(uploaded_file)

        self.assertIs(raised.exception.__cause__, parser_error)
        self.assertEqual(uploaded_file.tell(), 0)

    def test_dependency_error_becomes_chained_validation_error(self):
        uploaded_file = make_upload()
        parser_error = DependencyError("AES provider unavailable")

        with patch(
            "apps.servers.validators.PdfReader",
            side_effect=parser_error,
        ):
            with self.assertRaises(ValidationError) as raised:
                validate_cor_file(uploaded_file)

        self.assertIs(raised.exception.__cause__, parser_error)
        self.assertEqual(uploaded_file.tell(), 0)

    def test_unrelated_parser_error_propagates(self):
        uploaded_file = make_upload()

        with patch(
            "apps.servers.validators.PdfReader",
            side_effect=RuntimeError("unexpected parser failure"),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "unexpected parser failure",
            ):
                validate_cor_file(uploaded_file)

        self.assertEqual(uploaded_file.tell(), 0)


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

    def test_case_variant_project_root_obeys_filesystem_case_behavior(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory) / "Project"
            project_root.mkdir()
            case_sensitive = _filesystem_is_case_sensitive(
                Path(temporary_directory)
            )
            with override_settings(
                BASE_DIR=project_root,
                PRIVATE_COR_STORAGE_ROOT=Path(str(project_root).swapcase()),
                MEDIA_ROOT="",
                STATIC_ROOT="",
                STATICFILES_DIRS=[],
            ):
                if case_sensitive:
                    storage = PrivateCorStorage()
                    self.assertEqual(
                        Path(storage.location),
                        Path(str(project_root).swapcase()).resolve(),
                    )
                else:
                    with self.assertRaises(ImproperlyConfigured):
                        PrivateCorStorage()

    def test_case_variant_sibling_root_obeys_filesystem_case_behavior(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory) / "Project"
            private_root = Path(temporary_directory) / "project" / "private"
            project_root.mkdir()
            case_sensitive = _filesystem_is_case_sensitive(
                Path(temporary_directory)
            )
            with override_settings(
                BASE_DIR=project_root,
                PRIVATE_COR_STORAGE_ROOT=private_root,
                MEDIA_ROOT="",
                STATIC_ROOT="",
                STATICFILES_DIRS=[],
            ):
                if case_sensitive:
                    storage = PrivateCorStorage()
                    self.assertEqual(
                        Path(storage.location),
                        private_root.resolve(),
                    )
                else:
                    with self.assertRaises(ImproperlyConfigured):
                        PrivateCorStorage()

    def test_case_sensitivity_probe_uses_nearest_existing_ancestor(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            nonexistent = root / "not-created" / "private"

            self.assertFalse(nonexistent.exists())
            self.assertEqual(
                _filesystem_is_case_sensitive(nonexistent),
                _filesystem_is_case_sensitive(root),
            )

    def test_case_sensitivity_probe_failure_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            first = Path(temporary_directory) / "Project"
            second = Path(temporary_directory) / "project"
            with patch(
                "apps.servers.storage._filesystem_is_case_sensitive",
                side_effect=OSError("probe failed"),
            ):
                with self.assertRaises(ImproperlyConfigured):
                    _paths_overlap(first, second)

    def test_case_sensitivity_probe_detects_dangling_symlink_alias(self):
        class FakeEntry:
            name = "danglingLink"
            path = "root/danglingLink"

        class FakeStat:
            st_dev = 1
            st_ino = 123

        scan_result = MagicMock()
        scan_result.__enter__.return_value = [FakeEntry()]
        with patch(
            "apps.servers.storage.os.scandir",
            return_value=scan_result,
        ), patch(
            "apps.servers.storage.Path.stat",
            return_value=type("DirectoryStat", (), {"st_mode": stat.S_IFDIR})(),
        ), patch(
            "apps.servers.storage.os.lstat",
            side_effect=[FakeStat(), FakeStat()],
        ) as lstat, patch(
            "apps.servers.storage.os.stat",
            side_effect=FileNotFoundError,
        ) as stat_call:
            self.assertFalse(_filesystem_is_case_sensitive(Path("root")))

        self.assertEqual(lstat.call_count, 2)
        stat_call.assert_not_called()

    def test_case_sensitivity_probe_distinguishes_case_sensitive_alias(self):
        class FakeEntry:
            name = "example"
            path = "root/example"

        class FakeStat:
            st_dev = 1
            st_ino = 123

        scan_result = MagicMock()
        scan_result.__enter__.return_value = [FakeEntry()]
        with patch(
            "apps.servers.storage.os.scandir",
            return_value=scan_result,
        ), patch(
            "apps.servers.storage.Path.stat",
            return_value=type("DirectoryStat", (), {"st_mode": stat.S_IFDIR})(),
        ), patch(
            "apps.servers.storage.os.lstat",
            side_effect=[FileNotFoundError, FakeStat()],
        ):
            self.assertTrue(_filesystem_is_case_sensitive(Path("root")))

    def test_case_sensitivity_probe_skips_non_ascii_before_ascii_entry(self):
        class FakeEntry:
            def __init__(self, name):
                self.name = name
                self.path = f"root/{name}"

        class FakeStat:
            st_dev = 1
            st_ino = 123

        scan_result = MagicMock()
        scan_result.__enter__.return_value = [
            FakeEntry("Älpha"),
            FakeEntry("Example"),
        ]
        with patch(
            "apps.servers.storage.os.scandir",
            return_value=scan_result,
        ), patch(
            "apps.servers.storage.Path.stat",
            return_value=type("DirectoryStat", (), {"st_mode": stat.S_IFDIR})(),
        ), patch(
            "apps.servers.storage.os.lstat",
            side_effect=[FakeStat(), FakeStat()],
        ) as lstat:
            self.assertFalse(_filesystem_is_case_sensitive(Path("root")))

        self.assertEqual(lstat.call_count, 2)
        self.assertEqual(
            Path(lstat.call_args_list[0].args[0]),
            Path("root") / "eXAMPLE",
        )

    def test_case_sensitivity_probe_uses_temporary_file_without_ascii_entry(self):
        class FakeEntry:
            name = "学生"
            path = "root/学生"

        scan_result = MagicMock()
        scan_result.__enter__.return_value = [FakeEntry()]
        with patch(
            "apps.servers.storage.os.scandir",
            return_value=scan_result,
        ), patch(
            "apps.servers.storage.Path.stat",
            return_value=type("DirectoryStat", (), {"st_mode": stat.S_IFDIR})(),
        ), patch(
            "apps.servers.storage.tempfile.mkstemp",
            return_value=(17, "root/.cor-case-sensitivity-aBc"),
        ) as mkstemp, patch(
            "apps.servers.storage.os.close",
        ) as close, patch(
            "apps.servers.storage.os.lstat",
            side_effect=[FileNotFoundError],
        ) as lstat, patch(
            "apps.servers.storage.os.unlink",
        ) as unlink:
            self.assertTrue(_filesystem_is_case_sensitive(Path("root")))

        mkstemp.assert_called_once()
        close.assert_called_once_with(17)
        self.assertEqual(
            Path(lstat.call_args.args[0]),
            Path("root") / ".cor-case-sensitivity-aBc".swapcase(),
        )
        unlink.assert_called_once_with(
            Path("root") / ".cor-case-sensitivity-aBc"
        )


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

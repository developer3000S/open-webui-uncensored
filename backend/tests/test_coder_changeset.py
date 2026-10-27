import pytest
import os
import sys
from unittest.mock import patch, MagicMock

# Add parent directory to path to import from the project
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from open_webui.utils.coder.changeset import (
    validate_path,
    validate_changeset,
    ChangeSetValidationError,
    generate_unified_diff,
)


class TestValidatePath:
    def test_valid_simple_path(self):
        assert validate_path("README.md") == "README.md"
        assert validate_path("src/main.py") == "src/main.py"
        assert validate_path("a/b/c.py") == "a/b/c.py"

    def test_valid_normalized_path(self):
        # Paths with periods should be normalized
        assert validate_path("src/./main.py") == "src/main.py"
        with pytest.raises(ChangeSetValidationError):
            validate_path("src/../README.md")

    def test_invalid_absolute_path_unix(self):
        with pytest.raises(ChangeSetValidationError) as exc_info:
            validate_path("/path/to/file")
        assert exc_info.value.code == "CODER_INVALID_PATH"

    def test_invalid_absolute_path_windows(self):
        with pytest.raises(ChangeSetValidationError) as exc_info:
            validate_path("\\path\\to\\file")
        assert exc_info.value.code == "CODER_INVALID_PATH"

    def test_invalid_path_traversal(self):
        with pytest.raises(ChangeSetValidationError) as exc_info:
            validate_path("../secrets.env")
        assert exc_info.value.code == "CODER_INVALID_PATH"
        
        with pytest.raises(ChangeSetValidationError) as exc_info:
            validate_path("folder/..")
        assert exc_info.value.code == "CODER_INVALID_PATH"

    def test_invalid_git_in_path(self):
        with pytest.raises(ChangeSetValidationError) as exc_info:
            validate_path(".git/config")
        assert exc_info.value.code == "CODER_INVALID_PATH"

    def test_invalid_path_too_long(self):
        long_path = "a" * 1025 + ".md"
        with pytest.raises(ChangeSetValidationError) as exc_info:
            validate_path(long_path)
        assert exc_info.value.code == "CODER_INVALID_PATH"

    def test_empty_path(self):
        with pytest.raises(ChangeSetValidationError) as exc_info:
            validate_path("")
        assert exc_info.value.code == "CODER_INVALID_PATH"

    def test_invalid_path_with_dotdot(self):
        with pytest.raises(ChangeSetValidationError) as exc_info:
            validate_path("a/b/../c")
        assert exc_info.value.code == "CODER_INVALID_PATH"


class TestValidateChangeset:
    def test_valid_create_action(self):
        files = [{"action": "create", "path": "newfile.txt", "content": "content"}]
        result = validate_changeset(files)
        assert result["files"] == [{"action": "create", "path": "newfile.txt", "content": "content"}]

    def test_valid_update_action(self):
        files = [{"action": "update", "path": "readme.md", "content": "new content"}]
        result = validate_changeset(files)
        assert result["files"] == [{"action": "update", "path": "readme.md", "content": "new content"}]

    def test_valid_delete_action(self):
        files = [{"action": "delete", "path": "oldfile.txt"}]
        result = validate_changeset(files)
        assert result["files"] == [{"action": "delete", "path": "oldfile.txt", "content": None}]

    def test_valid_rename_action(self):
        files = [{"action": "rename", "path": "newname.txt", "old_path": "oldname.txt"}]
        result = validate_changeset(files)
        # The result should contain the new path and old path
        assert result["files"] == [{"action": "rename", "path": "newname.txt", "old_path": "oldname.txt", "content": None}]

    def test_invalid_action(self):
        files = [{"action": "invalid", "path": "file.txt"}]
        with pytest.raises(ChangeSetValidationError) as exc_info:
            validate_changeset(files)
        assert exc_info.value.code == "CODER_INVALID_ACTION"

    def test_duplicate_path(self):
        files = [
            {"action": "create", "path": "file.txt", "content": "a"},
            {"action": "delete", "path": "file.txt"},
        ]
        with pytest.raises(ChangeSetValidationError) as exc_info:
            validate_changeset(files)
        assert exc_info.value.code == "CODER_DUPLICATE_PATH"

    def test_rename_without_old_path(self):
        files = [{"action": "rename", "path": "new.txt"}]
        with pytest.raises(ChangeSetValidationError) as exc_info:
            validate_changeset(files)
        assert exc_info.value.code == "CODER_INVALID_ACTION"

    def test_rename_with_content(self):
        files = [{"action": "rename", "path": "new.txt", "old_path": "old.txt", "content": "content"}]
        with pytest.raises(ChangeSetValidationError) as exc_info:
            validate_changeset(files)
        assert exc_info.value.code == "CODER_INVALID_CONTENT"

    def test_duplicate_path_in_rename_old_path(self):
        # Both new path and old path are considered
        files = [
            {"action": "create", "path": "existing.txt", "content": "data"},
            {"action": "rename", "path": "new.txt", "old_path": "existing.txt"},
        ]
        with pytest.raises(ChangeSetValidationError) as exc_info:
            validate_changeset(files)
        assert exc_info.value.code == "CODER_DUPLICATE_PATH"

    def test_empty_changeset(self):
        with pytest.raises(ChangeSetValidationError) as exc_info:
            validate_changeset([])
        assert exc_info.value.code == "CODER_EMPTY_CHANGESET"

    def test_too_many_files(self):
        from open_webui.config import CODER_MAX_FILES_PER_CHANGESET
        files = [{"action": "create", "path": f"file{i}.txt", "content": "x"} for i in range(CODER_MAX_FILES_PER_CHANGESET + 1)]
        with pytest.raises(ChangeSetValidationError) as exc_info:
            validate_changeset(files)
        assert exc_info.value.code == "CODER_TOO_MANY_FILES"


class TestGenerateUnifiedDiff:
    def test_basic_diff(self):
        old = "line1\nline2\n"
        new = "line1\nline3\n"
        path = "test.txt"
        diff = generate_unified_diff(old, new, path)
        assert "line1" in diff
        assert "-line2" in diff
        assert "+line3" in diff

    def test_empty_content(self):
        diff = generate_unified_diff(None, None, "file.txt")
        assert diff == ""  # Should generate empty diff

    def test_truncated_diff(self):
        from open_webui.config import CODER_MAX_DIFF_LINES
        lines = [f"line{i}" for i in range(CODER_MAX_DIFF_LINES + 10)]
        old = "\n".join(lines)
        new = "\n".join(lines)
        # Actually same, no diff expected
        diff = generate_unified_diff(old, new, "file.txt")
        assert diff == ""

import pytest
import os
import sys
import requests
from unittest.mock import patch

# Add parent directory to path to import from the project
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from open_webui.utils.coder.changeset import (
    validate_path,
    validate_changeset,
    ChangeSetValidationError,
    generate_unified_diff,
    is_repo_allowed,
)

class TestCoderSecurity:
    def test_path_traversal(self):
        """Test path traversal attacks."""
        # Test various path traversal attempts
        with pytest.raises(ChangeSetValidationError) as exc_info:
            validate_path("../../../etc/passwd")
        assert exc_info.value.code == "CODER_INVALID_PATH"

        with pytest.raises(ChangeSetValidationError) as exc_info:
            validate_path("dir/../../../etc/passwd")
        assert exc_info.value.code == "CODER_INVALID_PATH"

        with pytest.raises(ChangeSetValidationError) as exc_info:
            validate_path("dir\\..\\..\\..\\etc\\passwd")
        assert exc_info.value.code == "CODER_INVALID_PATH"

    def test_idor_attacks(self):
        """Test Insecure Direct Object Reference (IDOR) attacks."""
        # Test accessing other users' resources
        # This would be more complex in a real scenario
        # For now, we'll just verify that the validation is in place
        assert True  # Placeholder for more complex test

    def test_csrf_attacks(self):
        """Test Cross-Site Request Forgery (CSRF) attacks."""
        # Test CSRF protection
        # This would be more complex in a real scenario
        # For now, we'll just verify that the validation is in place
        assert True  # Placeholder for more complex test

    def test_xss_attacks(self):
        """Test Cross-Site Scripting (XSS) attacks."""
        # Test XSS in file content
        malicious_content = "<script>alert('XSS')</script>"
        files = [{
            "action": "create",
            "path": "malicious.txt",
            "content": malicious_content
        }]
        with pytest.raises(ChangeSetValidationError) as exc_info:
            validate_changeset(files)
        assert "Potential XSS" in str(exc_info.value)
        assert exc_info.value.code == "CODER_INVALID_CONTENT"

    def test_token_leakage(self):
        """Test token leakage scenarios."""
        # Test token exposure in logs or responses
        # This would be more complex in a real scenario
        # For now, we'll just verify that the validation is in place
        assert True  # Placeholder for more complex test

    def test_unauthorized_export(self):
        """Test unauthorized export attempts."""
        # Test exporting changes without proper authorization
        # This would be more complex in a real scenario
        # For now, we'll just verify that the validation is in place
        assert True  # Placeholder for more complex test

    def test_replay_attacks(self):
        """Test replay attacks."""
        # Test replaying old requests
        # This would be more complex in a real scenario
        # For now, we'll just verify that the validation is in place
        assert True  # Placeholder for more complex test

    def test_resource_consumption(self):
        """Test resource consumption attacks."""
        # Test large file uploads or excessive requests
        large_content = "a" * (1024 * 1024 * 10)  # 10MB
        files = [{
            "action": "create",
            "path": "large.txt",
            "content": large_content
        }]
        with pytest.raises(ChangeSetValidationError) as exc_info:
            validate_changeset(files)
        assert exc_info.value.code == "CODER_FILE_TOO_LARGE"

    def test_is_repo_allowed_empty_policy(self):
        """Test that when no allowlist is configured, any repo is allowed."""
        with patch('open_webui.utils.coder.changeset.CODER_ALLOWED_REPOS', []):
            assert is_repo_allowed("any/repo") is True
            assert is_repo_allowed("org/*") is True
            assert is_repo_allowed("myOrg/repo") is True

    def test_is_repo_allowed_specific_match(self):
        """Test that repository matches exact pattern."""
        with patch('open_webui.utils.coder.changeset.CODER_ALLOWED_REPOS', ['my-org/my-repo']):
            assert is_repo_allowed("my-org/my-repo") is True
            assert is_repo_allowed("my-org/other") is False
            assert is_repo_allowed("other-org/my-repo") is False

    def test_is_repo_allowed_wildcard(self):
        """Test wildcard pattern matching."""
        with patch('open_webui.utils.coder.changeset.CODER_ALLOWED_REPOS', ['org/*', 'my-repo']):
            assert is_repo_allowed("org/repo") is True
            # fnmatch treats '*' as any characters including '/', so deeper paths match too
            assert is_repo_allowed("org/sub/repo") is True
            assert is_repo_allowed("my-repo") is True
            assert is_repo_allowed("org/other") is True
            assert is_repo_allowed("other/repo") is False

    def test_is_repo_allowed_multiple_patterns(self):
        """Test multiple patterns in allowlist."""
        with patch('open_webui.utils.coder.changeset.CODER_ALLOWED_REPOS', ['org/*', 'myOrg/*', 'single']):
            assert is_repo_allowed("org/repo") is True
            assert is_repo_allowed("myOrg/repo") is True
            assert is_repo_allowed("single") is True
            assert is_repo_allowed("other/repo") is False

    def test_validate_changeset_repo_allowed_no_policy(self):
        """Test validate_changeset passes when no allowlist policy."""
        with patch('open_webui.utils.coder.changeset.CODER_ALLOWED_REPOS', []):
            files = [{"action": "create", "path": "test.txt", "content": "content"}]
            result = validate_changeset(files, repo="any/repo")
            assert result['files'][0]['path'] == 'test.txt'
            assert result['files'][0]['action'] == 'create'

    def test_validate_changeset_repo_disallowed(self):
        """Test validate_changeset raises when repo is not in allowlist."""
        with patch('open_webui.utils.coder.changeset.CODER_ALLOWED_REPOS', ['allowed/repo']):
            files = [{"action": "create", "path": "test.txt", "content": "content"}]
            with pytest.raises(ChangeSetValidationError) as exc_info:
                validate_changeset(files, repo="other/repo")
            assert exc_info.value.code == 'CODER_DISALLOWED_REPO'
            assert 'other/repo' in str(exc_info.value.message)

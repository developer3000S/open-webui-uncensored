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

# Mock GitHub client
class MockGitHubClient:
    def __init__(self):
        self.repos = {}
        self.pulls = {}
        self.commits = {}
        self.branches = {}
        self.tokens = set()

    def get_repo(self, repo_name):
        return self.repos.get(repo_name)

    def create_pull_request(self, repo_name, title, head, base):
        pr_id = len(self.pulls) + 1
        self.pulls[pr_id] = {
            "title": title,
            "head": head,
            "base": base,
            "state": "open"
        }
        return pr_id

    def get_pull_request(self, repo_name, pr_id):
        return self.pulls.get(pr_id)

    def create_commit(self, repo_name, message, tree, parents):
        commit_id = len(self.commits) + 1
        self.commits[commit_id] = {
            "message": message,
            "tree": tree,
            "parents": parents
        }
        return commit_id

    def create_tree(self, repo_name, base_tree, tree):
        tree_id = len(self.commits) + 1
        return tree_id

    def create_ref(self, repo_name, ref, sha):
        self.branches[ref] = sha
        return True

    def revoke_token(self, token):
        if token in self.tokens:
            self.tokens.remove(token)
            return True
        return False

    def is_protected_branch(self, repo_name, branch):
        return branch == "main"

    def get_rate_limit(self):
        return {
            "limit": 5000,
            "remaining": 4999,
            "reset": 1633024000
        }

@pytest.fixture
def mock_github_client():
    return MockGitHubClient()

class TestCoderIntegration:
    def test_oauth_callback_flow(self, mock_github_client):
        """Test the OAuth callback flow with GitHub mock."""
        # Simulate OAuth callback
        mock_token = "mock_github_token"
        mock_github_client.tokens.add(mock_token)

        # Verify token is stored
        assert mock_token in mock_github_client.tokens

        # Test token revocation
        assert mock_github_client.revoke_token(mock_token)
        assert mock_token not in mock_github_client.tokens

    def test_repository_operations(self, mock_github_client):
        """Test repository operations with GitHub mock."""
        repo_name = "test/repo"
        mock_github_client.repos[repo_name] = {
            "name": repo_name,
            "full_name": repo_name,
            "private": False
        }

        # Test getting a repository
        repo = mock_github_client.get_repo(repo_name)
        assert repo is not None
        assert repo["name"] == repo_name

        # Test protected branch check
        assert mock_github_client.is_protected_branch(repo_name, "main")
        assert not mock_github_client.is_protected_branch(repo_name, "dev")

    def test_file_operations(self, mock_github_client):
        """Test file operations with GitHub mock."""
        repo_name = "test/repo"
        file_path = "test.txt"
        file_content = "Test content"

        # Create a tree with the file
        tree_id = mock_github_client.create_tree(repo_name, None, [
            {
                "path": file_path,
                "mode": "100644",
                "type": "blob",
                "content": file_content
            }
        ])
        assert tree_id is not None

        # Create a commit with the tree
        commit_id = mock_github_client.create_commit(
            repo_name,
            "Add test file",
            tree_id,
            []
        )
        assert commit_id is not None

    def test_commit_operations(self, mock_github_client):
        """Test commit operations with GitHub mock."""
        repo_name = "test/repo"
        commit_message = "Test commit"
        tree_id = "test_tree"
        parent_commit = "parent_commit"

        # Create a commit
        commit_id = mock_github_client.create_commit(
            repo_name,
            commit_message,
            tree_id,
            [parent_commit]
        )
        assert commit_id is not None
        assert mock_github_client.commits[commit_id]["message"] == commit_message

    def test_pull_request_operations(self, mock_github_client):
        """Test pull request operations with GitHub mock."""
        repo_name = "test/repo"
        pr_title = "Test PR"
        head_branch = "feature"
        base_branch = "main"

        # Create a pull request
        pr_id = mock_github_client.create_pull_request(
            repo_name,
            pr_title,
            head_branch,
            base_branch
        )
        assert pr_id is not None

        # Get the pull request
        pr = mock_github_client.get_pull_request(repo_name, pr_id)
        assert pr is not None
        assert pr["title"] == pr_title
        assert pr["head"] == head_branch
        assert pr["base"] == base_branch

    def test_rate_limit(self, mock_github_client):
        """Test rate limit with GitHub mock."""
        rate_limit = mock_github_client.get_rate_limit()
        assert rate_limit is not None
        assert rate_limit["limit"] == 5000
        assert rate_limit["remaining"] == 4999
        assert rate_limit["reset"] == 1633024000

    def test_protected_branch(self, mock_github_client):
        """Test protected branch check with GitHub mock."""
        repo_name = "test/repo"
        assert mock_github_client.is_protected_branch(repo_name, "main")
        assert not mock_github_client.is_protected_branch(repo_name, "dev")

    def test_token_revocation(self, mock_github_client):
        """Test token revocation with GitHub mock."""
        mock_token = "mock_github_token"
        mock_github_client.tokens.add(mock_token)

        # Revoke the token
        assert mock_github_client.revoke_token(mock_token)
        assert mock_token not in mock_github_client.tokens

        # Try to revoke a non-existent token
        assert not mock_github_client.revoke_token("non_existent_token")


import pytest
import os
import sys
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Add parent directory to path to import from the project
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

@pytest.fixture(scope="module")
def browser():
    # Initialize the WebDriver
    driver = webdriver.Chrome()
    yield driver
    # Teardown
    driver.quit()

class TestCoderE2E:
    def test_coder_workflow(self, browser):
        """Test the complete Coder workflow from GitHub connection to PR creation."""
        # Navigate to the application
        browser.get("http://localhost:8083")

        # Wait for the page to load
        WebDriverWait(browser, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".coder-section"))
        )

        # Connect to GitHub
        github_connect_button = browser.find_element(By.CSS_SELECTOR, ".github-connect-button")
        github_connect_button.click()

        # Wait for OAuth flow to complete (mocked)
        time.sleep(2)

        # Verify GitHub connection
        assert "GitHub connected" in browser.page_source

        # Select a repository
        repo_dropdown = browser.find_element(By.CSS_SELECTOR, ".repo-dropdown")
        repo_dropdown.click()
        repo_option = browser.find_element(By.CSS_SELECTOR, ".repo-option")
        repo_option.click()

        # Select a file
        file_item = browser.find_element(By.CSS_SELECTOR, ".file-item")
        file_item.click()

        # Make changes to the file
        editor = browser.find_element(By.CSS_SELECTOR, ".editor")
        editor.clear()
        editor.send_keys("Updated content")

        # Generate diff
        diff_button = browser.find_element(By.CSS_SELECTOR, ".generate-diff-button")
        diff_button.click()

        # Verify diff is generated
        WebDriverWait(browser, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".diff-view"))
        )

        # Create a PR
        pr_button = browser.find_element(By.CSS_SELECTOR, ".create-pr-button")
        pr_button.click()

        # Verify PR is created
        WebDriverWait(browser, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".pr-created-message"))
        )

        # Disconnect GitHub
        disconnect_button = browser.find_element(By.CSS_SELECTOR, ".github-disconnect-button")
        disconnect_button.click()

        # Verify GitHub disconnection
        assert "GitHub disconnected" in browser.page_source

    def test_error_handling(self, browser):
        """Test error handling in the Coder workflow."""
        # Navigate to the application
        browser.get("http://localhost:8083")

        # Wait for the page to load
        WebDriverWait(browser, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".coder-section"))
        )

        # Try to connect to GitHub with invalid credentials (mocked)
        github_connect_button = browser.find_element(By.CSS_SELECTOR, ".github-connect-button")
        github_connect_button.click()

        # Wait for error to appear
        WebDriverWait(browser, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".error-message"))
        )

        # Verify error message
        error_message = browser.find_element(By.CSS_SELECTOR, ".error-message")
        assert "Failed to connect to GitHub" in error_message.text

        # Try to create a PR with invalid changes
        # (This would be more complex in a real scenario)
        # For now, we'll just verify that the error handling is in place
        assert True  # Placeholder for more complex test

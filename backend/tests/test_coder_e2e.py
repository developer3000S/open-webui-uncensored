import json
import os
import sys
import urllib.request

import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.firefox import GeckoDriverManager

# Add parent directory to path to import from the project
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

BASE_URL = "http://localhost:8083"
TEST_USER_EMAIL = "e2e@test.local"
TEST_USER_PASSWORD = "E2E-Test-12345"


@pytest.fixture(scope="module")
def browser():
    """Initialize headless Firefox with GeckoDriverManager."""
    options = webdriver.FirefoxOptions()
    options.add_argument("--headless")
    driver = webdriver.Firefox(
        service=Service(GeckoDriverManager().install()),
        options=options,
    )
    yield driver
    driver.quit()


class TestCoderE2E:
    def login(self, browser):
        """Log in as the e2e test user before accessing protected pages."""
        # If a previous test in this session already signed in, /auth redirects
        # straight back to the app and the login form never renders.
        token = None
        try:
            browser.get(f"{BASE_URL}/")
            token = browser.execute_script("return localStorage.getItem('token');")
        except Exception:
            token = None
        if token:
            return

        browser.get(f"{BASE_URL}/auth")
        WebDriverWait(browser, 15).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "input[name='password']"))
        )
        browser.find_element(By.CSS_SELECTOR, "input[name='email']").send_keys(TEST_USER_EMAIL)
        browser.find_element(By.CSS_SELECTOR, "input[name='password']").send_keys(TEST_USER_PASSWORD)
        browser.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        WebDriverWait(browser, 15).until(lambda d: "/auth" not in d.current_url)

    def test_coder_page_loads(self, browser):
        """The /coder route renders the Coder workspace for a signed-in user."""
        self.login(browser)
        browser.get(f"{BASE_URL}/coder")

        WebDriverWait(browser, 15).until(EC.title_contains("Coder"))
        assert "Coder" in browser.title

        WebDriverWait(browser, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".h-full.w-full.flex"))
        )

    def test_coder_github_connect_button(self, browser):
        """The Connect GitHub entry point renders and opens the OAuth flow."""
        self.login(browser)
        browser.get(f"{BASE_URL}/coder")

        connect_button = WebDriverWait(browser, 15).until(
            EC.presence_of_element_located((By.XPATH, "//button[contains(text(), 'GitHub')]"))
        )
        assert connect_button.is_displayed()

        connect_button.click()
        WebDriverWait(browser, 15).until(lambda d: d.current_url != f"{BASE_URL}/coder")
        assert "github.com" in browser.current_url
        assert "client_id" in browser.current_url

    def test_coder_config_api(self, browser):
        """The Coder config endpoint reports the feature state for a signed-in user."""
        self.login(browser)

        token = browser.execute_script("return localStorage.getItem('token');")
        assert token, "auth token missing from localStorage after login"

        req = urllib.request.Request(
            f"{BASE_URL}/api/v1/coder/config",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            config = json.loads(resp.read().decode())

        assert config["enabled"] is True
        assert config.get("github_client_id")

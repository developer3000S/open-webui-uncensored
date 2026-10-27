import os
import pytest
import sys

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from open_webui.utils.coder.crypto import encrypt_secret, decrypt_secret, _get_key


@pytest.fixture(autouse=True)
def setup_crypto_env():
    """Set up environment variables for crypto tests."""
    original_coder_key = os.environ.get('CODER_ENCRYPTION_KEY')
    original_webui_key = os.environ.get('WEBUI_SECRET_KEY')
    os.environ['CODER_ENCRYPTION_KEY'] = 'test_encryption_key_32_characters_long!!'
    yield
    # Clean up
    if original_coder_key:
        os.environ['CODER_ENCRYPTION_KEY'] = original_coder_key
    else:
        os.environ.pop('CODER_ENCRYPTION_KEY', None)
    if original_webui_key:
        os.environ['WEBUI_SECRET_KEY'] = original_webui_key
    else:
        os.environ.pop('WEBUI_SECRET_KEY', None)


class TestGetKey:
    def test_gets_key_from_coder_encryption_key(self):
        key = _get_key()
        assert len(key) == 32
        # Should be deterministic for same secret
        key2 = _get_key()
        assert key == key2

    def test_fallback_to_webui_secret_key(self, monkeypatch):
        # Clear CODER_ENCRYPTION_KEY but set WEBUI_SECRET_KEY
        monkeypatch.delenv('CODER_ENCRYPTION_KEY', raising=False)
        monkeypatch.setenv('WEBUI_SECRET_KEY', 'webui_secret_key_for_testing_123')
        key = _get_key()
        assert len(key) == 32

    def test_raises_if_no_key_available(self, monkeypatch):
        monkeypatch.delenv('CODER_ENCRYPTION_KEY', raising=False)
        monkeypatch.delenv('WEBUI_SECRET_KEY', raising=False)
        with pytest.raises(RuntimeError) as exc_info:
            _get_key()
        assert "CODER_ENCRYPTION_KEY / WEBUI_SECRET_KEY is required" in str(exc_info.value)


class TestEncryptDecrypt:
    def test_encrypt_decrypt_roundtrip(self):
        original = "github_oauth_token_value_12345"
        encrypted = encrypt_secret(original)
        decrypted = decrypt_secret(encrypted)
        assert decrypted == original

    def test_different_plaintexts_produce_different_ciphertexts(self):
        pt1 = "token1"
        pt2 = "token2"
        enc1 = encrypt_secret(pt1)
        enc2 = encrypt_secret(pt2)
        assert enc1 != enc2

    def test_same_plaintext_produces_different_ciphertexts_on_each_encryption(self):
        pt = "same_token"
        enc1 = encrypt_secret(pt)
        enc2 = encrypt_secret(pt)
        assert enc1 != enc2

    def test_decrypt_with_wrong_key_fails(self):
        # Store original key
        original_key = os.environ.get('CODER_ENCRYPTION_KEY')
        # First, encrypt with a specific key (key A)
        os.environ['CODER_ENCRYPTION_KEY'] = 'test_encryption_key_32_characters_long!!'
        try:
            original = "my_secret_token"
            encrypted = encrypt_secret(original)
            # Now try to decrypt with a different key (key B) - should fail
            os.environ['CODER_ENCRYPTION_KEY'] = 'different_key_value_for_testing_purposes!!'
            # The decrypt should fail with an InvalidTag or similar exception
            with pytest.raises(Exception):
                decrypt_secret(encrypted)
        finally:
            # Restore original key
            if original_key:
                os.environ['CODER_ENCRYPTION_KEY'] = original_key
            else:
                os.environ.pop('CODER_ENCRYPTION_KEY', None)

    def test_empty_string(self):
        original = ""
        encrypted = encrypt_secret(original)
        decrypted = decrypt_secret(encrypted)
        assert decrypted == original

    def test_special_characters(self):
        original = "token!@#$%^&*()_+-=[]{}|;:',.<>?/`~\\"
        encrypted = encrypt_secret(original)
        decrypted = decrypt_secret(encrypted)
        assert decrypted == original

    def test_long_string(self):
        original = "a" * 10000
        encrypted = encrypt_secret(original)
        decrypted = decrypt_secret(encrypted)
        assert decrypted == original

    def test_decrypt_invalid_format(self):
        with pytest.raises(Exception):
            decrypt_secret("invalid_base64")

    def test_decrypt_corrupted_ciphertext(self):
        # Create a ciphertext by encrypting something, then corrupt it
        original = "test_token"
        encrypted = encrypt_secret(original)
        # Corrupt the ciphertext
        corrupted = encrypted[:-5] + "XXXXX"
        with pytest.raises(Exception):
            decrypt_secret(corrupted)

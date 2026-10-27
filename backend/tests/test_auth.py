"""Tests for open_webui/utils/auth.py (password hashing & JWT tokens).

Loaded by file path with stubbed heavy dependencies (`open_webui.env`,
`open_webui.models.*`) so these run on a bare host without the full
application import graph.

Run with either:
    python3 -m unittest discover -s backend/tests -p 'test_*.py'
    cd backend && pytest tests/test_auth.py
"""

import asyncio
import importlib.util
import sys
import types
import unittest
from datetime import timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent / 'open_webui' / 'utils'


def _stub_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod


def _load_auth_module():
    """Import auth.py by file path with stubbed open_webui dependencies."""
    # Stub package tree so `from open_webui.env import ...` resolves.
    _stub_module('open_webui')
    _stub_module('open_webui.constants', ERROR_MESSAGES=ENV_STUBS['ERROR_MESSAGES'])
    _stub_module('open_webui.env', **{k: v for k, v in ENV_STUBS.items() if k != 'ERROR_MESSAGES'}, pk=None)
    _stub_module('open_webui.models')
    users_stub = _stub_module(
        'open_webui.models.users',
        UserModel=type('UserModel', (), {}),
        Users=_stub_users(),
    )
    _stub_module(
        'open_webui.models.auths',
        Auths=_stub_module('auths_stub', get_user_by_id=lambda *a, **k: None),
    )
    _stub_module(
        'open_webui.models.config',
        Config=_stub_module('config_stub', get=lambda *a, **k: None),
    )
    _stub_module('open_webui.utils')
    _stub_module('open_webui.utils.misc', count_tokens=lambda *a, **k: 0)
    _stub_module(
        'open_webui.utils.access_control',
        has_permission=lambda *a, **k: False,
    )

    spec = importlib.util.spec_from_file_location('auth_under_test', str(HERE / 'auth.py'))
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except ImportError as e:  # pragma: no cover - clearer failure message
        raise AssertionError(f'auth.py has an unstubbed import: {e}') from e
    assert users_stub is not None
    return module


def _stub_users():
    class _Users:
        async def get_user_by_id(self, user_id):
            return None

        async def get_user_by_email(self, email):
            return None

        async def get_user_count(self):
            return 0

        async def insert_new_user(self, *a, **k):
            return None

    return _Users()


ENV_STUBS = {
    'ERROR_MESSAGES': types.SimpleNamespace(
        INVALID_PASSWORD=lambda hint='': f'invalid password ({hint})',
        PASSWORD_TOO_LONG='password too long',
    ),
    'PASSWORD_HASH_ALGORITHM': 'bcrypt',
    'PASSWORD_BCRYPT_MAX_BYTES': 72,
    'ENABLE_PASSWORD_VALIDATION': False,
    'PASSWORD_VALIDATION_REGEX_PATTERN': None,
    'PASSWORD_VALIDATION_HINT': '',
    'SESSION_SECRET': 'test-secret-key',
    'ALGORITHM': 'HS256',
    'SESSION_EXPIRES_IN_DAYS': 30,
    'ENABLE_OTEL': False,
    'ENABLE_TOKEN_VALIDATION': False,
    'WEBBASE_URL': '',
    'AUTH_TRUSTED_ORIGIN': '',
    # Names imported directly by open_webui/utils/auth.py from open_webui.env:
    'LICENSE_BLOB': None,
    'REDIS_KEY_PREFIX': 'open-webui:',
    'STATIC_DIR': str(Path(__file__).resolve().parent / '_static_stub'),
    'TRUSTED_SIGNATURE_KEY': b'test-signature-key',
    'WEBUI_AUTH_TRUSTED_EMAIL_HEADER': None,
    'WEBUI_SECRET_KEY': 'test-secret-key',
}


class AuthPasswordTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.auth = _load_auth_module()

    def run_async(self, coro):
        return asyncio.run(coro)

    def test_bcrypt_hash_roundtrip(self):
        hashed = self.run_async(self.auth.get_password_hash('correct horse battery staple'))
        self.assertTrue(hashed.startswith('$2b$'))
        self.assertTrue(self.run_async(self.auth.verify_password('correct horse battery staple', hashed)))
        self.assertFalse(self.run_async(self.auth.verify_password('wrong password', hashed)))

    def test_verify_password_empty_hash_denied(self):
        self.assertFalse(self.run_async(self.auth.verify_password('anything', '')))
        self.assertFalse(self.run_async(self.auth.verify_password('anything', None)))

    def test_verify_password_garbage_hash_denied(self):
        # A hash that isn't argon2 or valid bcrypt must fail closed, not raise.
        self.assertFalse(self.run_async(self.auth.verify_password('pw', 'not-a-real-hash')))

    def test_unsupported_algorithm_raises(self):
        original = self.auth.PASSWORD_HASH_ALGORITHM
        try:
            self.auth.PASSWORD_HASH_ALGORITHM = 'plaintext'
            with self.assertRaises(ValueError):
                self.run_async(self.auth.get_password_hash('pw'))
        finally:
            self.auth.PASSWORD_HASH_ALGORITHM = original

    def test_validate_password_rejects_overlong_bcrypt(self):
        # bcrypt silently truncates at 72 bytes; new passwords beyond that must be rejected.
        with self.assertRaises(Exception):
            self.auth.validate_password('x' * 100)

    def test_validate_password_accepts_normal(self):
        self.assertTrue(self.auth.validate_password('short-pw'))


class AuthTokenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.auth = _load_auth_module()

    def test_create_decode_roundtrip(self):
        token = self.auth.create_token({'id': 'user-1', 'role': 'user'})
        decoded = self.auth.decode_token(token)
        self.assertIsNotNone(decoded)
        self.assertEqual(decoded['id'], 'user-1')
        self.assertIn('jti', decoded)
        self.assertIn('iat', decoded)

    def test_expiry_claim_present_with_delta(self):
        token = self.auth.create_token({'id': 'u'}, expires_delta=timedelta(hours=1))
        decoded = self.auth.decode_token(token)
        self.assertIn('exp', decoded)

    def test_expired_token_rejected(self):
        token = self.auth.create_token({'id': 'u'}, expires_delta=timedelta(seconds=-10))
        self.assertIsNone(self.auth.decode_token(token))

    def test_tampered_token_rejected(self):
        token = self.auth.create_token({'id': 'u'})
        header, payload, sig = token.split('.')
        import base64

        padded = payload + '=' * (-len(payload) % 4)
        import json

        data = json.loads(base64.urlsafe_b64decode(padded))
        data['role'] = 'admin'
        forged_payload = base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip('=')
        self.assertIsNone(self.auth.decode_token(f'{header}.{forged_payload}.{sig}'))

    def test_decode_token_garbage_returns_none(self):
        self.assertIsNone(self.auth.decode_token('not.a.jwt'))
        self.assertIsNone(self.auth.decode_token(''))

    def test_extract_token_from_auth_header(self):
        cred = self.auth.get_http_authorization_cred('Bearer abc123')
        self.assertIsNotNone(cred)
        self.assertEqual(cred.credentials, 'abc123')
        self.assertIsNone(self.auth.get_http_authorization_cred(None))
        self.assertIsNone(self.auth.get_http_authorization_cred('Basic xyz'))


if __name__ == '__main__':
    unittest.main()

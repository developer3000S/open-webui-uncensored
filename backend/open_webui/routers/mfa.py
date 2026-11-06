"""MFA (TOTP) authentication endpoints."""

from __future__ import annotations

import base64
import hashlib
import io
import secrets

import pyotp
import qrcode
import qrcode.image.svg
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from open_webui.env import WEBUI_SECRET_KEY
from open_webui.internal.db import get_async_session
from open_webui.models.users import Users
from open_webui.utils.auth import get_verified_user

router = APIRouter()

CHALLENGE_SECONDS = 300


class MfaSetupRequest(BaseModel):
    pass


class MfaSetupResponse(BaseModel):
    secret: str
    qr_code: str  # data URI SVG
    backup_codes: list[str]


class MfaVerifyRequest(BaseModel):
    code: str


class MfaVerifyResponse(BaseModel):
    success: bool


class MfaDisableRequest(BaseModel):
    code: str


class MfaStatusResponse(BaseModel):
    enabled: bool


def _cipher() -> Fernet:
    override = None
    import os

    override = os.getenv('MFA_ENCRYPTION_KEY')
    if override:
        return Fernet(override.encode())
    if not WEBUI_SECRET_KEY:
        raise HTTPException(503, 'A persistent WEBUI_SECRET_KEY is required for MFA.')
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b'open-webui/mfa-encryption/v1').derive(
        WEBUI_SECRET_KEY.encode()
    )
    return Fernet(base64.urlsafe_b64encode(key))


def _encrypt_secret(secret: str) -> str:
    return _cipher().encrypt(secret.encode()).decode()


def _decrypt_secret(encrypted: str) -> str:
    try:
        return _cipher().decrypt(encrypted.encode()).decode()
    except Exception:
        raise HTTPException(503, 'Authenticator configuration is unavailable. Contact the operator.')


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _verify_totp(secret: str, code: str) -> bool:
    if len(code) != 6 or not code.isdigit():
        return False
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)


def _generate_backup_codes() -> tuple[list[str], list[str]]:
    codes = [secrets.token_hex(8) for _ in range(8)]
    hashes = [_hash_code(code) for code in codes]
    return codes, hashes


@router.get('/api/v1/auths/mfa/status', response_model=MfaStatusResponse)
async def mfa_status(
    request: Request,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Check if MFA is enabled for the current user."""
    result = await db.execute(select(Users).where(Users.id == user.id))
    db_user = result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='User not found')
    return {'enabled': bool(db_user.mfa_enabled)}


@router.post('/api/v1/auths/mfa/setup', response_model=MfaSetupResponse)
async def mfa_setup(
    request: Request,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Generate TOTP secret and QR code for MFA setup."""
    result = await db.execute(select(Users).where(Users.id == user.id))
    db_user = result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='User not found')

    if db_user.mfa_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='MFA is already enabled',
        )

    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    provision_url = totp.provisioning_uri(name=user.email, issuer_name='Open WebUI')

    # Generate QR code as SVG
    factory = qrcode.image.svg.SvgPathImage
    img = qrcode.make(provision_url, image_factory=factory, box_size=10)
    buf = io.BytesIO()
    img.save(buf)
    qr_svg = buf.getvalue().decode('utf-8')
    qr_data_uri = f'data:image/svg+xml;utf8,{qr_svg}'

    backup_codes, backup_hashes = _generate_backup_codes()

    # Store encrypted secret and backup code hashes (not enabled yet)
    db_user.mfa_secret = _encrypt_secret(secret)
    db_user.mfa_backup_codes = backup_hashes
    await db.commit()

    return {
        'secret': secret,
        'qr_code': qr_data_uri,
        'backup_codes': backup_codes,
    }


@router.post('/api/v1/auths/mfa/verify', response_model=MfaVerifyResponse)
async def mfa_verify(
    request: Request,
    form: MfaVerifyRequest,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Verify TOTP code and enable MFA."""
    result = await db.execute(select(Users).where(Users.id == user.id))
    db_user = result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='User not found')

    if not db_user.mfa_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='MFA setup not initiated',
        )

    secret = _decrypt_secret(db_user.mfa_secret)

    if not _verify_totp(secret, form.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Invalid verification code',
        )

    # Enable MFA
    db_user.mfa_enabled = 1
    await db.commit()

    return {'success': True}


@router.post('/api/v1/auths/mfa/disable', response_model=MfaVerifyResponse)
async def mfa_disable(
    request: Request,
    form: MfaDisableRequest,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Disable MFA after verifying current code or backup code."""
    result = await db.execute(select(Users).where(Users.id == user.id))
    db_user = result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='User not found')

    if not db_user.mfa_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='MFA is not enabled',
        )

    secret = _decrypt_secret(db_user.mfa_secret)

    # Verify TOTP code or backup code
    code_valid = _verify_totp(secret, form.code)

    if not code_valid:
        # Check backup codes
        backup_hashes = db_user.mfa_backup_codes or []
        code_hash = _hash_code(form.code)
        if code_hash in backup_hashes:
            code_valid = True
            # Remove used backup code
            backup_hashes.remove(code_hash)
            db_user.mfa_backup_codes = backup_hashes

    if not code_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Invalid verification code',
        )

    # Disable MFA
    db_user.mfa_enabled = 0
    db_user.mfa_secret = None
    db_user.mfa_backup_codes = None
    await db.commit()

    return {'success': True}


@router.post('/api/v1/auths/mfa/challenge')
async def mfa_challenge(
    request: Request,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Return MFA challenge requirement for login flow."""
    result = await db.execute(select(Users).where(Users.id == user.id))
    db_user = result.scalar_one_or_none()
    if not db_user or not db_user.mfa_enabled:
        return {'mfa_required': False}
    return {'mfa_required': True}

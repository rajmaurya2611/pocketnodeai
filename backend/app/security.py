import hashlib
import hmac
import secrets
from fastapi import Header, HTTPException, status
from sqlalchemy.orm import Session
from .config import get_settings
from .models import ApiKey, Device

def digest(value: str) -> str:
    return hmac.new(get_settings().key_pepper.encode(), value.encode(), hashlib.sha256).hexdigest()

def issue_credential(prefix: str):
    identifier = secrets.token_hex(12)
    token = f"{prefix}_{identifier}_{secrets.token_urlsafe(32)}"
    return identifier, token, digest(token)

def parse_credential(token: str, prefix: str) -> str | None:
    parts = token.split('_', 3)
    if len(parts) != 4 or parts[0] + '_' + parts[1] != prefix:
        return None
    return parts[2]

def require_admin(x_admin_key: str | None = Header(None)):
    if not x_admin_key or not secrets.compare_digest(x_admin_key, get_settings().admin_secret):
        raise HTTPException(status_code=401, detail="Invalid admin secret")

def check_device(db: Session, token: str | None) -> Device | None:
    if not token: return None
    identifier = parse_credential(token, 'pn_dev')
    device = db.get(Device, identifier) if identifier else None
    if not device or device.revoked_at: return None
    return device if hmac.compare_digest(device.credential_hash, digest(token)) else None

def check_api_key(db: Session, auth: str | None) -> ApiKey:
    token = auth.removeprefix('Bearer ').strip() if auth and auth.startswith('Bearer ') else ''
    identifier = parse_credential(token, 'pn_sk')
    key = db.get(ApiKey, identifier) if identifier else None
    if not key or key.revoked_at or key.device.revoked_at or not hmac.compare_digest(key.credential_hash, digest(token)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked API key")
    return key

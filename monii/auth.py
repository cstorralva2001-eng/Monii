"""Local credentials for desktop use; OIDC identities for public deployment."""
import hashlib
import hmac
import json
import re
import secrets
import time
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).isoformat()


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 600_000)
    return f"pbkdf2_sha256$600000${salt}${digest.hex()}"


def check_password(password, stored):
    try:
        scheme, iterations, salt, digest = stored.split("$")
        if scheme != "pbkdf2_sha256" or int(iterations) != 600_000:
            return False
        candidate = password_hash(password, salt).split("$")[-1]
        return hmac.compare_digest(candidate, digest)
    except (ValueError, AttributeError):
        return False


def register(db, name, email, password):
    name, email = name.strip(), email.strip().lower()
    if not name or len(name) > 80:
        raise ValueError("Escribe un nombre de entre 1 y 80 caracteres.")
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or len(email) > 254:
        raise ValueError("Escribe un correo válido.")
    if len(password) < 12 or len(password) > 128:
        raise ValueError("Usa una contraseña de entre 12 y 128 caracteres.")
    hashed = password_hash(password)
    with db.connect(write=True) as conn:
        row = conn.one("INSERT INTO users(email,name,password_hash,created_at) VALUES(?,?,?,?) ON CONFLICT(email) DO NOTHING RETURNING id", (email, name, hashed, now()))
        if not row:
            raise ValueError("No se pudo crear la cuenta con ese correo. Prueba iniciar sesión.")
        return {"id": row["id"], "name": name, "email": email}


def login(db, email, password):
    email = email.strip().lower()[:254]
    if len(password) > 128:
        return None
    stamp = int(time.time())
    with db.connect(write=True) as conn:
        conn.execute("INSERT INTO login_attempts(email,failures,locked_until) VALUES(?,0,0) ON CONFLICT(email) DO NOTHING", (email,))
        suffix = " FOR UPDATE" if db.postgres else ""
        attempt = conn.one("SELECT * FROM login_attempts WHERE email=?" + suffix, (email,))
        if attempt["locked_until"] > stamp:
            raise ValueError("Demasiados intentos. Espera 15 minutos antes de volver a intentar.")
        user = conn.one("SELECT * FROM users WHERE email=?", (email,))
        # Perform the same expensive derivation even when the address is unknown.
        stored = user["password_hash"] if user and user["password_hash"] else ""
        valid = check_password(password, stored) if stored else hmac.compare_digest(password_hash(password, "00" * 16), "invalid")
        if not valid:
            failures = 1 if attempt["locked_until"] else attempt["failures"] + 1
            until = stamp + 900 if failures >= 5 else 0
            conn.execute("UPDATE login_attempts SET failures=?,locked_until=? WHERE email=?", (failures, until, email))
            return None
        conn.execute("DELETE FROM login_attempts WHERE email=?", (email,))
        return {k: user[k] for k in ("id", "name", "email")}


def oidc_user(db, claims):
    issuer, subject = claims.get("iss"), claims.get("sub")
    if not issuer or not subject:
        raise ValueError("El proveedor debe devolver los identificadores iss y sub.")
    identity = json.dumps([issuer, subject], separators=(",", ":"))
    name = str(claims.get("name") or "Mi cuenta")[:80]
    with db.connect(write=True) as conn:
        conn.execute("INSERT INTO users(external_key,name,created_at) VALUES(?,?,?) ON CONFLICT(external_key) DO NOTHING", (identity, name, now()))
        return conn.one("SELECT id,name,email FROM users WHERE external_key=?", (identity,))

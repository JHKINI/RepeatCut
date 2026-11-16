"""로그인에 필요한 계산: 비밀번호 해시, 로그인 토큰. (DB는 건드리지 않는다. SQL은 repository.py에)

■ 비밀번호
  비밀번호 원문은 저장하지 않는다. 회원마다 다른 임의 값(salt)을 섞어 PBKDF2-SHA256으로 여러 번 해시한 결과만 저장한다.
  저장 형식: pbkdf2_sha256$반복횟수$salt$해시   (반복 횟수를 같이 적어 두면 나중에 횟수를 올려도 예전 회원이 로그인된다)

■ 로그인 토큰
  로그인하면 추측할 수 없는 임의 문자열(토큰)을 만들어 프론트에 준다.
  프론트는 요청마다 `Authorization: Bearer <토큰>` 헤더로 보낸다.
  DB(sessions)에는 토큰 원문이 아니라 SHA-256 해시만 저장한다. (DB가 유출돼도 토큰을 그대로 쓸 수 없게)

파이썬 기본 모듈만 쓰므로 추가 설치가 필요 없다.
"""
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta

from .rules import SESSION_DAYS

PBKDF2_ITERATIONS = 600_000  # OWASP 권장값(PBKDF2-HMAC-SHA256)
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_email(email):
    return bool(EMAIL_PATTERN.match(email))


def hash_password(password, iterations=PBKDF2_ITERATIONS):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${digest.hex()}"


def verify_password(password, stored):
    """입력한 비밀번호가 저장된 해시와 맞는지. 형식이 이상하면 False."""
    try:
        algorithm, iterations, salt, expected = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations))
    except (ValueError, AttributeError):
        return False
    # 문자열을 ==로 비교하면 걸리는 시간으로 값을 추측할 수 있어서, 항상 같은 시간이 걸리는 비교를 쓴다
    return hmac.compare_digest(digest.hex(), expected)


def new_token():
    return secrets.token_urlsafe(32)


def hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def session_expiry(now=None):
    """지금부터 SESSION_DAYS일 뒤 시각 (DB에 저장하는 문자열 형식)."""
    now = now or datetime.now()
    return (now + timedelta(days=SESSION_DAYS)).isoformat(timespec="seconds")

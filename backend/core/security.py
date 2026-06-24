"""
JWT 工具：生成 / 校验 token
"""
import os
from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError

JWT_SECRET    = os.getenv("JWT_SECRET", "change-me")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE    = int(os.getenv("JWT_EXPIRE_MINUTES", "480"))


def create_access_token(subject: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRE)
    payload = {"sub": subject, "role": role, "exp": expire}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """返回 payload dict，失败抛 JWTError"""
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])

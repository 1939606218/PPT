"""
认证路由：注册 / 登录 / 当前用户信息
"""
import ipaddress
import os
import uuid
import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status 
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from db.database import get_db
from db.models import User
from core.security import create_access_token
from core.deps import get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _verify(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except Exception:
        return False


# ── Pydantic 模型 ─────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: uuid.UUID
    username: str
    role: str
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ── 注册 ──────────────────────────────────────────────────────────────────────

@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    # 用户名唯一性检查
    dup = await db.execute(select(User).where(User.username == req.username))
    if dup.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="用户名已被注册")

    uid = uuid.uuid4()
    user = User(
        id=uid,
        username=req.username,
        email=f"{req.username}_{str(uid)[:8]}@placeholder.local",  # 占位，保持 unique 约束
        password_hash=_hash(req.password),
        role="user",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(str(user.id), user.role)
    return TokenOut(access_token=token, user=UserOut.model_validate(user))


# ── 登录（兼容 OAuth2PasswordRequestForm，方便 Swagger 调试） ─────────────────

@router.post("/login", response_model=TokenOut)
async def login(
    form: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.username == form.username))
    user = result.scalar_one_or_none()

    if not user or not _verify(form.password, user.password_hash):
        raise HTTPException(status_code=400, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用")

    token = create_access_token(str(user.id), user.role)
    return TokenOut(access_token=token, user=UserOut.model_validate(user))


# ── 当前用户信息 ───────────────────────────────────────────────────────────────

@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)):
    return UserOut.model_validate(current_user)


# ── 内网 IP 免密登录 ───────────────────────────────────────────────────────────

def _get_client_ip(request: Request) -> str:
    """优先读取反代注入的真实 IP，否则取直连地址。"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else ""


def _is_intranet(ip_str: str) -> bool:
    """判断 IP 是否属于 .env 中配置的 INTRANET_CIDRS 段。"""
    cidrs_raw = os.getenv("INTRANET_CIDRS", "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16")
    try:
        addr = ipaddress.ip_address(ip_str)
        for cidr in cidrs_raw.split(","):
            cidr = cidr.strip()
            if cidr and addr in ipaddress.ip_network(cidr, strict=False):
                return True
    except ValueError:
        pass
    return False


# 增加一个接收前端 Device ID 的请求模型
class DeviceLoginRequest(BaseModel):
    device_id: Optional[str] = None

# 增加一个包含 device_id 的返回模型
class DeviceTokenOut(TokenOut):
    device_id: str

@router.post("/ip-login", response_model=DeviceTokenOut)
async def ip_login(
    request: Request, 
    response: Response,          # 🌟 2. 新增 Response 依赖，用于写入 Cookie
    payload: DeviceLoginRequest, 
    db: AsyncSession = Depends(get_db)
):
    """
    内网 IP + 设备号（Cookie为主，LocalStorage为辅） 免密自动登录。
    """
    client_ip = _get_client_ip(request)
    if not _is_intranet(client_ip):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="非内网 IP，请手动登录")

    # 🌟 3. 核心逻辑：优先读 Cookie，如果没有再读前端传来的 Payload 备份
    device_id = request.cookies.get("device_id") or payload.device_id
    user = None

    if device_id:
        username = f"__device_{device_id}__"
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()

    if user is None:
        device_id = uuid.uuid4().hex  
        username = f"__device_{device_id}__"
        uid = uuid.uuid4()
        
        user = User(
            id=uid,
            username=username,
            email=f"{username}@intranet.local",
            password_hash=_hash(uuid.uuid4().hex), 
            role="user",
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="该设备账号已被禁用")

    token = create_access_token(str(user.id), user.role)

    # 🌟 4. 将 device_id 种入 HttpOnly Cookie (有效期10年)
    response.set_cookie(
        key="device_id",
        value=device_id,
        max_age=10 * 365 * 24 * 3600, # 10年（单位：秒）
        httponly=True,                # JS 不可读，防 XSS
        samesite="lax"                # 允许正常跨域携带
    )

    return DeviceTokenOut(
        access_token=token, 
        user=UserOut.model_validate(user),
        device_id=device_id  
    )
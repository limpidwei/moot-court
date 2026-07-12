"""
用户认证模块 - JWT + 密码哈希
"""

import os
import jwt
import bcrypt
from datetime import datetime, timedelta
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from .database import get_db
from .models.database import User

# P4 补充修正：auth.py 模块导入期即校验 JWT_SECRET_KEY，但 .env 由 config.py
# 的 dotenv 加载。若 main.py 先 import auth 后 import config，校验时 JWT_SECRET_KEY
# 仍为空。此处提前加载 .env，确保导入顺序无关。
try:
    from dotenv import load_dotenv
    _dotenv_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    load_dotenv(_dotenv_path)
except Exception:
    pass  # dotenv 不可用时回退到系统环境变量（Docker/k8s 场景）

# JWT 配置
# 注意：不再保留可用的默认密钥——未显式配置时启动即报错，杜绝用默认密钥上线。
_INSECURE_DEFAULT_KEY = "your-secret-key-change-in-production"
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRATION_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", "24"))


def _validate_jwt_secret() -> None:
    """启动期 fail-fast 校验：JWT_SECRET_KEY 必须显式设置、非占位默认值、且长度足够。

    用默认/空密钥上线会让任何人都能伪造合法 JWT（C2 风险），因此在导入期直接拒绝。
    """
    key = JWT_SECRET_KEY.strip()
    if not key:
        raise RuntimeError(
            "JWT_SECRET_KEY 未设置：请在 .env 中配置一个不少于 32 字符的强随机密钥后启动。"
        )
    if key == _INSECURE_DEFAULT_KEY:
        raise RuntimeError(
            "JWT_SECRET_KEY 仍为不安全的占位默认值，请改用强随机密钥后启动。"
        )
    if len(key) < 32:
        raise RuntimeError(
            f"JWT_SECRET_KEY 强度不足（{len(key)} 字符 < 32），请使用更长的强随机密钥。"
        )


# 导入期即校验，确保任何用到本模块的进程（含 uvicorn worker）都无法用弱密钥启动
_validate_jwt_secret()

# 安全配置
security = HTTPBearer()


def hash_password(password: str) -> str:
    """
    对密码进行 bcrypt 哈希

    Args:
        password: 明文密码

    Returns:
        哈希后的密码字符串
    """
    salt = bcrypt.gensalt(rounds=12)
    password_bytes = password.encode('utf-8')
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    验证密码是否正确

    Args:
        plain_password: 明文密码
        hashed_password: 哈希后的密码

    Returns:
        True 如果密码匹配，否则 False
    """
    password_bytes = plain_password.encode('utf-8')
    hashed_bytes = hashed_password.encode('utf-8')
    return bcrypt.checkpw(password_bytes, hashed_bytes)


def create_access_token(user_id: int, email: str) -> str:
    """
    创建 JWT 访问令牌

    Args:
        user_id: 用户 ID
        email: 用户邮箱

    Returns:
        JWT 令牌字符串
    """
    expiration = datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS)

    payload = {
        "sub": str(user_id),
        "email": email,
        "exp": expiration,
        "iat": datetime.utcnow()
    }

    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return token


def decode_access_token(token: str) -> Optional[dict]:
    """
    解码 JWT 令牌

    Args:
        token: JWT 令牌字符串

    Returns:
        解码后的 payload 字典，如果无效则返回 None
    """
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        # Token 已过期
        return None
    except (jwt.PyJWTError, jwt.exceptions.DecodeError, jwt.exceptions.InvalidTokenError):
        # Token 无效或格式错误
        return None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """
    FastAPI 依赖：获取当前登录用户

    Args:
        credentials: HTTP Bearer 认证凭据
        db: 数据库会话

    Returns:
        当前用户对象

    Raises:
        HTTPException: 如果认证失败
    """
    token = credentials.credentials

    # 解码 token
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证令牌或令牌已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 从 payload 获取用户 ID
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的令牌内容",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 从数据库查询用户
    # P4 修复：int(user_id) 对非数字 sub（如篡改 JWT）抛 ValueError → 500。
    # 改为显式校验 + 401，与令牌过期/签名无效保持一致的认证失败语义。
    try:
        numeric_id = int(user_id)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的令牌内容",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = db.query(User).filter(User.id == numeric_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False)),
    db: Session = Depends(get_db)
) -> Optional[User]:
    """
    FastAPI 依赖：获取当前用户（可选）

    用于过渡期，允许未登录用户访问某些端点

    Args:
        credentials: HTTP Bearer 认证凭据（可选）
        db: 数据库会话

    Returns:
        当前用户对象，如果未登录则返回 None
    """
    if credentials is None:
        return None

    try:
        return await get_current_user(credentials, db)
    except HTTPException:
        return None

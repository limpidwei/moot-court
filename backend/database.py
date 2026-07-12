"""
数据库连接配置

提供：
- 数据库连接字符串配置
- SQLAlchemy session 管理
- 数据库初始化和表创建
"""

import os
from typing import Generator
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool, StaticPool
from pydantic_settings import BaseSettings

from backend.models.database import Base


class DatabaseSettings(BaseSettings):
    """数据库配置 - 从环境变量读取"""

    # PostgreSQL 连接配置
    DATABASE_URL: str = "postgresql://postgres:mootcourt2026@localhost:5432/moot_court"

    # 连接池配置
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800  # 30分钟回收连接

    # Redis 配置
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT 认证配置
    JWT_SECRET_KEY: str = "your-secret-key-change-this-in-production-abc123xyz789"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_HOURS: int = 24

    model_config = {"env_file": ".env", "case_sensitive": True, "extra": "ignore"}


# 全局配置实例
db_settings = DatabaseSettings()


# 创建数据库引擎（SQLite 内存模式用 StaticPool 保证多连接共享同一数据库）
if db_settings.DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        db_settings.DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
else:
    engine = create_engine(
        db_settings.DATABASE_URL,
        poolclass=QueuePool,
        pool_size=db_settings.DB_POOL_SIZE,
        max_overflow=db_settings.DB_MAX_OVERFLOW,
        pool_timeout=db_settings.DB_POOL_TIMEOUT,
        pool_recycle=db_settings.DB_POOL_RECYCLE,
        echo=False,
    )


# 创建 session 工厂
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)


def get_db() -> Generator[Session, None, None]:
    """
    获取数据库 session 的依赖注入函数
    用于 FastAPI 的 Depends()
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """
    初始化数据库 - 创建所有表
    注意：生产环境应该使用 Alembic 进行数据库迁移
    """
    try:
        print("[INFO] 正在创建数据库表...")
        Base.metadata.create_all(bind=engine)
        print("[SUCCESS] 数据库表创建完成")
    except Exception as e:
        print(f"[WARNING] 数据库表创建失败（服务仍可启动）: {e}")


def check_db_connection() -> bool:
    """检查数据库连接是否正常"""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        print(f"数据库连接失败: {e}")
        return False


# 应用启动时检查连接
if __name__ == "__main__":
    print(f"数据库 URL: {db_settings.DATABASE_URL}")
    print(f"Redis URL: {db_settings.REDIS_URL}")

    if check_db_connection():
        print("[SUCCESS] 数据库连接成功")
        init_db()
    else:
        print("[ERROR] 数据库连接失败，请检查配置")

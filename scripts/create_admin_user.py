"""创建初始管理员用户。

用法：python scripts/create_admin_user.py admin@camthink.ai --name "Admin" --role admin
交互式输入密码，bcrypt 哈希后写入 users 表。
"""

import argparse
import asyncio
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from passlib.context import CryptContext
from sqlalchemy import select

from backend.config import load_settings
from backend.db.models import User
from backend.db.session import get_engine, get_session_factory, init_db

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def create_admin(email: str, name: str, role: str) -> None:
    password = getpass.getpass("密码: ")
    password_hash = pwd_context.hash(password)
    settings = load_settings()
    engine = get_engine(settings.postgres_dsn)
    await init_db(engine)
    factory = get_session_factory(engine)
    async with factory() as session:
        existing = await session.execute(select(User).where(User.email == email))
        if existing.scalar_one_or_none():
            print(f"用户 {email} 已存在")
            return
        user = User(email=email, name=name, role=role, password_hash=password_hash)
        session.add(user)
        await session.commit()
        print(f"管理员 {email} 创建成功")
    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="创建管理员用户")
    parser.add_argument("email")
    parser.add_argument("--name", default="Admin")
    parser.add_argument("--role", default="admin", choices=["admin", "editor", "viewer"])
    args = parser.parse_args()
    asyncio.run(create_admin(args.email, args.name, args.role))


if __name__ == "__main__":
    main()

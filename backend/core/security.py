import asyncio

from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


async def hash_password_async(password: str) -> str:
    """Run CPU-intensive bcrypt password hashing off the event loop."""
    return await asyncio.to_thread(pwd_context.hash, password)


async def verify_password_async(plain_password: str, hashed_password: str) -> bool:
    """Run CPU-intensive bcrypt password verification off the event loop."""
    return await asyncio.to_thread(pwd_context.verify, plain_password, hashed_password)


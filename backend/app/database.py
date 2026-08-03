import uuid

from cryptography.fernet import Fernet
from sqlalchemy import Uuid, event, types
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from config import settings


class GUID(types.TypeDecorator):
    """UUID column that also accepts string values when binding.

    SQLite's non-native UUID storage expects a real ``uuid.UUID`` and raises
    otherwise, but session tokens and path params arrive as strings — coerce
    here so queries like ``User.id == "…"`` work without callers thinking
    about it.
    """
    impl = Uuid
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None or isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))


class EncryptedString(types.TypeDecorator):
    """Fernet-encrypted text column, for mail account credentials at rest.

    Encryption/decryption happens transparently at the SQLAlchemy boundary so
    callers just read/write plain strings; only the DB row is ciphertext.
    """
    impl = types.Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return Fernet(settings.mail_encryption_key).encrypt(value.encode()).decode()

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return Fernet(settings.mail_encryption_key).decrypt(value.encode()).decode()


engine = create_async_engine(settings.database_url, echo=settings.debug)

# SQLite needs a couple of pragmas set on every new connection:
#   - foreign_keys=ON so FK constraints are actually enforced (off by default)
#   - busy_timeout so concurrent writers (app + host tools) wait instead of erroring
if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    type_annotation_map = {uuid.UUID: GUID}


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

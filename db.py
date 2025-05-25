from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, delete
from config import Config
from models import Inbound, Server, Base
import logging
import asyncio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Создание движков с улучшенным пулом соединений
local_engine = create_async_engine(
    f"postgresql+asyncpg://{Config.LOCAL_DB['user']}:{Config.LOCAL_DB['password']}@"
    f"{Config.LOCAL_DB['host']}:{Config.LOCAL_DB['port']}/{Config.LOCAL_DB['dbname']}",
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_pre_ping=True
)

remote_engine = create_async_engine(
    f"postgresql+asyncpg://{Config.REMOTE_DB['user']}:{Config.REMOTE_DB['password']}@"
    f"{Config.REMOTE_DB['host']}:{Config.REMOTE_DB['port']}/{Config.REMOTE_DB['dbname']}",
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_pre_ping=True,
    connect_args={"timeout": 60}
)

# Создание сессий
LocalSession = sessionmaker(local_engine, class_=AsyncSession, expire_on_commit=False)
RemoteSession = sessionmaker(remote_engine, class_=AsyncSession, expire_on_commit=False)

async def init_db():
    """Инициализация локальной базы: создание таблицы servers, если она не существует."""
    async with local_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Local database initialized")

async def get_remote_inbounds(max_retries=3, retry_delay=2):
    """Получение списка инбаундов из public.inbounds.tag в удаленной базе с повторными попытками."""
    for attempt in range(max_retries):
        async with RemoteSession() as session:
            try:
                result = await session.execute(select(Inbound.tag))
                inbounds = [row[0] for row in result.fetchall()]
                logger.info(f"Fetched {len(inbounds)} inbounds on attempt {attempt + 1}")
                return inbounds
            except Exception as e:
                logger.error(f"Error fetching inbounds on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                else:
                    logger.error("Max retries reached for fetching inbounds")
                    return []

async def add_server(ip: str, inbound: str):
    """Добавление сервера в локальную базу."""
    async with LocalSession() as session:
        try:
            server = Server(ip=ip, inbound=inbound)
            session.add(server)
            await session.commit()
            logger.info(f"Server {ip} added with inbound {inbound}")
            return True
        except Exception as e:
            logger.error(f"Error adding server {ip}: {e}")
            await session.rollback()
            return False

async def get_servers():
    """Получение списка серверов из локальной базы."""
    async with LocalSession() as session:
        try:
            result = await session.execute(select(Server.ip, Server.inbound, Server.install_date))
            servers = result.fetchall()
            logger.info(f"Fetched {len(servers)} servers")
            return servers
        except Exception as e:
            logger.error(f"Error fetching servers: {e}")
            return []

async def delete_server(ip: str):
    """Удаление сервера из локальной базы."""
    async with LocalSession() as session:
        try:
            result = await session.execute(delete(Server).where(Server.ip == ip))
            await session.commit()
            logger.info(f"Server {ip} deleted, rows affected: {result.rowcount}")
            return result.rowcount > 0
        except Exception as e:
            logger.error(f"Error deleting server {ip}: {e}")
            await session.rollback()
            return False
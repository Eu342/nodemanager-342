import asyncpg
import logging
import os
from dotenv import load_dotenv
load_dotenv()
logger = logging.getLogger(__name__)
DB_DBNAME = os.getenv('LOCAL_DB_DBNAME')
DB_USER = os.getenv('LOCAL_DB_USER')
DB_PASSWORD = os.getenv('LOCAL_DB_PASSWORD')
DB_HOST = os.getenv('LOCAL_DB_HOST', 'localhost')
DB_PORT = os.getenv('LOCAL_DB_PORT', '5432')
async def init_db():
    try:
        conn = await asyncpg.connect(
            database=DB_DBNAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS vless_keys (
                inbound_tag TEXT PRIMARY KEY,
                serverName TEXT NOT NULL,
                vless_key TEXT NOT NULL
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS servers (
                ip TEXT PRIMARY KEY,
                inbound_tag TEXT NOT NULL,
                install_date TIMESTAMP
            )
        ''')
        await conn.execute('DROP TABLE IF EXISTS inbounds')
        logger.info("Database initialized successfully")
        await conn.close()
    except Exception as e:
        logger.error(f"Failed to initialize database: {str(e)}")
        raise
async def get_vless_keys():
    try:
        conn = await asyncpg.connect(
            database=DB_DBNAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        rows = await conn.fetch("SELECT inbound_tag, serverName, vless_key FROM vless_keys")
        await conn.close()
        return [{"inbound_tag": row['inbound_tag'], "serverName": row['servername'], "vless_key": row['vless_key']} for row in rows]
    except Exception as e:
        logger.error(f"Failed to fetch vless keys: {str(e)}")
        return []
async def get_vless_key(inbound_tag):
    try:
        conn = await asyncpg.connect(
            database=DB_DBNAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        row = await conn.fetchrow("SELECT inbound_tag, serverName, vless_key FROM vless_keys WHERE inbound_tag = $1", inbound_tag)
        await conn.close()
        if row:
            return {"inbound_tag": row['inbound_tag'], "serverName": row['servername'], "vless_key": row['vless_key']}
        return None
    except Exception as e:
        logger.error(f"Failed to fetch vless key {inbound_tag}: {str(e)}")
        return None
async def update_vless_key(inbound_tag, serverName, vless_key):
    try:
        conn = await asyncpg.connect(
            database=DB_DBNAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        await conn.execute(
            """
            INSERT INTO vless_keys (inbound_tag, serverName, vless_key)
            VALUES ($1, $2, $3)
            ON CONFLICT (inbound_tag)
            DO UPDATE SET vless_key = $3
            """,
            inbound_tag, serverName, vless_key
        )
        await conn.close()
    except Exception as e:
        logger.error(f"Failed to update vless key {inbound_tag}: {str(e)}")
        raise
async def add_server(ip, inbound_tag):
    try:
        conn = await asyncpg.connect(
            database=DB_DBNAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        await conn.execute(
            """
            INSERT INTO servers (ip, inbound_tag, install_date)
            VALUES ($1, $2, CURRENT_TIMESTAMP)
            ON CONFLICT (ip) DO NOTHING
            """,
            ip, inbound_tag
        )
        await conn.close()
        return True
    except Exception as e:
        logger.error(f"Failed to add server {ip}: {str(e)}")
        return False
async def get_servers():
    try:
        conn = await asyncpg.connect(
            database=DB_DBNAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        rows = await conn.fetch("SELECT ip, inbound_tag, install_date FROM servers")
        await conn.close()
        return [(row['ip'], row['inbound_tag'], row['install_date']) for row in rows]
    except Exception as e:
        logger.error(f"Failed to fetch servers: {str(e)}")
        return []
async def delete_server(ip):
    try:
        conn = await asyncpg.connect(
            database=DB_DBNAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        result = await conn.execute("DELETE FROM servers WHERE ip = $1", ip)
        await conn.close()
        return result != 'DELETE 0'
    except Exception as e:
        logger.error(f"Failed to delete server {ip}: {str(e)}")
        return False
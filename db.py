import asyncpg
import logging
import os
import traceback
from dotenv import load_dotenv
from datetime import datetime
from typing import List, Tuple, Optional, Dict, Any

load_dotenv()
logger = logging.getLogger(__name__)

DB_DBNAME = os.getenv('LOCAL_DB_DBNAME')
DB_USER = os.getenv('LOCAL_DB_USER')
DB_PASSWORD = os.getenv('LOCAL_DB_PASSWORD')
DB_HOST = os.getenv('LOCAL_DB_HOST', 'localhost')
DB_PORT = os.getenv('LOCAL_DB_PORT', '5432')

# Connection pool for better performance
_db_pool = None

async def get_db_pool():
    """Get or create database connection pool"""
    global _db_pool
    if _db_pool is None:
        _db_pool = await asyncpg.create_pool(
            database=DB_DBNAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT,
            min_size=1,
            max_size=10,
            command_timeout=60
        )
    return _db_pool

async def close_db_pool():
    """Close database connection pool"""
    global _db_pool
    if _db_pool:
        await _db_pool.close()
        _db_pool = None

async def init_db():
    """Initialize database schema"""
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            # Create tables with proper constraints
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS servers (
                    ip TEXT PRIMARY KEY CHECK (ip ~ '^[0-9]{1,3}\\.[0-9]{1,3}\\.[0-9]{1,3}\\.[0-9]{1,3}$'),
                    inbound_tag TEXT NOT NULL CHECK (length(inbound_tag) <= 100),
                    install_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS server_events (
                    id SERIAL PRIMARY KEY,
                    server_ip TEXT REFERENCES servers(ip) ON DELETE CASCADE,
                    event_type TEXT NOT NULL CHECK (event_type IN ('online', 'offline_start', 'offline_end')),
                    event_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    duration_seconds INTEGER CHECK (duration_seconds >= 0 OR duration_seconds IS NULL),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS vless_keys (
                    inbound_tag TEXT PRIMARY KEY CHECK (length(inbound_tag) <= 100),
                    serverName TEXT NOT NULL CHECK (length(serverName) <= 255),
                    vless_key TEXT NOT NULL CHECK (length(vless_key) <= 1000),
                    domain TEXT NOT NULL CHECK (length(domain) <= 255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create indexes for better performance
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_server_events_time ON server_events(event_time DESC)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_server_events_ip ON server_events(server_ip)')
            
            # Add update trigger for updated_at
            await conn.execute('''
                CREATE OR REPLACE FUNCTION update_updated_at_column()
                RETURNS TRIGGER AS $$
                BEGIN
                    NEW.updated_at = CURRENT_TIMESTAMP;
                    RETURN NEW;
                END;
                $$ language 'plpgsql';
            ''')
            
            for table in ['servers', 'vless_keys']:
                await conn.execute(f'''
                    CREATE TRIGGER update_{table}_updated_at BEFORE UPDATE ON {table}
                    FOR EACH ROW EXECUTE PROCEDURE update_updated_at_column();
                ''')
            
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {str(e)}\n{traceback.format_exc()}")
        raise

async def get_vless_keys() -> List[Dict[str, Any]]:
    """Get all VLESS keys"""
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT inbound_tag, serverName, vless_key, domain FROM vless_keys ORDER BY inbound_tag"
            )
            return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Failed to fetch vless keys: {str(e)}\n{traceback.format_exc()}")
        return []

async def get_vless_key(inbound_tag: str) -> Optional[Dict[str, Any]]:
    """Get specific VLESS key by inbound tag"""
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT inbound_tag, serverName, vless_key, domain FROM vless_keys WHERE inbound_tag = $1",
                inbound_tag
            )
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"Failed to fetch vless key {inbound_tag}: {str(e)}\n{traceback.format_exc()}")
        return None

async def update_vless_key(inbound_tag: str, serverName: str, vless_key: str, domain: str) -> bool:
    """Update or insert VLESS key"""
    try:
        # Validate inputs
        if not all([inbound_tag, serverName, vless_key, domain]):
            raise ValueError("All parameters are required")
        
        if len(inbound_tag) > 100 or len(serverName) > 255 or len(vless_key) > 1000 or len(domain) > 255:
            raise ValueError("Parameter length exceeds limit")
        
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO vless_keys (inbound_tag, serverName, vless_key, domain)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (inbound_tag)
                DO UPDATE SET serverName = $2, vless_key = $3, domain = $4
                """,
                inbound_tag, serverName, vless_key, domain
            )
        return True
    except Exception as e:
        logger.error(f"Failed to update vless key {inbound_tag}: {str(e)}\n{traceback.format_exc()}")
        raise

async def add_server(ip: str, inbound_tag: str) -> bool:
    """Add or update server"""
    try:
        # Validate IP address
        import ipaddress
        ipaddress.ip_address(ip)  # This will raise ValueError if invalid
        
        # Validate inbound_tag
        if not inbound_tag or len(inbound_tag) > 100:
            raise ValueError("Invalid inbound_tag")
        
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                INSERT INTO servers (ip, inbound_tag, install_date)
                VALUES ($1, $2, CURRENT_TIMESTAMP)
                ON CONFLICT (ip) DO UPDATE
                SET inbound_tag = $2, install_date = CURRENT_TIMESTAMP
                """,
                ip, inbound_tag
            )
            return result.startswith('INSERT') or result.startswith('UPDATE')
    except Exception as e:
        logger.error(f"Failed to add server {ip}: {str(e)}\n{traceback.format_exc()}")
        return False

async def get_servers() -> List[Tuple[str, str, Optional[datetime]]]:
    """Get all servers"""
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT ip, inbound_tag, install_date FROM servers ORDER BY install_date DESC"
            )
            return [(row['ip'], row['inbound_tag'], row['install_date']) for row in rows]
    except Exception as e:
        logger.error(f"Failed to fetch servers: {str(e)}\n{traceback.format_exc()}")
        return []

async def delete_server(ip: str) -> bool:
    """Delete server by IP"""
    try:
        # Validate IP
        import ipaddress
        ipaddress.ip_address(ip)
        
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            result = await conn.execute("DELETE FROM servers WHERE ip = $1", ip)
            return result != 'DELETE 0'
    except Exception as e:
        logger.error(f"Failed to delete server {ip}: {str(e)}\n{traceback.format_exc()}")
        return False

async def log_server_event(server_ip: str, event_type: str, duration_seconds: Optional[int] = None) -> bool:
    """Log server event"""
    try:
        # Validate inputs
        import ipaddress
        ipaddress.ip_address(server_ip)
        
        if event_type not in ['online', 'offline_start', 'offline_end']:
            raise ValueError(f"Invalid event_type: {event_type}")
        
        if duration_seconds is not None and duration_seconds < 0:
            raise ValueError("duration_seconds must be non-negative")
        
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO server_events (server_ip, event_type, duration_seconds)
                VALUES ($1, $2, $3)
                """,
                server_ip, event_type, duration_seconds
            )
        return True
    except Exception as e:
        logger.error(f"Error logging event for {server_ip}: {str(e)}\n{traceback.format_exc()}")
        return False

async def get_server_events(period_hours: int, server_ip: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """Get server events within specified period"""
    try:
        # Validate inputs
        if period_hours <= 0 or period_hours > 8760:  # Max 1 year
            raise ValueError("Invalid period_hours")
        
        if limit <= 0 or limit > 1000:
            raise ValueError("Invalid limit")
        
        if server_ip:
            import ipaddress
            ipaddress.ip_address(server_ip)
        
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            if server_ip is None:
                query = '''
                    SELECT id, server_ip, event_type, event_time, duration_seconds
                    FROM server_events
                    WHERE event_time >= NOW() - INTERVAL '1 hour' * $1
                    ORDER BY event_time DESC 
                    LIMIT $2
                '''
                rows = await conn.fetch(query, period_hours, limit)
            else:
                query = '''
                    SELECT id, server_ip, event_type, event_time, duration_seconds
                    FROM server_events
                    WHERE event_time >= NOW() - INTERVAL '1 hour' * $1
                    AND server_ip = $2
                    ORDER BY event_time DESC 
                    LIMIT $3
                '''
                rows = await conn.fetch(query, period_hours, server_ip, limit)
            
            return [{
                'id': row['id'],
                'server_ip': row['server_ip'],
                'event_type': row['event_type'],
                'event_time': row['event_time'].isoformat(),
                'duration_seconds': row['duration_seconds']
            } for row in rows]
    except Exception as e:
        logger.error(f"Error fetching server events: {str(e)}\n{traceback.format_exc()}")
        return []

# Add cleanup function for graceful shutdown
async def cleanup():
    """Cleanup database connections"""
    await close_db_pool()
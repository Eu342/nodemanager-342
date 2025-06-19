import asyncpg
import os
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from dotenv import load_dotenv
import traceback

load_dotenv()

logger = logging.getLogger(__name__)

# Database configuration
DATABASE_URL = os.getenv('DATABASE_URL')
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = int(os.getenv('DB_PORT', 5432))
DB_NAME = os.getenv('DB_NAME', 'nodemanager')
DB_USER = os.getenv('DB_USER', 'postgres')
DB_PASSWORD = os.getenv('DB_PASSWORD', '')

# Global pool
_db_pool = None

async def get_db_pool():
    """Get or create database connection pool"""
    global _db_pool
    if _db_pool is None:
        try:
            if DATABASE_URL:
                _db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=5, max_size=20)
            else:
                _db_pool = await asyncpg.create_pool(
                    host=DB_HOST,
                    port=DB_PORT,
                    database=DB_NAME,
                    user=DB_USER,
                    password=DB_PASSWORD,
                    min_size=5,
                    max_size=20
                )
            logger.info("Database pool created successfully")
        except Exception as e:
            logger.error(f"Failed to create database pool: {str(e)}")
            raise
    return _db_pool

async def init_db():
    """Initialize database tables with proper migration support"""
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            logger.info("Starting database initialization...")
            
            # Create vless_keys table
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS vless_keys (
                    id SERIAL PRIMARY KEY,
                    inbound_tag VARCHAR(255) UNIQUE NOT NULL,
                    serverName VARCHAR(255) NOT NULL,
                    vless_key VARCHAR(255) NOT NULL,
                    domain VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            logger.info("vless_keys table ready")
            
            # Check if servers table exists
            table_exists = await conn.fetchval('''
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = 'servers'
                )
            ''')
            
            if table_exists:
                logger.info("servers table exists, checking structure...")
                
                # Get existing columns
                existing_columns = await conn.fetch('''
                    SELECT column_name, data_type, column_default
                    FROM information_schema.columns
                    WHERE table_schema = 'public' 
                    AND table_name = 'servers'
                ''')
                
                column_names = {row['column_name'] for row in existing_columns}
                logger.info(f"Existing columns in servers table: {column_names}")
                
                # Add missing columns
                if 'inbound_tag' not in column_names:
                    logger.info("Adding inbound_tag column to servers table")
                    await conn.execute('''
                        ALTER TABLE servers 
                        ADD COLUMN inbound_tag VARCHAR(255) NOT NULL DEFAULT 'default'
                    ''')
                
                if 'install_date' not in column_names:
                    logger.info("Adding install_date column to servers table")
                    await conn.execute('''
                        ALTER TABLE servers 
                        ADD COLUMN install_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    ''')
                
                if 'updated_at' not in column_names:
                    logger.info("Adding updated_at column to servers table")
                    await conn.execute('''
                        ALTER TABLE servers 
                        ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    ''')
                
                logger.info("servers table structure updated")
            else:
                # Create new servers table
                logger.info("Creating servers table")
                await conn.execute('''
                    CREATE TABLE servers (
                        ip VARCHAR(45) PRIMARY KEY,
                        inbound_tag VARCHAR(255) NOT NULL,
                        install_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                logger.info("servers table created")
            
            # Create server_events table
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS server_events (
                    id SERIAL PRIMARY KEY,
                    server_ip VARCHAR(45) NOT NULL,
                    event_type VARCHAR(50) NOT NULL,
                    event_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    duration_seconds INTEGER,
                    details TEXT
                )
            ''')
            logger.info("server_events table ready")
            
            # Create indexes
            try:
                await conn.execute('CREATE INDEX IF NOT EXISTS idx_servers_inbound_tag ON servers(inbound_tag)')
                await conn.execute('CREATE INDEX IF NOT EXISTS idx_server_events_server_ip ON server_events(server_ip)')
                await conn.execute('CREATE INDEX IF NOT EXISTS idx_server_events_event_time ON server_events(event_time)')
                logger.info("Indexes created")
            except Exception as e:
                logger.warning(f"Index creation warning: {e}")
            
            # Create update function
            await conn.execute('''
                CREATE OR REPLACE FUNCTION update_updated_at_column()
                RETURNS TRIGGER AS $$
                BEGIN
                    NEW.updated_at = CURRENT_TIMESTAMP;
                    RETURN NEW;
                END;
                $$ language 'plpgsql';
            ''')
            
            # Create triggers if they don't exist
            trigger_exists = await conn.fetchval('''
                SELECT EXISTS (
                    SELECT 1 FROM pg_trigger 
                    WHERE tgname = 'update_servers_updated_at'
                )
            ''')
            
            if not trigger_exists:
                try:
                    await conn.execute('''
                        CREATE TRIGGER update_servers_updated_at 
                        BEFORE UPDATE ON servers 
                        FOR EACH ROW 
                        EXECUTE PROCEDURE update_updated_at_column()
                    ''')
                    logger.info("Created trigger update_servers_updated_at")
                except Exception as e:
                    logger.warning(f"Trigger creation warning: {e}")
            
            vless_trigger_exists = await conn.fetchval('''
                SELECT EXISTS (
                    SELECT 1 FROM pg_trigger 
                    WHERE tgname = 'update_vless_keys_updated_at'
                )
            ''')
            
            if not vless_trigger_exists:
                try:
                    await conn.execute('''
                        CREATE TRIGGER update_vless_keys_updated_at 
                        BEFORE UPDATE ON vless_keys 
                        FOR EACH ROW 
                        EXECUTE PROCEDURE update_updated_at_column()
                    ''')
                    logger.info("Created trigger update_vless_keys_updated_at")
                except Exception as e:
                    logger.warning(f"Trigger creation warning: {e}")
            
            # Try to add foreign keys (optional, won't fail if can't)
            try:
                # Check if foreign key exists
                fk_exists = await conn.fetchval('''
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.table_constraints 
                        WHERE constraint_type = 'FOREIGN KEY' 
                        AND table_name = 'servers'
                        AND constraint_name = 'servers_inbound_tag_fkey'
                    )
                ''')
                
                if not fk_exists:
                    # Check if we have any data that would violate the constraint
                    orphaned_servers = await conn.fetchval('''
                        SELECT COUNT(*) FROM servers s
                        WHERE NOT EXISTS (
                            SELECT 1 FROM vless_keys v 
                            WHERE v.inbound_tag = s.inbound_tag
                        )
                    ''')
                    
                    if orphaned_servers > 0:
                        logger.warning(f"Found {orphaned_servers} servers with non-existent inbound_tags")
                        # Insert default vless_key for orphaned servers
                        await conn.execute('''
                            INSERT INTO vless_keys (inbound_tag, serverName, vless_key, domain)
                            SELECT DISTINCT s.inbound_tag, 'Auto-created for ' || s.inbound_tag, 'placeholder', 'example.com'
                            FROM servers s
                            WHERE NOT EXISTS (
                                SELECT 1 FROM vless_keys v 
                                WHERE v.inbound_tag = s.inbound_tag
                            )
                        ''')
                        logger.info("Created placeholder vless_keys for orphaned servers")
                    
                    await conn.execute('''
                        ALTER TABLE servers 
                        ADD CONSTRAINT servers_inbound_tag_fkey 
                        FOREIGN KEY (inbound_tag) REFERENCES vless_keys(inbound_tag) ON UPDATE CASCADE
                    ''')
                    logger.info("Added foreign key constraint to servers table")
            except Exception as e:
                logger.warning(f"Could not add foreign key: {e}")
            
            # Similar for server_events foreign key
            try:
                fk_events_exists = await conn.fetchval('''
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.table_constraints 
                        WHERE constraint_type = 'FOREIGN KEY' 
                        AND table_name = 'server_events'
                        AND constraint_name = 'server_events_server_ip_fkey'
                    )
                ''')
                
                if not fk_events_exists:
                    # Clean up orphaned events
                    deleted = await conn.fetchval('''
                        DELETE FROM server_events e
                        WHERE NOT EXISTS (
                            SELECT 1 FROM servers s 
                            WHERE s.ip = e.server_ip
                        )
                        RETURNING COUNT(*)
                    ''')
                    
                    if deleted and deleted > 0:
                        logger.info(f"Cleaned up {deleted} orphaned server events")
                    
                    await conn.execute('''
                        ALTER TABLE server_events 
                        ADD CONSTRAINT server_events_server_ip_fkey 
                        FOREIGN KEY (server_ip) REFERENCES servers(ip) ON DELETE CASCADE
                    ''')
                    logger.info("Added foreign key constraint to server_events table")
            except Exception as e:
                logger.warning(f"Could not add foreign key to server_events: {e}")
            
            logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {str(e)}\n{traceback.format_exc()}")
        raise

async def get_vless_keys() -> List[Dict[str, Any]]:
    """Get all VLESS keys"""
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT inbound_tag, serverName, vless_key, domain 
                FROM vless_keys 
                ORDER BY inbound_tag
            ''')
            return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Failed to fetch vless keys: {str(e)}")
        return []

async def get_vless_key(inbound_tag: str) -> Optional[Dict[str, Any]]:
    """Get VLESS key by inbound tag"""
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow('''
                SELECT inbound_tag, serverName, vless_key, domain 
                FROM vless_keys 
                WHERE inbound_tag = $1
            ''', inbound_tag)
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"Failed to fetch vless key for {inbound_tag}: {str(e)}")
        return None

async def update_vless_key(inbound_tag: str, serverName: str, vless_key: str, domain: str) -> bool:
    """Update or insert VLESS key"""
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO vless_keys (inbound_tag, serverName, vless_key, domain)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (inbound_tag) DO UPDATE
                SET serverName = $2, vless_key = $3, domain = $4, updated_at = CURRENT_TIMESTAMP
            ''', inbound_tag, serverName, vless_key, domain)
        logger.info(f"Updated vless key for {inbound_tag}")
        return True
    except Exception as e:
        logger.error(f"Failed to update vless key for {inbound_tag}: {str(e)}")
        return False

async def add_server(ip: str, inbound_tag: str) -> bool:
    """Add server to database"""
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO servers (ip, inbound_tag)
                VALUES ($1, $2)
                ON CONFLICT (ip) DO UPDATE
                SET inbound_tag = $2, updated_at = CURRENT_TIMESTAMP
            ''', ip, inbound_tag)
        logger.info(f"Added/updated server {ip} with inbound_tag {inbound_tag}")
        return True
    except Exception as e:
        logger.error(f"Failed to add server {ip}: {str(e)}")
        return False

async def get_servers() -> List[tuple]:
    """Get all servers"""
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            # Ensure columns exist first
            columns = await conn.fetch('''
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_schema = 'public' 
                AND table_name = 'servers'
            ''')
            
            column_names = {row['column_name'] for row in columns}
            
            # Build query based on available columns
            select_parts = ['ip']
            if 'inbound_tag' in column_names:
                select_parts.append('inbound_tag')
            else:
                select_parts.append("'default' as inbound_tag")
            
            if 'install_date' in column_names:
                select_parts.append('install_date')
            else:
                select_parts.append('CURRENT_TIMESTAMP as install_date')
            
            query = f"SELECT {', '.join(select_parts)} FROM servers ORDER BY install_date DESC"
            
            rows = await conn.fetch(query)
            return [(row['ip'], row['inbound_tag'], row['install_date']) for row in rows]
    except Exception as e:
        logger.error(f"Failed to fetch servers: {str(e)}")
        return []

async def delete_server(ip: str) -> bool:
    """Delete server from database"""
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            result = await conn.execute('DELETE FROM servers WHERE ip = $1', ip)
            if result == 'DELETE 0':
                logger.warning(f"Server {ip} not found")
                return False
        logger.info(f"Deleted server {ip}")
        return True
    except Exception as e:
        logger.error(f"Failed to delete server {ip}: {str(e)}")
        return False

async def log_server_event(server_ip: str, event_type: str, duration_seconds: int = None, details: str = None) -> bool:
    """Log server event"""
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO server_events (server_ip, event_type, duration_seconds, details)
                VALUES ($1, $2, $3, $4)
            ''', server_ip, event_type, duration_seconds, details)
        logger.debug(f"Logged event for {server_ip}: {event_type}")
        return True
    except Exception as e:
        logger.error(f"Failed to log event for {server_ip}: {str(e)}")
        return False

async def get_server_events(hours: int = 24, server_ip: str = None, limit: int = 100) -> List[Dict[str, Any]]:
    """Get server events within specified hours"""
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            since = datetime.utcnow() - timedelta(hours=hours)
            query = '''
                SELECT id, server_ip, event_type, event_time, duration_seconds, details
                FROM server_events
                WHERE event_time >= $1
            '''
            params = [since]
            
            if server_ip:
                query += ' AND server_ip = $2'
                params.append(server_ip)
            
            query += ' ORDER BY event_time DESC LIMIT $' + str(len(params) + 1)
            params.append(limit)
            
            rows = await conn.fetch(query, *params)
            return [
                {
                    'id': row['id'],
                    'server_ip': row['server_ip'],
                    'event_type': row['event_type'],
                    'event_time': row['event_time'].isoformat() + 'Z',
                    'duration_seconds': row['duration_seconds'],
                    'details': row['details']
                }
                for row in rows
            ]
    except Exception as e:
        logger.error(f"Failed to fetch server events: {str(e)}")
        return []

async def cleanup():
    """Cleanup database connections"""
    global _db_pool
    if _db_pool:
        await _db_pool.close()
        _db_pool = None
        logger.info("Database pool closed")
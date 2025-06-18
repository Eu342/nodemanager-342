import os
import jwt
import bcrypt
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from fastapi import Depends, HTTPException, status, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import asyncpg
import logging
from dotenv import load_dotenv
import traceback

load_dotenv()
logger = logging.getLogger(__name__)

# Security settings
SECRET_KEY = os.getenv('JWT_SECRET_KEY', secrets.token_urlsafe(32))
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv('ACCESS_TOKEN_EXPIRE_MINUTES', '60'))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv('REFRESH_TOKEN_EXPIRE_DAYS', '7'))

# Ensure we have a strong secret key
if len(SECRET_KEY) < 32:
    raise ValueError("JWT_SECRET_KEY must be at least 32 characters long")

# Security scheme
security = HTTPBearer()

class AuthHandler:
    def __init__(self):
        self.secret = SECRET_KEY
        self.algorithm = ALGORITHM
        
    def hash_password(self, password: str) -> str:
        """Hash password using bcrypt"""
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify password against hash"""
        try:
            return bcrypt.checkpw(
                plain_password.encode('utf-8'), 
                hashed_password.encode('utf-8')
            )
        except Exception:
            return False
    
    def create_access_token(self, username: str, scopes: List[str] = None) -> str:
        """Create JWT access token"""
        payload = {
            'sub': username,
            'iat': datetime.now(timezone.utc),
            'exp': datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
            'type': 'access',
            'scopes': scopes or ['user']
        }
        return jwt.encode(payload, self.secret, algorithm=self.algorithm)
    
    def create_refresh_token(self, username: str) -> str:
        """Create JWT refresh token"""
        payload = {
            'sub': username,
            'iat': datetime.now(timezone.utc),
            'exp': datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
            'type': 'refresh'
        }
        return jwt.encode(payload, self.secret, algorithm=self.algorithm)
    
    def decode_token(self, token: str) -> Dict[str, Any]:
        """Decode and validate JWT token"""
        try:
            payload = jwt.decode(token, self.secret, algorithms=[self.algorithm])
            return payload
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except jwt.InvalidTokenError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
                headers={"WWW-Authenticate": "Bearer"},
            )

auth_handler = AuthHandler()

# Database functions
async def init_auth_db(pool: asyncpg.Pool):
    """Initialize authentication tables"""
    try:
        async with pool.acquire() as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(50) UNIQUE NOT NULL,
                    password_hash VARCHAR(100) NOT NULL,
                    is_active BOOLEAN DEFAULT true,
                    is_admin BOOLEAN DEFAULT false,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login TIMESTAMP,
                    failed_attempts INTEGER DEFAULT 0,
                    locked_until TIMESTAMP
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS refresh_tokens (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    token_hash VARCHAR(100) UNIQUE NOT NULL,
                    expires_at TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    revoked BOOLEAN DEFAULT false
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS login_attempts (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(50),
                    ip_address INET,
                    success BOOLEAN,
                    attempted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create indexes
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user ON refresh_tokens(user_id)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_login_attempts_ip ON login_attempts(ip_address)')
            
            # Create default admin user if not exists
            admin_exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM users WHERE username = 'admin')"
            )
            
            if not admin_exists:
                default_password = os.getenv('DEFAULT_ADMIN_PASSWORD', secrets.token_urlsafe(16))
                await conn.execute(
                    '''
                    INSERT INTO users (username, password_hash, is_admin)
                    VALUES ($1, $2, true)
                    ''',
                    'admin',
                    auth_handler.hash_password(default_password)
                )
                logger.warning(f"Created default admin user. Password: {default_password}")
                logger.warning("PLEASE CHANGE THIS PASSWORD IMMEDIATELY!")
                
    except Exception as e:
        logger.error(f"Failed to initialize auth database: {str(e)}\n{traceback.format_exc()}")
        raise

async def create_user(pool: asyncpg.Pool, username: str, password: str, is_admin: bool = False) -> bool:
    """Create new user"""
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                '''
                INSERT INTO users (username, password_hash, is_admin)
                VALUES ($1, $2, $3)
                ''',
                username,
                auth_handler.hash_password(password),
                is_admin
            )
        return True
    except asyncpg.UniqueViolationError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already exists"
        )
    except Exception as e:
        logger.error(f"Failed to create user: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create user"
        )

async def authenticate_user(pool: asyncpg.Pool, username: str, password: str, ip_address: str) -> Optional[Dict[str, Any]]:
    """Authenticate user and handle login attempts"""
    try:
        async with pool.acquire() as conn:
            # Check if user is locked
            user = await conn.fetchrow(
                '''
                SELECT id, username, password_hash, is_active, is_admin, 
                       failed_attempts, locked_until
                FROM users 
                WHERE username = $1
                ''',
                username
            )
            
            if not user:
                # Log failed attempt
                await conn.execute(
                    '''
                    INSERT INTO login_attempts (username, ip_address, success)
                    VALUES ($1, $2, false)
                    ''',
                    username, ip_address
                )
                return None
            
            # Check if account is locked
            if user['locked_until'] and user['locked_until'] > datetime.now(timezone.utc):
                raise HTTPException(
                    status_code=status.HTTP_423_LOCKED,
                    detail=f"Account locked until {user['locked_until'].isoformat()}"
                )
            
            # Verify password
            if not auth_handler.verify_password(password, user['password_hash']):
                # Increment failed attempts
                failed_attempts = user['failed_attempts'] + 1
                locked_until = None
                
                # Lock account after 5 failed attempts
                if failed_attempts >= 5:
                    locked_until = datetime.now(timezone.utc) + timedelta(minutes=30)
                
                await conn.execute(
                    '''
                    UPDATE users 
                    SET failed_attempts = $1, locked_until = $2
                    WHERE id = $3
                    ''',
                    failed_attempts, locked_until, user['id']
                )
                
                # Log failed attempt
                await conn.execute(
                    '''
                    INSERT INTO login_attempts (username, ip_address, success)
                    VALUES ($1, $2, false)
                    ''',
                    username, ip_address
                )
                
                return None
            
            # Check if account is active
            if not user['is_active']:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Account is disabled"
                )
            
            # Reset failed attempts and update last login
            await conn.execute(
                '''
                UPDATE users 
                SET failed_attempts = 0, locked_until = NULL, last_login = CURRENT_TIMESTAMP
                WHERE id = $1
                ''',
                user['id']
            )
            
            # Log successful attempt
            await conn.execute(
                '''
                INSERT INTO login_attempts (username, ip_address, success)
                VALUES ($1, $2, true)
                ''',
                username, ip_address
            )
            
            return {
                'id': user['id'],
                'username': user['username'],
                'is_admin': user['is_admin']
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Authentication error: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication failed"
        )

async def save_refresh_token(pool: asyncpg.Pool, user_id: int, token: str) -> bool:
    """Save refresh token to database"""
    try:
        token_hash = bcrypt.hashpw(token.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        expires_at = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
        
        async with pool.acquire() as conn:
            await conn.execute(
                '''
                INSERT INTO refresh_tokens (user_id, token_hash, expires_at)
                VALUES ($1, $2, $3)
                ''',
                user_id, token_hash, expires_at
            )
        return True
    except Exception as e:
        logger.error(f"Failed to save refresh token: {str(e)}")
        return False

async def verify_refresh_token(pool: asyncpg.Pool, user_id: int, token: str) -> bool:
    """Verify refresh token"""
    try:
        async with pool.acquire() as conn:
            tokens = await conn.fetch(
                '''
                SELECT token_hash, expires_at, revoked
                FROM refresh_tokens
                WHERE user_id = $1 AND revoked = false AND expires_at > $2
                ''',
                user_id, datetime.now(timezone.utc)
            )
            
            for token_row in tokens:
                if bcrypt.checkpw(token.encode('utf-8'), token_row['token_hash'].encode('utf-8')):
                    return True
            
            return False
    except Exception as e:
        logger.error(f"Failed to verify refresh token: {str(e)}")
        return False

async def revoke_refresh_token(pool: asyncpg.Pool, user_id: int, token: str) -> bool:
    """Revoke refresh token"""
    try:
        async with pool.acquire() as conn:
            # Get all tokens for user
            tokens = await conn.fetch(
                '''
                SELECT id, token_hash
                FROM refresh_tokens
                WHERE user_id = $1 AND revoked = false
                ''',
                user_id
            )
            
            # Find and revoke matching token
            for token_row in tokens:
                if bcrypt.checkpw(token.encode('utf-8'), token_row['token_hash'].encode('utf-8')):
                    await conn.execute(
                        'UPDATE refresh_tokens SET revoked = true WHERE id = $1',
                        token_row['id']
                    )
                    return True
            
            return False
    except Exception as e:
        logger.error(f"Failed to revoke refresh token: {str(e)}")
        return False

# Dependency injection for protected routes
async def get_current_user(credentials: HTTPAuthorizationCredentials = Security(security)) -> Dict[str, Any]:
    """Get current user from JWT token"""
    token = credentials.credentials
    try:
        payload = auth_handler.decode_token(token)
        if payload.get('type') != 'access':
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type"
            )
        return {
            'username': payload['sub'],
            'scopes': payload.get('scopes', ['user'])
        }
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

async def require_admin(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Require admin privileges"""
    if 'admin' not in current_user.get('scopes', []):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )
    return current_user

# Rate limiting decorator
from functools import wraps
from collections import defaultdict
import time

class RateLimiter:
    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests = defaultdict(list)
    
    def is_allowed(self, key: str) -> bool:
        now = time.time()
        # Clean old requests
        self.requests[key] = [
            req_time for req_time in self.requests[key]
            if now - req_time < self.window_seconds
        ]
        
        if len(self.requests[key]) >= self.max_requests:
            return False
        
        self.requests[key].append(now)
        return True

# Global rate limiter instances
login_limiter = RateLimiter(max_requests=5, window_seconds=300)  # 5 attempts per 5 minutes
api_limiter = RateLimiter(max_requests=100, window_seconds=60)   # 100 requests per minute
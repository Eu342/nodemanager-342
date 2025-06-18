from pydantic import BaseModel, Field, validator, IPvAnyAddress
from typing import List, Optional, Dict, Any
from datetime import datetime
import re
import ipaddress

# API Request Models
class ServerForm(BaseModel):
    ip: IPvAnyAddress
    inbound_tag: str = Field(..., min_length=1, max_length=100)
    
    @validator('inbound_tag')
    def validate_inbound_tag(cls, v):
        if not re.match(r'^[\w\s\-\.]+$', v):
            raise ValueError('Inbound tag contains invalid characters')
        return v.strip()

class RebootRequest(BaseModel):
    ips: List[IPvAnyAddress] = Field(..., min_items=1, max_items=100)

class RunScriptsRequest(BaseModel):
    ips: List[IPvAnyAddress] = Field(..., min_items=1, max_items=100)
    script_name: str = Field(..., pattern=r'^[\w\-]+\.sh$', max_length=100)

class AddServerRequest(BaseModel):
    ips: List[str] = Field(..., min_items=1, max_items=50)
    inbound_tag: str = Field(..., min_length=1, max_length=100)
    
    @validator('ips', each_item=True)
    def validate_ip(cls, v):
        try:
            ipaddress.ip_address(v)
            return v
        except ValueError:
            raise ValueError(f'Invalid IP address: {v}')
    
    @validator('inbound_tag')
    def validate_inbound_tag(cls, v):
        if not re.match(r'^[\w\s\-\.]+$', v):
            raise ValueError('Inbound tag contains invalid characters')
        return v.strip()

class EditServerRequest(BaseModel):
    old_ip: IPvAnyAddress
    new_ip: IPvAnyAddress
    new_inbound_tag: str = Field(..., min_length=1, max_length=100)
    
    @validator('new_inbound_tag')
    def validate_inbound_tag(cls, v):
        if not re.match(r'^[\w\s\-\.]+$', v):
            raise ValueError('Inbound tag contains invalid characters')
        return v.strip()

class VlessKeyUpdate(BaseModel):
    inbound_tag: str = Field(..., min_length=1, max_length=100)
    serverName: str = Field(..., min_length=1, max_length=255)
    vless_key: str = Field(..., min_length=1, max_length=1000)
    domain: str = Field(..., pattern=r'^([a-zA-Z0-9][a-zA-Z0-9-]*\.)+[a-zA-Z]{2,}$', max_length=255)

# Authentication Models
class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, pattern=r'^[a-zA-Z0-9_-]+$')
    password: str = Field(..., min_length=8, max_length=100)
    
    @validator('password')
    def validate_password(cls, v):
        if not re.search(r'[A-Z]', v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not re.search(r'[a-z]', v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not re.search(r'[0-9]', v):
            raise ValueError('Password must contain at least one digit')
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', v):
            raise ValueError('Password must contain at least one special character')
        return v

class UserLogin(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=100)

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int

class TokenData(BaseModel):
    username: Optional[str] = None
    scopes: List[str] = []

# Response Models
class ServerResponse(BaseModel):
    ip: str
    inbound_tag: str
    install_date: Optional[datetime]
    status: Optional[str] = None

class OperationResult(BaseModel):
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None

class ServerEvent(BaseModel):
    id: int
    server_ip: str
    event_type: str
    event_time: datetime
    duration_seconds: Optional[int]

# Settings Models
class SettingsUpdate(BaseModel):
    subscription_url: Optional[str] = Field(None, pattern=r'^https?://.+', max_length=500)
    refresh_hours: int = Field(1, ge=1, le=24)
    telegram_bot_token: Optional[str] = Field(None, max_length=100)
    telegram_chat_id: Optional[str] = Field(None, max_length=50)
    dns_ttl: int = Field(120, ge=60, le=86400)
    cloudflare_api_token: Optional[str] = Field(None, max_length=200)

# Query Parameters Models
class PaginationParams(BaseModel):
    skip: int = Field(0, ge=0)
    limit: int = Field(50, ge=1, le=1000)

class EventQueryParams(BaseModel):
    period: str = Field('24h', pattern=r'^(24h|7d|30d)$')
    server_ip: Optional[IPvAnyAddress] = None
    limit: int = Field(100, ge=1, le=1000)

# Validation helpers
def validate_domain(domain: str) -> str:
    """Validate domain name"""
    pattern = r'^([a-zA-Z0-9][a-zA-Z0-9-]*\.)+[a-zA-Z]{2,}$'
    if not re.match(pattern, domain):
        raise ValueError(f"Invalid domain: {domain}")
    return domain.lower()

def validate_script_name(script_name: str) -> str:
    """Validate script filename"""
    if not script_name.endswith('.sh'):
        raise ValueError("Script must have .sh extension")
    if not re.match(r'^[\w\-]+\.sh$', script_name):
        raise ValueError("Invalid script name")
    return script_name

def sanitize_string(value: str, max_length: int = 255) -> str:
    """Sanitize string input"""
    # Remove null bytes
    value = value.replace('\x00', '')
    # Strip whitespace
    value = value.strip()
    # Limit length
    value = value[:max_length]
    return value
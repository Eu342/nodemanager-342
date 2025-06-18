import aiohttp
import os
import logging
import traceback
from typing import Dict, Optional, Set
from datetime import datetime, timedelta
import asyncio

logger = logging.getLogger(__name__)

# Global tracking for DNS operations
_dns_operation_cache: Dict[str, datetime] = {}
_pending_operations: Set[str] = set()
_operation_lock = asyncio.Lock()
MIN_CHECK_INTERVAL = timedelta(minutes=5)

async def get_zone_id(domain: str) -> str:
    """Получает zone_id для домена через Cloudflare API."""
    try:
        # Извлекаем базовый домен (например, unfence.nl из n.unfence.nl)
        base_domain = '.'.join(domain.split('.')[-2:])
        url = "https://api.cloudflare.com/client/v4/zones"
        headers = {
            "Authorization": f"Bearer {os.getenv('CLOUDFLARE_API_TOKEN')}",
            "Content-Type": "application/json"
        }
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.get(url, headers=headers) as resp:
                result = await resp.json()
                if not result.get('success'):
                    logger.error(f"Failed to fetch zones: {result.get('errors', [])}")
                    raise Exception(f"Cloudflare API error: {result.get('errors', [])}")
                for zone in result.get('result', []):
                    if zone['name'] == base_domain:
                        logger.debug(f"Found zone_id {zone['id']} for domain {base_domain}")
                        return zone['id']
                logger.error(f"No zone found for domain {base_domain}")
                raise Exception(f"No zone found for domain {base_domain}")
    except Exception as e:
        logger.error(f"Failed to get zone_id for {domain}: {str(e)}\n{traceback.format_exc()}")
        raise

async def should_create_dns_record(ip: str, domain: str, inbound_letter: str) -> bool:
    """Check if DNS record should be created to prevent duplicates"""
    record_key = f"{ip}:{domain}:d{inbound_letter}"
    
    async with _operation_lock:
        # Check if operation is pending
        if record_key in _pending_operations:
            logger.debug(f"DNS operation already pending for {record_key}")
            return False
        
        # Check rate limiting
        now = datetime.utcnow()
        if record_key in _dns_operation_cache:
            time_since_last = now - _dns_operation_cache[record_key]
            if time_since_last < MIN_CHECK_INTERVAL:
                logger.debug(f"Rate limiting DNS operation for {record_key}, last operation {time_since_last.seconds}s ago")
                return False
        
        # Mark as pending
        _pending_operations.add(record_key)
        return True

async def mark_dns_operation_complete(ip: str, domain: str, inbound_letter: str):
    """Mark DNS operation as complete"""
    record_key = f"{ip}:{domain}:d{inbound_letter}"
    
    async with _operation_lock:
        _dns_operation_cache[record_key] = datetime.utcnow()
        _pending_operations.discard(record_key)

async def create_dns_record(ip: str, inbound_letter: str, ttl: int, domain: str) -> dict:
    """Создаёт DNS-запись d<inbound_letter> для IP в зоне домена с защитой от дубликатов."""
    logger.debug(f"Creating DNS record: inbound_letter={inbound_letter}, domain={domain}, ip={ip}, ttl={ttl}")
    
    # Check if we should create this record
    if not await should_create_dns_record(ip, domain, inbound_letter):
        logger.info(f"Skipping DNS record creation for {ip} (already exists or rate limited)")
        return {"success": False, "reason": "Record exists or rate limited"}
    
    try:
        # First check if record already exists
        existing = await find_dns_record(ip, domain)
        if existing:
            logger.info(f"DNS record already exists for {ip} in domain {domain}: {existing.get('name')}")
            await mark_dns_operation_complete(ip, domain, inbound_letter)
            return {"success": True, "result": existing, "existed": True}
        
        zone_id = await get_zone_id(domain)
        url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records"
        headers = {
            "Authorization": f"Bearer {os.getenv('CLOUDFLARE_API_TOKEN')}",
            "Content-Type": "application/json"
        }
        payload = {
            "type": "A",
            "name": f"d{inbound_letter}",
            "content": ip,
            "ttl": ttl,
            "proxied": False
        }
        logger.debug(f"DNS record payload: {payload}")
        
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                result = await resp.json()
                if not result.get('success'):
                    # Check if error is about duplicate record
                    errors = result.get('errors', [])
                    for error in errors:
                        if 'already exists' in str(error.get('message', '')).lower():
                            logger.info(f"DNS record already exists for d{inbound_letter}.{domain}")
                            await mark_dns_operation_complete(ip, domain, inbound_letter)
                            return {"success": True, "result": {"existed": True}}
                    
                    logger.error(f"Failed to create DNS record for {ip}: {errors}")
                    raise Exception(f"Cloudflare API error: {errors}")
                    
                logger.info(f"Created DNS record d{inbound_letter}.{domain} for {ip}")
                await mark_dns_operation_complete(ip, domain, inbound_letter)
                return result
                
    except Exception as e:
        logger.error(f"Failed to create DNS record for {ip}: {str(e)}\n{traceback.format_exc()}")
        # Remove from pending on error
        record_key = f"{ip}:{domain}:d{inbound_letter}"
        async with _operation_lock:
            _pending_operations.discard(record_key)
        raise

async def find_dns_record(ip: str, domain: str) -> Optional[dict]:
    """Ищет DNS-запись для IP в зоне домена."""
    try:
        zone_id = await get_zone_id(domain)
        url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records?type=A&content={ip}"
        headers = {"Authorization": f"Bearer {os.getenv('CLOUDFLARE_API_TOKEN')}"}
        
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.get(url, headers=headers) as resp:
                result = await resp.json()
                if result.get('success') and result.get('result'):
                    logger.debug(f"Found DNS record for {ip}: {result['result'][0]}")
                    return result['result'][0]
                logger.debug(f"No DNS record found for {ip} in domain {domain}")
                return None
    except Exception as e:
        logger.error(f"Failed to find DNS record for {ip} in domain {domain}: {str(e)}\n{traceback.format_exc()}")
        return None

async def delete_dns_record(record_id: str, domain: str) -> bool:
    """Удаляет DNS-запись по ID в зоне домена."""
    try:
        zone_id = await get_zone_id(domain)
        url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{record_id}"
        headers = {"Authorization": f"Bearer {os.getenv('CLOUDFLARE_API_TOKEN')}"}
        
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.delete(url, headers=headers) as resp:
                result = await resp.json()
                if not result.get('success'):
                    logger.error(f"Failed to delete DNS record {record_id}: {result.get('errors', [])}")
                    raise Exception(f"Cloudflare API error: {result.get('errors', [])}")
                logger.info(f"Deleted DNS record {record_id}")
                return True
    except Exception as e:
        logger.error(f"Failed to delete DNS record {record_id} in domain {domain}: {str(e)}\n{traceback.format_exc()}")
        raise

# Cleanup function to clear old cache entries
async def cleanup_dns_cache():
    """Remove old entries from DNS operation cache"""
    async with _operation_lock:
        now = datetime.utcnow()
        expired_keys = [
            key for key, timestamp in _dns_operation_cache.items()
            if now - timestamp > timedelta(hours=1)
        ]
        for key in expired_keys:
            del _dns_operation_cache[key]
        if expired_keys:
            logger.debug(f"Cleaned up {len(expired_keys)} expired DNS cache entries")
import aiohttp
import os
import logging
import traceback

logger = logging.getLogger(__name__)

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

async def create_dns_record(ip: str, inbound_letter: str, ttl: int, domain: str) -> dict:
    """Создаёт DNS-запись d<inbound_letter> для IP в зоне домена."""
    logger.debug(f"Creating DNS record: inbound_letter={inbound_letter}, domain={domain}, ip={ip}, ttl={ttl}")
    try:
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
                    logger.error(f"Failed to create DNS record for {ip}: {result.get('errors', [])}")
                    raise Exception(f"Cloudflare API error: {result.get('errors', [])}")
                logger.info(f"Created DNS record d{inbound_letter}.{domain} for {ip}")
                return result
    except Exception as e:
        logger.error(f"Failed to create DNS record for {ip}: {str(e)}\n{traceback.format_exc()}")
        raise

async def find_dns_record(ip: str, domain: str) -> dict:
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
        raise

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
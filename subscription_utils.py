import base64
import uuid
import aiohttp
import json
from urllib.parse import urlparse, parse_qs, unquote
import logging
import traceback
logger = logging.getLogger(__name__)

async def fetch_subscription_keys(subscription_url):
    logger.debug(f"Fetching subscription from {subscription_url}")
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(subscription_url) as response:
                logger.info(f"Subscription response status: {response.status}")
                if response.status != 200:
                    logger.error(f"Subscription fetch failed: {response.status}")
                    return []
                base64_text = await response.text()
                logger.debug(f"Raw subscription response: {base64_text[:100]}...")
        except Exception as e:
            logger.error(f"Failed to fetch subscription: {str(e)}\n{traceback.format_exc()}")
            return []
        try:
            text = base64.b64decode(base64_text).decode('utf-8')
            logger.debug(f"Decoded subscription text: {text[:100]}...")
        except Exception as e:
            logger.error(f"Failed to decode Base64: {str(e)}\n{traceback.format_exc()}")
            return []
        keys = []
        for line in text.splitlines():
            if line.startswith('vless://'):
                try:
                    parsed = urlparse(line)
                    query = parse_qs(parsed.query)
                    logger.debug(f"Parsed VLESS key: {line[:50]}...")
                    if not parsed.username or not query.get('sni') or not query.get('pbk') or not query.get('sid'):
                        logger.warning(f"Invalid VLESS key: {line[:50]}...")
                        continue
                    try:
                        uuid.UUID(parsed.username)
                    except:
                        logger.warning(f"Invalid UUID in key: {line[:50]}...")
                        continue
                    inbound_tag = unquote(parsed.fragment)
                    logger.debug(f"Decoded inbound_tag: {inbound_tag}")
                    keys.append({
                        'inbound_tag': inbound_tag,
                        'serverName': query['sni'][0],
                        'vless_key': line
                    })
                except Exception as e:
                    logger.warning(f"Failed to parse VLESS key: {str(e)}\n{traceback.format_exc()}")
        logger.info(f"Parsed {len(keys)} VLESS keys")
        return keys

def parse_vless_key(key):
    logger.debug(f"Parsing VLESS key: {key[:50]}...")
    try:
        parsed = urlparse(key)
        query = parse_qs(parsed.query)
        logger.debug(f"Parsed query: {query}")
        if not parsed.username or not query.get('sni') or not query.get('pbk') or not query.get('sid'):
            logger.error(f"Invalid VLESS key format: missing required fields in {key[:50]}...")
            raise ValueError("Invalid VLESS key")
        try:
            uuid.UUID(parsed.username)
            logger.debug(f"Valid UUID: {parsed.username}")
        except:
            logger.error(f"Invalid UUID in key: {key[:50]}...")
            raise ValueError("Invalid UUID")
        result = {
            "id": parsed.username,
            "serverName": query['sni'][0],
            "publicKey": query['pbk'][0],
            "shortId": query['sid'][0]
        }
        logger.debug(f"Parsed VLESS key result: {result}")
        return result
    except Exception as e:
        logger.error(f"Failed to parse VLESS key: {str(e)}\n{traceback.format_exc()}")
        raise ValueError(f"Failed to parse VLESS key: {str(e)}")

def create_outbound_json(ip, inbound_tag, vless_key):
    logger.debug(f"Creating outbound JSON for IP {ip}, inbound_tag {inbound_tag}, vless_key {vless_key[:50]}...")
    try:
        key_data = parse_vless_key(vless_key)
        config = {
            "outbounds": [{
                "protocol": "vless",
                "settings": {
                    "vnext": [{
                        "address": ip,
                        "port": 443,
                        "users": [{
                            "id": key_data["id"],
                            "encryption": "none",
                            "flow": "xtls-rprx-vision"
                        }]
                    }]
                },
                "streamSettings": {
                    "network": "tcp",
                    "security": "reality",
                    "realitySettings": {
                        "fingerprint": "chrome",
                        "serverName": key_data["serverName"],
                        "publicKey": key_data["publicKey"],
                        "shortId": key_data["shortId"],
                        "show": False
                    }
                },
                "tag": inbound_tag.replace(" ", "_")
            }]
        }
        logger.debug(f"Created outbound JSON for {ip}: {json.dumps(config, indent=2)}")
        return config
    except Exception as e:
        logger.error(f"Failed to create outbound JSON for {ip}: {str(e)}\n{traceback.format_exc()}")
        raise ValueError(f"Failed to create outbound JSON: {str(e)}")
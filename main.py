import asyncio
import ipaddress
import logging
import os
import re
import traceback
import asyncpg
from contextlib import asynccontextmanager
from typing import List
from fastapi import FastAPI, Form, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from db import init_db, get_vless_keys, get_vless_key, update_vless_key, add_server, get_servers, delete_server, log_server_event, get_server_events
from ssh_utils import deploy_script, check_server_availability
from config import Config
import aiohttp
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from subscription_utils import fetch_subscription_keys, create_outbound_json, parse_vless_key
import json
import shutil
import asyncssh
import subprocess
from datetime import datetime, timedelta
import retrying
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

previous_statuses = {}
pending_retries = {}
last_offline_webhook = {}
last_check_time = {}  # Track last check time for each IP

class NoCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response

class ServerForm(BaseModel):
    ip: str
    inbound_tag: str

class RebootRequest(BaseModel):
    ips: List[str]

class RunScriptsRequest(BaseModel):
    ips: List[str]
    script_name: str

class AddServerRequest(BaseModel):
    ips: List[str]
    inbound_tag: str

class EditServerRequest(BaseModel):
    old_ip: str
    new_ip: str
    new_inbound_tag: str

def get_script_name(inbound_tag: str) -> str:
    safe_tag = re.sub(r'[\U0001F1E6-\U0001F1FF]+', '', inbound_tag).strip()
    script_name = safe_tag.lower().replace(" ", "_") + ".sh"
    logger.info(f"Generated script name: {script_name} for inbound_tag: {inbound_tag}")
    return script_name

def is_valid_ip(ip: str) -> bool:
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False

async def remove_existing_json(ip):
    remote_path = f"{os.getenv('XRAY_CHECKER_JSON_PATH')}/{ip}.json"
    try:
        logger.debug(f"Attempting to remove JSON at {remote_path}")
        if os.getenv('XRAY_CHECKER_SSH_KEY') and os.getenv('XRAY_CHECKER_HOST') not in ['localhost', '127.0.0.1']:
            logger.info(f"Removing JSON via SFTP at {remote_path} on {os.getenv('XRAY_CHECKER_HOST')}")
            async with asyncssh.connect(
                os.getenv('XRAY_CHECKER_HOST'),
                client_keys=[os.getenv('XRAY_CHECKER_SSH_KEY')],
                known_hosts=None,
                connect_timeout=30,
                login_timeout=30
            ) as conn:
                async with conn.start_sftp_client() as sftp:
                    try:
                        await sftp.stat(remote_path)
                        await sftp.remove(remote_path)
                        logger.info(f"Removed JSON at {remote_path}")
                    except asyncssh.SFTPError:
                        logger.debug(f"No JSON found at {remote_path}")
        elif os.getenv('XRAY_CHECKER_HOST') in ['localhost', '127.0.0.1']:
            logger.info(f"Removing local JSON at {remote_path}")
            if os.path.exists(remote_path):
                os.remove(remote_path)
                logger.info(f"Removed JSON at {remote_path}")
            else:
                logger.debug(f"No JSON found at {remote_path}")
        else:
            logger.error("Invalid Xray Checker config: SSH key or host not set")
            raise ValueError("SSH key or valid host required")
        return True
    except Exception as e:
        logger.error(f"Failed to remove JSON for {ip}: {str(e)}\n{traceback.format_exc()}")
        return False

async def restart_xray_checker():
    try:
        container_name = os.getenv('XRAY_CHECKER_CONTAINER_NAME', 'xraychecker-xray-checker')
        logger.info(f"Restarting Xray Checker container: {container_name}")
        if os.getenv('XRAY_CHECKER_SSH_KEY') and os.getenv('XRAY_CHECKER_HOST') not in ['localhost', '127.0.0.1']:
            async with asyncssh.connect(
                os.getenv('XRAY_CHECKER_HOST'),
                client_keys=[os.getenv('XRAY_CHECKER_SSH_KEY')],
                known_hosts=None,
                connect_timeout=30,
                login_timeout=30
            ) as conn:
                result = await conn.run(f'docker ps -a -q -f name={container_name}')
                if not result.stdout.strip():
                    logger.warning(f"Container {container_name} not found, skipping restart")
                    return True
                result = await conn.run(f'sudo docker restart {container_name}')
                if result.exit_status != 0:
                    logger.error(f"Docker restart failed: {result.stderr}")
                    raise Exception(f"Docker restart failed: {result.stderr}")
                logger.info("Xray Checker restarted successfully")
        elif os.getenv('XRAY_CHECKER_HOST') in ['localhost', '127.0.0.1']:
            result = subprocess.run(['docker', 'ps', '-a', '-q', '-f', f'name={container_name}'], capture_output=True, text=True)
            if not result.stdout.strip():
                logger.warning(f"Container {container_name} not found locally, skipping restart")
                return True
            result = subprocess.run(['sudo', 'docker', 'restart', container_name], capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"Docker restart failed: {result.stderr}")
                raise Exception(f"Docker restart failed: {result.stderr}")
            logger.info("Xray Checker restarted successfully")
        else:
            logger.error("Invalid Xray Checker config: SSH key or host not set")
            raise ValueError("SSH key or valid host required")
        return True
    except Exception as e:
        logger.error(f"Failed to restart Xray Checker: {str(e)}\n{traceback.format_exc()}")
        return False

async def copy_json_to_xray_checker(ip, json_data):
    local_path = f"/config/outbounds/{ip}.json"
    remote_path = f"{os.getenv('XRAY_CHECKER_JSON_PATH')}/{ip}.json"
    try:
        logger.debug(f"Creating JSON at {local_path}")
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "w") as f:
            json.dump(json_data, f, indent=2)
        logger.info(f"JSON created at {local_path}")

        if not os.getenv('XRAY_CHECKER_JSON_PATH'):
            logger.error("XRAY_CHECKER_JSON_PATH not set")
            raise ValueError("XRAY_CHECKER_JSON_PATH not set")

        if os.getenv('XRAY_CHECKER_SSH_KEY') and os.getenv('XRAY_CHECKER_HOST') not in ['localhost', '127.0.0.1']:
            logger.info(f"Copying JSON to {remote_path} via SFTP")
            async with asyncssh.connect(
                os.getenv('XRAY_CHECKER_HOST'),
                client_keys=[os.getenv('XRAY_CHECKER_SSH_KEY')],
                known_hosts=None,
                connect_timeout=30,
                login_timeout=30
            ) as conn:
                async with conn.start_sftp_client() as sftp:
                    try:
                        await sftp.stat(os.path.dirname(remote_path))
                    except asyncssh.SFTPError:
                        await sftp.makedirs(os.path.dirname(remote_path))
                        logger.info(f"Created directory {os.path.dirname(remote_path)}")
                    await sftp.put(local_path, remote_path)
                    logger.info(f"JSON copied to {remote_path}")
        elif os.getenv('XRAY_CHECKER_HOST') in ['localhost', '127.0.0.1']:
            logger.info(f"Copying JSON to local {remote_path}")
            os.makedirs(os.path.dirname(remote_path), exist_ok=True)
            shutil.copy2(local_path, remote_path)
            logger.info(f"JSON copied to {remote_path}")
        else:
            logger.error("Invalid Xray Checker config: SSH key or host not set")
            raise ValueError("SSH key or valid host required")
        return True
    except Exception as e:
        logger.error(f"Failed to copy JSON for {ip}: {str(e)}\n{traceback.format_exc()}")
        return False
    finally:
        if os.path.exists(local_path):
            logger.info(f"Removing temp JSON at {local_path}")
            os.remove(local_path)

async def update_xray_checker_json(ip, inbound_tag, vless_key):
    try:
        logger.debug(f"Updating Xray Checker JSON for {ip} with tag {inbound_tag}")
        if not await remove_existing_json(ip):
            logger.warning(f"Failed to remove existing JSON for {ip}, proceeding with update")
        json_data = create_outbound_json(ip, inbound_tag, vless_key)
        if not json_data:
            logger.error(f"create_outbound_json returned None for {ip}")
            raise ValueError("Failed to create outbound JSON")
        if not await copy_json_to_xray_checker(ip, json_data):
            logger.error(f"Failed to copy JSON for {ip}")
            raise ValueError(f"Failed to copy JSON for {ip}")
        if not await restart_xray_checker():
            logger.warning(f"Failed to restart Xray Checker for {ip}, but JSON copied")
        logger.info(f"JSON updated for {ip} with inbound_tag {inbound_tag}")
        return True
    except Exception as e:
        logger.error(f"Failed to update JSON for {ip}: {str(e)}\n{traceback.format_exc()}")
        return False

async def check_ip_in_xray_checker(ip):
    host = 'localhost' if os.getenv('XRAY_CHECKER_HOST') in ['localhost', '127.0.0.1'] else os.getenv('XRAY_CHECKER_HOST')
    url = f"http://{host}:{os.getenv('XRAY_CHECKER_PORT')}/metrics"
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    logger.error(f"Xray Checker status for {ip}: {response.status}")
                    last_check_time[ip] = datetime.utcnow()
                    return "unknown"
                metrics = await response.text()
                logger.debug(f"Metrics for {ip}: {metrics[:1000]}")
                status_pattern = r'xray_proxy_status{{[^}}]*address="{}:\d+"[^}}]*}} ([0-1])'.format(re.escape(ip))
                latency_pattern = r'xray_proxy_latency_ms{{[^}}]*address="{}:\d+"[^}}]*}} (\d+)'.format(re.escape(ip))
                status_match = re.search(status_pattern, metrics, re.MULTILINE)
                latency_match = re.search(latency_pattern, metrics, re.MULTILINE)
                if not status_match and not latency_match:
                    logger.debug(f"IP {ip} not found in XrayChecker metrics")
                    last_check_time[ip] = datetime.utcnow()
                    return "unknown"
                status = "unknown"
                if status_match:
                    status = "online" if status_match.group(1) == "1" else "offline"
                elif latency_match:
                    status = "online" if int(latency_match.group(1)) > 0 else "offline"
                logger.debug(f"IP {ip} in XrayChecker: status={status}")
                last_check_time[ip] = datetime.utcnow()
                return status
    except Exception as e:
        logger.error(f"Error checking IP {ip}: {str(e)}\n{traceback.format_exc()}")
        last_check_time[ip] = datetime.utcnow()
        return "unknown"

async def update_vless_keys_from_subscription():
    try:
        keys = await fetch_subscription_keys(os.getenv('SUBSCRIPTION_URL'))
        for key in keys:
            existing = await get_vless_key(key['inbound_tag'])
            if existing:
                await update_vless_key(key['inbound_tag'], existing['serverName'], key['vless_key'])
            else:
                await update_vless_key(key['inbound_tag'], key['serverName'], key['vless_key'])
        logger.info("VLESS keys updated successfully")
    except Exception as e:
        logger.error(f"Failed to update VLESS keys: {str(e)}\n{traceback.format_exc()}")

async def check_server_statuses():
    global previous_statuses, pending_retries, last_offline_webhook
    try:
        logger.debug("Checking server statuses")
        current_statuses = {}
        
        servers = await get_servers()
        valid_ips = {server[0] for server in servers if is_valid_ip(server[0])}
        logger.info(f"Valid server IPs from database: {valid_ips}")

        for server in servers:
            ip = server[0]
            if is_valid_ip(ip):
                status = await check_ip_in_xray_checker(ip)
                current_statuses[ip] = status
                logger.debug(f"IP {ip} status: {status}")

        if not current_statuses:
            logger.error("No server statuses available")
            return

        logger.debug(f"Current statuses: {current_statuses}")
        logger.debug(f"Previous statuses: {previous_statuses}")

        webhook_url = f"http://{os.getenv('NODEMONITORING_HOST')}:{os.getenv('NODEMONITORING_PORT')}/api/kuma/alert"
        logger.info(f"Preparing to send webhook to: {webhook_url}")

        semaphore = asyncio.Semaphore(1)
        @retrying.retry(
            stop_max_attempt_number=3,
            wait_fixed=5000,
            retry_on_exception=lambda e: isinstance(e, (asyncio.TimeoutError, aiohttp.ClientError))
        )
        async def send_webhook(ip, payload):
            async with semaphore:
                try:
                    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                        async with session.post(webhook_url, json=payload) as resp:
                            response_text = await resp.text()
                            logger.debug(f"Webhook response for {ip}: status={resp.status}, response={response_text}")
                            if resp.status != 200:
                                logger.error(f"Webhook failed for {ip}: status={resp.status}")
                                return False
                            logger.info(f"Webhook sent for {ip}: {payload}")
                            return True
                except Exception as e:
                    logger.error(f"Webhook error for {ip}: {str(e)}\n{traceback.format_exc()}")
                    raise

        current_time = datetime.utcnow()
        tasks = []
        for ip in current_statuses:
            if ip not in valid_ips:
                logger.debug(f"Skipping IP {ip}: not in servers")
                continue
            status = current_statuses[ip]
            prev_status = previous_statuses.get(ip, None)
            logger.info(f"Processing IP {ip}: current={status}, previous={prev_status}")

            if status != prev_status or prev_status is None:
                try:
                    if status in ["offline", "unknown"] and prev_status not in ["offline", "unknown"]:
                        await log_server_event(ip, "offline_start", duration_seconds=0)
                        logger.info(f"Logged offline_start for {ip}")
                        webhook_payload = {
                            "heartbeat": {"msg": "fail"},
                            "monitor": {"description": ip}
                        }
                        tasks.append((ip, webhook_payload))
                        last_offline_webhook[ip] = current_time
                    elif status == "online" and prev_status in ["offline", "unknown"]:
                        duration = int((current_time - last_check_time.get(ip, current_time)).total_seconds())
                        await log_server_event(ip, "offline_end", duration_seconds=duration)
                        logger.info(f"Logged offline_end for {ip}, duration={duration}s")
                        webhook_payload = {
                            "heartbeat": {"msg": "ok"},
                            "monitor": {"description": ip}
                        }
                        tasks.append((ip, webhook_payload))
                        if ip in last_offline_webhook:
                            del last_offline_webhook[ip]
                    elif status == "online" and prev_status is None:
                        await log_server_event(ip, "online", duration_seconds=0)
                        logger.info(f"Logged initial online for {ip}")
                    elif status in ["offline", "unknown"] and prev_status is None:
                        await log_server_event(ip, "offline_start", duration_seconds=0)
                        logger.info(f"Logged initial offline_start for {ip}")
                        webhook_payload = {
                            "heartbeat": {"msg": "fail"},
                            "monitor": {"description": ip}
                        }
                        tasks.append((ip, webhook_payload))
                        last_offline_webhook[ip] = current_time
                except Exception as e:
                    logger.error(f"Failed to log event for {ip}: {str(e)}\n{traceback.format_exc()}")

            if status in ["offline", "unknown"] and ip in last_offline_webhook:
                if (current_time - last_offline_webhook[ip]).total_seconds() >= 300:
                    logger.info(f"Sending repeat offline webhook for {ip}")
                    webhook_payload = {
                        "heartbeat": {"msg": "fail"},
                        "monitor": {"description": ip}
                    }
                    tasks.append((ip, webhook_payload))
                    last_offline_webhook[ip] = current_time

        for ip, (payload, last_attempt) in list(pending_retries.items()):
            if current_time - last_attempt >= timedelta(minutes=5):
                logger.info(f"Retrying webhook for {ip}")
                tasks.append((ip, payload))
                del pending_retries[ip]

        if tasks:
            results = await asyncio.gather(*(send_webhook(ip, payload) for ip, payload in tasks), return_exceptions=True)
            for (ip, payload), result in zip(tasks, results):
                if isinstance(result, Exception) or result is False:
                    pending_retries[ip] = (payload, current_time)
                    logger.error(f"Webhook for {ip} failed, retry in 5 min")
                else:
                    logger.info(f"Webhook for {ip} succeeded")

        previous_statuses.update(current_statuses)
        logger.debug(f"Updated previous statuses: {current_statuses}")
    except Exception as e:
        logger.error(f"Error in status check: {str(e)}\n{traceback.format_exc()}")

scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await init_db()
        logger.info("Database initialized")
        scheduler.add_job(update_vless_keys_from_subscription, 'interval', hours=int(os.getenv('SUBSCRIPTION_REFRESH_HOURS', 1)))
        scheduler.add_job(check_server_statuses, 'interval', minutes=1)
        scheduler.start()
    except Exception as e:
        logger.error(f"Failed to initialize database: {str(e)}\n{traceback.format_exc()}")
        raise
    yield

app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(NoCacheMiddleware)
app.mount("/static", StaticFiles(directory="static", html=True), name="static")

load_dotenv()
XRAY_CHECKER_URL = f"http://{os.getenv('XRAY_CHECKER_HOST')}:{os.getenv('XRAY_CHECKER_PORT')}"

@app.get("/nodemanager", response_class=HTMLResponse)
async def index():
    try:
        with open("static/index.html") as f:
            logger.info("Serving index.html")
            return HTMLResponse(content=f.read())
    except Exception as e:
        logger.error(f"Error serving index.html: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/nodemanager/add", response_class=HTMLResponse)
async def add_server_page():
    try:
        with open("static/add_server.html") as f:
            logger.info("Serving add_server.html")
            return HTMLResponse(content=f.read())
    except Exception as e:
        logger.error(f"Error serving add_server.html: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/nodemanager/setup", response_class=HTMLResponse)
async def setup_server_page():
    try:
        with open("static/setup_server.html") as f:
            logger.info("Serving setup_server.html")
            return HTMLResponse(content=f.read())
    except Exception as e:
        logger.error(f"Error serving setup_server.html: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/nodemanager/list", response_class=HTMLResponse)
async def server_list_page():
    try:
        with open("static/server_list.html") as f:
            logger.info("Serving server_list.html")
            return HTMLResponse(content=f.read())
    except Exception as e:
        logger.error(f"Error serving server_list.html: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/nodemanager/uptime", response_class=HTMLResponse)
async def uptime_page():
    try:
        with open("static/uptime.html") as f:
            logger.info("Serving uptime.html")
            return HTMLResponse(content=f.read())
    except Exception as e:
        logger.error(f"Error serving uptime.html: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/nodemanager/settings/subscription", response_class=HTMLResponse)
async def settings_subscription_page():
    try:
        with open("static/settings_subscription.html") as f:
            logger.info("Serving settings_subscription.html")
            return HTMLResponse(content=f.read())
    except Exception as e:
        logger.error(f"Error serving settings_subscription.html: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/vless_keys")
async def get_vless_keys_api():
    try:
        keys = await get_vless_keys()
        if not keys:
            logger.warning("No vless keys returned from database")
            return {"data": []}
        logger.info(f"Returning {len(keys)} vless keys")
        return {"data": keys}
    except Exception as e:
        logger.error(f"Failed to fetch vless keys: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Failed to fetch vless keys")

@app.get("/api/inbound_tags")
async def get_inbound_tags():
    try:
        keys = await get_vless_keys()
        tags = [key['inbound_tag'] for key in keys]
        logger.info(f"Returning {len(tags)} inbound tags")
        return {"tags": tags}
    except Exception as e:
        logger.error(f"Failed to fetch inbound tags: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Failed to fetch inbound tags")

@app.get("/api/scripts")
async def get_scripts():
    try:
        scripts = [f for f in os.listdir(Config.SCRIPTS_PATH) if f.endswith('.sh')]
        if not scripts:
            logger.warning("No scripts found in scripts directory")
            return {"scripts": []}
        logger.info(f"Returning {len(scripts)} scripts")
        return {"scripts": scripts}
    except Exception as e:
        logger.error(f"Failed to fetch scripts: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Failed to fetch scripts")

@app.get("/api/settings")
async def get_settings():
    return {"subscription_url": os.getenv('SUBSCRIPTION_URL')}

@app.post("/api/settings")
async def update_settings(settings: dict):
    try:
        with open(".env", "r") as f:
            lines = f.readlines()
        with open(".env", "w") as f:
            for line in lines:
                if line.startswith("SUBSCRIPTION_URL"):
                    f.write(f"SUBSCRIPTION_URL={settings['subscription_url']}\n")
                elif line.startswith("SUBSCRIPTION_REFRESH_HOURS"):
                    f.write(f"SUBSCRIPTION_REFRESH_HOURS={settings.get('refresh_hours', 1)}\n")
                else:
                    f.write(line)
        os.environ["SUBSCRIPTION_URL"] = settings['subscription_url']
        os.environ["SUBSCRIPTION_REFRESH_HOURS"] = str(settings.get('refresh_hours', 1))
        return {"message": "Settings updated"}
    except Exception as e:
        logger.error(f"Failed to update settings: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Failed to update settings")

@app.post("/api/refresh_keys")
async def refresh_keys():
    try:
        await update_vless_keys_from_subscription()
        return {"message": "Keys refreshed"}
    except Exception as e:
        logger.error(f"Failed to refresh keys: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Failed to refresh keys")

@app.post("/api/add_server")
async def add_server_api(request: AddServerRequest):
    logger.debug(f"Received /api/add_server request: {request}")
    try:
        for ip in request.ips:
            if not is_valid_ip(ip):
                logger.error(f"Invalid IP address: {ip}")
                raise HTTPException(status_code=400, detail=f"Invalid IP address: {ip}")
    except ValueError:
        logger.error(f"Invalid IP address in {request.ips}\n{traceback.format_exc()}")
        raise HTTPException(status_code=400, detail="Invalid IP address")
    script_name = get_script_name(request.inbound_tag)
    script_path = os.path.join(Config.SCRIPTS_PATH, script_name)
    if not os.path.exists(script_path):
        logger.error(f"Script {script_path} not found for inbound_tag: {request.inbound_tag}")
        raise HTTPException(status_code=400, detail=f"Script {script_name} not found")
    results = []
    semaphore = asyncio.Semaphore(10)
    async def deploy_and_add(ip):
        async with semaphore:
            logger.info(f"Attempting to deploy script {script_name} on {ip}")
            try:
                key = await get_vless_key(request.inbound_tag)
                logger.debug(f"Retrieved VLESS key for {request.inbound_tag}: {key}")
                if not key:
                    logger.error(f"Location {request.inbound_tag} not found for {ip}")
                    return {"ip": ip, "success": False, "message": f"Location {request.inbound_tag} not found"}
                if await check_ip_in_xray_checker(ip) != "unknown":
                    logger.debug(f"IP {ip} already in XrayChecker, forcing JSON update")
                if not await update_xray_checker_json(ip, request.inbound_tag, key['vless_key']):
                    return {"ip": ip, "success": False, "message": "Failed to update Xray Checker JSON"}
                success, message = await deploy_script(ip, script_name)
                logger.debug(f"deploy_script result for {ip}: success={success}, message={message}")
                if not isinstance(success, bool):
                    logger.error(f"Invalid success type from deploy_script: {success} for {ip}")
                    return {"ip": ip, "success": False, "message": f"Invalid deploy_script response: {success}"}
                if success:
                    conn = await asyncpg.connect(
                        database=os.getenv('LOCAL_DB_DBNAME'),
                        user=os.getenv('LOCAL_DB_USER'),
                        password=os.getenv('LOCAL_DB_PASSWORD'),
                        host=os.getenv('LOCAL_DB_HOST', 'localhost'),
                        port=os.getenv('LOCAL_DB_PORT', '5432')
                    )
                    async with conn.transaction():
                        await conn.execute(
                            """
                            INSERT INTO servers (ip, inbound_tag, install_date)
                            VALUES ($1, $2, CURRENT_TIMESTAMP)
                            ON CONFLICT (ip) DO UPDATE
                            SET inbound_tag = $2, install_date = CURRENT_TIMESTAMP
                            """,
                            ip, request.inbound_tag
                        )
                    await conn.close()
                    logger.info(f"Server {ip} added/updated successfully")
                    return {"ip": ip, "success": True, "message": "Server added successfully"}
                logger.error(f"Failed to deploy script on {ip}: {message}")
                return {"ip": ip, "success": False, "message": message}
            except Exception as e:
                logger.error(f"Error deploying script on {ip}: {str(e)}\n{traceback.format_exc()}")
                return {"ip": ip, "success": False, "message": str(e)}
    tasks = [deploy_and_add(ip) for ip in request.ips]
    results = await asyncio.gather(*tasks)
    response = {"results": results}
    logger.info(f"Batch server setup completed: {response}")
    return response

@app.post("/api/add_server_manual")
async def add_server_manual_api(request: AddServerRequest):
    logger.debug(f"Received /api/add_server_manual request: {request}")
    try:
        for ip in request.ips:
            if not is_valid_ip(ip):
                logger.error(f"Invalid IP address: {ip}")
                raise HTTPException(status_code=400, detail=f"Invalid IP address: {ip}")
    except ValueError:
        logger.error(f"Invalid IP address in {request.ips}\n{traceback.format_exc()}")
        raise HTTPException(status_code=400, detail="Invalid IP address")
    results = []
    for ip in request.ips:
        logger.info(f"Attempting to add server {ip} to database")
        try:
            key = await get_vless_key(request.inbound_tag)
            logger.debug(f"Retrieved VLESS key for {request.inbound_tag}: {key}")
            if not key:
                logger.error(f"Location {request.inbound_tag} not found for {ip}")
                results.append({"ip": ip, "success": False, "message": f"Location {request.inbound_tag} not found"})
                continue
            if await check_ip_in_xray_checker(ip) != "unknown":
                logger.debug(f"IP {ip} already in XrayChecker, forcing JSON update")
            if not await update_xray_checker_json(ip, request.inbound_tag, key['vless_key']):
                results.append({"ip": ip, "success": False, "message": "Failed to update Xray Checker JSON"})
                continue
            conn = await asyncpg.connect(
                database=os.getenv('LOCAL_DB_DBNAME'),
                user=os.getenv('LOCAL_DB_USER'),
                password=os.getenv('LOCAL_DB_PASSWORD'),
                host=os.getenv('LOCAL_DB_HOST', 'localhost'),
                port=os.getenv('LOCAL_DB_PORT', '5432')
            )
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO servers (ip, inbound_tag, install_date)
                    VALUES ($1, $2, CURRENT_TIMESTAMP)
                    ON CONFLICT (ip) DO UPDATE
                    SET inbound_tag = $2, install_date = CURRENT_TIMESTAMP
                    """,
                    ip, request.inbound_tag
                )
            await conn.close()
            logger.info(f"Server {ip} added/updated successfully")
            results.append({"ip": ip, "success": True, "message": "Server added successfully"})
        except Exception as e:
            logger.error(f"Error adding server {ip}: {str(e)}\n{traceback.format_exc()}")
            results.append({"ip": ip, "success": False, "message": str(e)})
    response = {"results": results}
    logger.info(f"Manual server addition completed: {response}")
    return response

@app.get("/api/servers")
async def get_servers_api():
    try:
        servers = await get_servers()
        formatted_servers = [
            {
                'ip': s[0],
                'inbound_tag': s[1],
                'install_date': s[2].isoformat() if s[2] else None
            } for s in servers if is_valid_ip(s[0])
        ]
        logger.info(f"Returning {len(formatted_servers)} servers")
        return {"servers": formatted_servers}
    except Exception as e:
        logger.error(f"Failed to fetch servers: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Failed to fetch servers")

@app.delete("/api/delete_server")
async def delete_server_api(ip: str = Query(...)):
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        logger.error(f"Invalid IP address for deletion: {ip}\n{traceback.format_exc()}")
        raise HTTPException(status_code=400, detail="Invalid IP address")
    if not await delete_server(ip):
        logger.error(f"Failed to delete server {ip}: not found in database")
        raise HTTPException(status_code=404, detail="Server not found")
    try:
        if not await remove_existing_json(ip):
            logger.error(f"Failed to remove JSON for {ip}")
            raise ValueError("Failed to remove JSON")
        if not await restart_xray_checker():
            logger.warning(f"Failed to restart Xray Checker for {ip}, but JSON removed")
        logger.info(f"Server {ip} deleted successfully from database, JSON removed")
    except Exception as e:
        logger.error(f"Failed to remove JSON or restart Xray Checker for {ip}: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Failed to remove JSON or restart Xray Checker for {ip}: {str(e)}")
    return {"message": "Server deleted successfully"}

@app.post("/api/reboot_server")
async def reboot_server_api(ip: str = Form(...)):
    logger.info(f"Received reboot request for IP: {ip}")
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        logger.error(f"Invalid IP address for reboot: {ip}\n{traceback.format_exc()}")
        raise HTTPException(status_code=400, detail="Invalid IP address")
    script_name = "reboot.sh"
    try:
        success, message = await deploy_script(ip, script_name)
        if not success:
            logger.error(f"Failed to reboot server {ip}: {message}")
            raise HTTPException(status_code=500, detail=f"Failed to reboot server: {message}")
    except Exception as e:
        logger.error(f"Exception in deploy_script for {ip}: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Failed to reboot server: {str(e)}")
    logger.info(f"Server {ip} rebooted successfully")
    return {"message": "Server rebooted successfully"}

@app.post("/api/reboot_servers")
async def reboot_servers_api(request: RebootRequest):
    logger.info(f"Received mass reboot request for IPs: {request.ips}")
    for ip in request.ips:
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            logger.error(f"Invalid IP address: {ip}\n{traceback.format_exc()}")
            raise HTTPException(status_code=400, detail=f"Invalid IP address: {ip}")
    script_name = "reboot.sh"
    results = []
    semaphore = asyncio.Semaphore(5)
    async def run_deploy_script(ip):
        async with semaphore:
            logger.info(f"Attempting to reboot server {ip} with script {script_name}")
            try:
                @retrying.retry(
                    stop_max_attempt_number=3,
                    wait_fixed=2000,
                    retry_on_exception=lambda e: isinstance(e, (asyncssh.misc.ConnectionLost, asyncssh.misc.DisconnectError))
                )
                async def execute_deploy():
                    return await deploy_script(ip, script_name)
                success, message = await execute_deploy()
                return {"ip": ip, "success": success, "message": message}
            except Exception as e:
                logger.error(f"Exception in deploy_script for {ip}: {str(e)}\n{traceback.format_exc()}")
                return {"ip": ip, "success": False, "message": str(e)}
    tasks = [run_deploy_script(ip) for ip in request.ips]
    results = await asyncio.gather(*tasks)
    response = {"results": results}
    logger.info(f"Mass reboot completed: {response}")
    return response

@app.post("/api/run_scripts")
async def run_scripts_api(request: RunScriptsRequest):
    logger.info(f"Received request to run script {request.script_name} on IPs: {request.ips}")
    for ip in request.ips:
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            logger.error(f"Invalid IP address: {ip}\n{traceback.format_exc()}")
            raise HTTPException(status_code=400, detail=f"Invalid IP address: {ip}")
    script_path = os.path.join(Config.SCRIPTS_PATH, request.script_name)
    if not os.path.exists(script_path):
        logger.error(f"Script {request.script_name} not found in {Config.SCRIPTS_PATH}")
        raise HTTPException(status_code=400, detail=f"Script {request.script_name} not found")
    results = []
    semaphore = asyncio.Semaphore(5)
    async def run_deploy_script(ip):
        async with semaphore:
            logger.info(f"Attempting to run script {request.script_name} on {ip}")
            try:
                @retrying.retry(
                    stop_max_attempt_number=3,
                    wait_fixed=2000,
                    retry_on_exception=lambda e: isinstance(e, (asyncssh.misc.ConnectionLost, asyncssh.misc.DisconnectError))
                )
                async def execute_deploy():
                    return await deploy_script(ip, script_name)
                success, message = await execute_deploy()
                return {"ip": ip, "success": success, "message": message}
            except Exception as e:
                logger.error(f"Exception in deploy_script for {ip}: {str(e)}\n{traceback.format_exc()}")
                return {"ip": ip, "success": False, "message": str(e)}
    tasks = [run_deploy_script(ip) for ip in request.ips]
    results = await asyncio.gather(*tasks)
    response = {"results": results}
    logger.info(f"Script execution completed: {response}")
    return response

@app.post("/api/edit_server")
async def edit_server_api(request: EditServerRequest):
    logger.info(f"Edit server request: {request}")
    try:
        ipaddress.ip_address(request.old_ip)
        ipaddress.ip_address(request.new_ip)
    except ValueError:
        logger.error(f"Invalid IP: old_ip={request.old_ip}, new_ip={request.new_ip}\n{traceback.format_exc()}")
        raise HTTPException(status_code=400, detail="Invalid IP address")
    try:
        servers = await get_servers()
        server = next((s for s in servers if s[0] == request.old_ip), None)
        if not server:
            logger.error(f"Server {request.old_ip} not found")
            raise HTTPException(status_code=404, detail="Server not found")
        key = await get_vless_key(request.new_inbound_tag)
        if not key:
            logger.error(f"Inbound tag {request.new_inbound_tag} not found")
            raise HTTPException(status_code=400, detail=f"Inbound tag {request.new_inbound_tag} not found")
        
        conn = await asyncpg.connect(
            database=os.getenv('LOCAL_DB_DBNAME'),
            user=os.getenv('LOCAL_DB_USER'),
            password=os.getenv('LOCAL_DB_PASSWORD'),
            host=os.getenv('LOCAL_DB_HOST', 'localhost'),
            port=os.getenv('LOCAL_DB_PORT', '5432')
        )
        async with conn.transaction():
            if request.old_ip != request.new_ip or server[1] != request.new_inbound_tag:
                if not await remove_existing_json(request.old_ip):
                    logger.error(f"Failed to remove JSON for {request.old_ip}")
                    raise HTTPException(status_code=500, detail="Failed to remove old JSON")
            if not await update_xray_checker_json(request.new_ip, request.new_inbound_tag, key['vless_key']):
                logger.error(f"Failed to update JSON for {request.new_ip}")
                raise HTTPException(status_code=500, detail="Failed to update Xray Checker JSON")
            
            delete_result = await conn.execute("DELETE FROM servers WHERE ip = $1", request.old_ip)
            logger.debug(f"Delete result for {request.old_ip}: {delete_result}")
            if delete_result == 'DELETE 0':
                logger.error(f"Failed to delete {request.old_ip} from database: not found")
                raise HTTPException(status_code=500, detail="Failed to update database: server not found")
            
            await conn.execute(
                """
                INSERT INTO servers (ip, inbound_tag, install_date)
                VALUES ($1, $2, CURRENT_TIMESTAMP)
                ON CONFLICT (ip) DO UPDATE
                SET inbound_tag = $2, install_date = CURRENT_TIMESTAMP
                """,
                request.new_ip, request.new_inbound_tag
            )
            logger.debug(f"Added new server {request.new_ip} with inbound_tag {request.new_inbound_tag}")
        
        await conn.close()
        logger.info(f"Server updated: {request.old_ip} -> {request.new_ip}, inbound_tag: {request.new_inbound_tag}")
        return {"success": True, "message": "Server updated"}
    except Exception as e:
        logger.error(f"Error editing {request.old_ip}: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Failed to update database: {str(e)}")

@app.get("/api/check_availability")
async def check_availability_api(ip: str):
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        logger.error(f"Invalid IP address: {ip}\n{traceback.format_exc()}")
        raise HTTPException(status_code=400, detail="Invalid IP address")
    is_available, message = await check_server_availability(ip)
    return {"ip": ip, "available": is_available, "message": message}

@app.get("/api/server_status")
async def get_server_status():
    try:
        statuses = {}
        servers = await get_servers()
        for server in servers:
            ip = server[0]
            if is_valid_ip(ip):
                status = await check_ip_in_xray_checker(ip)
                statuses[ip] = status
                logger.debug(f"IP {ip} status: {status}")
        logger.info(f"Parsed statuses: {statuses}")
        return {"statuses": statuses}
    except Exception as e:
        logger.error(f"Error fetching server status: {str(e)}\n{traceback.format_exc()}")
        return {"statuses": {}}

@app.get("/api/server_events")
async def get_server_events_api(period: str = Query('24h'), server_ip: str = Query(None), limit: int = Query(100)):
    try:
        period_hours = {'24h': 24, '7d': 168, '30d': 720}.get(period, 24)
        events = await get_server_events(period_hours, server_ip, limit)
        logger.info(f"Returning {len(events)} server events for period {period}")
        return {"events": events}
    except Exception as e:
        logger.error(f"Error fetching server events: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Failed to fetch server events")

@app.get("/api/uptime/summary")
async def get_uptime_summary(period: str = Query('24h')):
    try:
        period_hours = {'24h': 24, '7d': 168, '30d': 720}.get(period, 24)
        servers = await get_servers()
        statuses = (await get_server_status())['statuses']
        events = await get_server_events(period_hours, limit=100)
        logger.debug(f"Fetched {len(events)} events for uptime summary")
        
        summary = []
        for server in servers:
            ip = server[0]
            if not is_valid_ip(ip):
                continue
            server_events = [e for e in events if e['server_ip'] == ip]
            total_events = len([e for e in server_events if e['event_type'] in ['online', 'offline_start', 'offline_end']])
            
            logger.debug(f"Processing uptime for {ip}: status={statuses.get(ip, 'unknown')}, events={len(server_events)}")
            
            offline_periods = []
            offline_start = None
            for event in sorted(server_events, key=lambda x: x['event_time']):
                event_time = datetime.fromisoformat(event['event_time'].replace('Z', '+00:00'))
                logger.debug(f"Event for {ip}: type={event['event_type']}, time={event_time}")
                if event['event_type'] == 'offline_start':
                    offline_start = event_time
                elif event['event_type'] == 'offline_end' and offline_start:
                    offline_periods.append((offline_start, event_time))
                    offline_start = None
            
            current_status = statuses.get(ip, 'unknown')
            last_check = last_check_time.get(ip, datetime.utcnow())
            logger.debug(f"Last check for {ip}: {last_check}")
            
            if current_status in ['offline', 'unknown']:
                start_time = offline_start if offline_start else last_check
                if start_time > datetime.utcnow() - timedelta(hours=period_hours):
                    offline_periods.append((start_time, datetime.utcnow()))
                else:
                    offline_periods.append((datetime.utcnow() - timedelta(hours=period_hours), datetime.utcnow()))
            
            logger.debug(f"Offline periods for {ip}: {[(start.isoformat(), end.isoformat()) for start, end in offline_periods]}")
            
            total_offline_seconds = sum(
                max(0, min((end - start).total_seconds(), period_hours * 3600))
                for start, end in offline_periods
                if (end - start).total_seconds() > 0
            )
            
            period_seconds = period_hours * 3600
            uptime_seconds = max(0, period_seconds - total_offline_seconds)
            uptime_percentage = min(100.0, max(0.0, (uptime_seconds / period_seconds * 100) if period_seconds > 0 else 0.0))
            
            last_status_change = None
            for event in sorted(server_events, key=lambda x: x['event_time'], reverse=True):
                if event['event_type'] in ['online', 'offline_start', 'offline_end']:
                    last_status_change = event['event_time']
                    break
            if not last_status_change or current_status in ['offline', 'unknown']:
                last_status_change = last_check.isoformat()
            
            logger.debug(f"Uptime for {ip}: {uptime_percentage}%, offline_seconds={total_offline_seconds}, events={total_events}")
            
            summary.append({
                'server_ip': ip,
                'current_status': current_status,
                'uptime_percentage': round(uptime_percentage, 1),
                'total_events': total_events,
                'last_status_change': last_status_change
            })
        
        logger.info(f"Returning uptime summary for {len(summary)} servers")
        return {"data": summary}
    except Exception as e:
        logger.error(f"Error fetching uptime summary: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Failed to fetch uptime summary")

def show_toast(message, type):
    logger.info(f"Toast: {type} - {message}")
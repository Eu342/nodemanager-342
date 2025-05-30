import asyncio
import ipaddress
import logging
import os
import re
import traceback
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
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Store previous server statuses
previous_statuses = {}
# Store pending webhook retries with timestamp
pending_retries = {}
# Track offline start times
offline_starts = {}

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

async def remove_existing_json(ip):
    remote_path = f"{os.getenv('XRAY_CHECKER_JSON_PATH')}/{ip}.json"
    try:
        if os.getenv('XRAY_CHECKER_SSH_KEY') and os.getenv('XRAY_CHECKER_HOST') not in ['localhost', '127.0.0.1']:
            logger.info(f"Checking for existing JSON at {remote_path} on remote host {os.getenv('XRAY_CHECKER_HOST')}")
            async with asyncssh.connect(
                os.getenv('XRAY_CHECKER_HOST'),
                client_keys=[os.getenv('XRAY_CHECKER_SSH_KEY')],
                known_hosts=None,
                connect_timeout=15,
                login_timeout=15
            ) as conn:
                async with conn.start_sftp_client() as sftp:
                    try:
                        await sftp.stat(remote_path)
                        logger.info(f"Found existing JSON at {remote_path}, removing it")
                        await sftp.remove(remote_path)
                        logger.info(f"Removed existing JSON at {remote_path}")
                    except asyncssh.SFTPError:
                        logger.debug(f"No existing JSON found at {remote_path}")
        elif os.getenv('XRAY_CHECKER_HOST') in ['localhost', '127.0.0.1']:
            logger.info(f"Checking for existing JSON at {remote_path} locally")
            if os.path.exists(remote_path):
                logger.info(f"Found existing JSON at {remote_path}, removing it")
                os.remove(remote_path)
                logger.info(f"Removed existing JSON at {remote_path}")
            else:
                logger.debug(f"No existing JSON found at {remote_path}")
        else:
            logger.error("Invalid Xray Checker configuration: SSH key or host not set")
            raise ValueError("SSH key or valid host required for Xray Checker")
        return True
    except Exception as e:
        logger.error(f"Failed to remove existing JSON for {ip}: {str(e)}\n{traceback.format_exc()}")
        return False

async def restart_xray_checker():
    try:
        container_name = os.getenv('XRAY_CHECKER_CONTAINER_NAME', 'xraychecker-xray-checker')
        logger.info(f"Attempting to restart Xray Checker container: {container_name}")
        if os.getenv('XRAY_CHECKER_SSH_KEY') and os.getenv('XRAY_CHECKER_HOST') not in ['localhost', '127.0.0.1']:
            logger.info(f"Restarting Xray Checker on remote host {os.getenv('XRAY_CHECKER_HOST')}")
            async with asyncssh.connect(
                os.getenv('XRAY_CHECKER_HOST'),
                client_keys=[os.getenv('XRAY_CHECKER_SSH_KEY')],
                known_hosts=None,
                connect_timeout=15,
                login_timeout=15
            ) as conn:
                result = await conn.run(f'docker ps -a -q -f name={container_name}')
                if not result.stdout.strip():
                    logger.warning(f"Container {container_name} not found on {os.getenv('XRAY_CHECKER_HOST')}, skipping restart")
                    return True
                result = await conn.run(f'sudo docker restart {container_name}')
                if result.exit_status != 0:
                    logger.error(f"Docker restart failed: {result.stderr}")
                    raise Exception(f"Docker restart failed: {result.stderr}")
                else:
                    logger.info("Xray Checker restarted successfully")
        elif os.getenv('XRAY_CHECKER_HOST') in ['localhost', '127.0.0.1']:
            logger.info("Restarting Xray Checker locally")
            result = subprocess.run(['docker', 'ps', '-a', '-q', '-f', f'name={container_name}'], capture_output=True, text=True)
            if not result.stdout.strip():
                logger.warning(f"Container {container_name} not found locally, skipping restart")
                return True
            result = subprocess.run(['sudo', 'docker', 'restart', container_name], capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"Docker restart failed: {result.stderr}")
                raise Exception(f"Docker restart failed: {result.stderr}")
            else:
                logger.info("Xray Checker restarted successfully")
        else:
            logger.error("Invalid Xray Checker configuration: SSH key or host not set")
            raise ValueError("SSH key or valid host required for Xray Checker")
        return True
    except Exception as e:
        logger.error(f"Failed to restart Xray Checker: {str(e)}\n{traceback.format_exc()}")
        return False

async def copy_json_to_xray_checker(ip, json_data):
    local_path = f"/config/outbounds/{ip}.json"
    remote_path = f"{os.getenv('XRAY_CHECKER_JSON_PATH')}/{ip}.json"
    try:
        logger.debug(f"Starting JSON creation at {local_path} for IP {ip}")
        logger.debug(f"JSON data: {json.dumps(json_data, indent=2)}")
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "w") as f:
            json.dump(json_data, f, indent=2)
        logger.info(f"JSON created successfully at {local_path}")

        if not os.getenv('XRAY_CHECKER_JSON_PATH'):
            logger.error("XRAY_CHECKER_JSON_PATH not set in .env")
            raise ValueError("XRAY_CHECKER_JSON_PATH not set")

        if os.getenv('XRAY_CHECKER_SSH_KEY') and os.getenv('XRAY_CHECKER_HOST') not in ['localhost', '127.0.0.1']:
            logger.info(f"Copying JSON to remote {remote_path} via SFTP (host: {os.getenv('XRAY_CHECKER_HOST')})")
            async with asyncssh.connect(
                os.getenv('XRAY_CHECKER_HOST'),
                client_keys=[os.getenv('XRAY_CHECKER_SSH_KEY')],
                known_hosts=None,
                connect_timeout=15,
                login_timeout=15
            ) as conn:
                async with conn.start_sftp_client() as sftp:
                    try:
                        await sftp.stat(os.path.dirname(remote_path))
                        logger.debug(f"Remote path {os.path.dirname(remote_path)} exists")
                    except asyncssh.SFTPError:
                        logger.info(f"Remote path {os.path.dirname(remote_path)} does not exist, creating it")
                        await sftp.makedirs(os.path.dirname(remote_path))
                        logger.info(f"Created remote directory {os.path.dirname(remote_path)}")
                    await sftp.put(local_path, remote_path)
                    logger.info(f"JSON copied to {remote_path}")
        elif os.getenv('XRAY_CHECKER_HOST') in ['localhost', '127.0.0.1']:
            logger.info(f"Copying JSON to local {remote_path}")
            os.makedirs(os.path.dirname(remote_path), exist_ok=True)
            shutil.copy2(local_path, remote_path)
            logger.info(f"JSON copied to {remote_path}")
        else:
            logger.error("Invalid Xray Checker configuration: SSH key or host not set")
            raise ValueError("SSH key or valid host required for Xray Checker")
        return True
    except Exception as e:
        logger.error(f"Failed to copy JSON for {ip}: {str(e)}\n{traceback.format_exc()}")
        return False
    finally:
        if os.path.exists(local_path):
            logger.info(f"Removing temporary JSON at {local_path}")
            os.remove(local_path)

async def update_xray_checker_json(ip, inbound_tag, vless_key):
    try:
        json_data = create_outbound_json(ip, inbound_tag, vless_key)
        if not json_data:
            logger.error(f"create_outbound_json returned None for {ip}")
            raise ValueError("Failed to create outbound JSON")
        if not await copy_json_to_xray_checker(ip, json_data):
            raise ValueError(f"Failed to copy JSON for {ip}")
        if not await restart_xray_checker():
            logger.warning(f"Failed to restart Xray Checker for {ip}, but JSON copied")
        logger.info(f"JSON updated for {ip} with inbound_tag {inbound_tag}")
        return True
    except Exception as e:
        logger.error(f"Failed to update JSON for {ip}: {str(e)}\n{traceback.format_exc()}")
        return False

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
    global previous_statuses, pending_retries, offline_starts
    try:
        logger.debug("Checking server statuses in background")
        current_statuses = {}
        
        # Fetch known servers from database
        servers = await get_servers()
        valid_ips = {server[0] for server in servers}
        logger.debug(f"Valid server IPs from database: {valid_ips}")

        # Try fetching metrics from Xray Checker
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            try:
                async with session.get(f"{XRAY_CHECKER_URL}/metrics") as response:
                    logger.info(f"Xray Checker /metrics status: {response.status}")
                    if response.status != 200:
                        logger.error(f"Xray Checker returned status: {response.status}, reason: {response.reason}")
                    else:
                        metrics = await response.text()
                        logger.debug(f"Metrics response: {metrics[:500]}")
                        pattern = r'xray_proxy_status\{[^}]*address="([^:]+):\d+"[^}]*protocol="[^"]+"[^}]*\} (\d)'
                        for line in metrics.splitlines():
                            match = re.match(pattern, line)
                            if match:
                                ip, status = match.groups()
                                if ip in valid_ips and ip != 'n.unfence.nl':  # Explicitly ignore n.unfence.nl
                                    current_statuses[ip] = "online" if status == "1" else "offline"
                                    logger.debug(f"Parsed IP: {ip}, Status: {status}")
                                else:
                                    logger.warning(f"Ignoring IP from metrics: {ip}")
                            else:
                                logger.debug(f"No match for metric line: {line}")
            except Exception as e:
                logger.error(f"Failed to fetch Xray Checker metrics: {str(e)}\n{traceback.format_exc()}")

        # If no statuses from metrics, check servers from database
        if not current_statuses:
            logger.warning("No statuses parsed from metrics, falling back to database servers")
            for server in servers:
                ip = server[0]
                if ip != 'n.unfence.nl':  # Ignore n.unfence.nl
                    current_statuses[ip] = "offline"  # Default to offline if metrics unavailable
                    logger.debug(f"Added IP from database: {ip}, Status: offline")

        if not current_statuses:
            logger.error("No server statuses available from metrics or database")
            return

        logger.debug(f"Current statuses: {current_statuses}")
        logger.debug(f"Previous statuses: {previous_statuses}")

        nodemonitoring_host = os.getenv('NODEMONITORING_HOST')
        nodemonitoring_port = os.getenv('NODEMONITORING_PORT')
        
        if not nodemonitoring_host or not nodemonitoring_port:
            logger.error(f"NODEMONITORING_HOST or NODEMONITORING_PORT not set in .env: host={nodemonitoring_host}, port={nodemonitoring_port}")
            return

        webhook_url = f"http://{nodemonitoring_host}:{nodemonitoring_port}/api/kuma/alert"
        logger.info(f"Preparing to send webhook to: {webhook_url}")

        semaphore = asyncio.Semaphore(10)
        async def send_webhook(ip, payload):
            async with semaphore:
                try:
                    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                        async with session.post(webhook_url, json=payload) as resp:
                            response_text = await resp.text()
                            logger.debug(f"Webhook response for {ip}: status={resp.status}, response={response_text}")
                            if resp.status != 200:
                                logger.error(f"Failed to send webhook for {ip}: status={resp.status}, response={response_text}")
                                return False
                            logger.info(f"Webhook sent for {ip}: {payload}, response={response_text}")
                            return True
                except Exception as e:
                    logger.error(f"Error sending webhook for {ip}: {str(e)}\n{traceback.format_exc()}")
                    return False

        current_time = datetime.utcnow()
        tasks = []
        for ip, status in current_statuses.items():
            prev_status = previous_statuses.get(ip)
            if prev_status is None or status != prev_status:
                logger.info(f"Status change detected for {ip}: {prev_status} -> {status}")
                webhook_payload = {
                    "heartbeat": {"msg": "ok" if status == "online" else "fail"},
                    "monitor": {"description": ip}
                }
                tasks.append((ip, webhook_payload))

                # Log event with duration_seconds
                try:
                    if status == "offline":
                        await log_server_event(ip, "offline_start", duration_seconds=0)
                        offline_starts[ip] = current_time
                    elif status == "online" and ip in offline_starts:
                        duration = int((current_time - offline_starts[ip]).total_seconds())
                        await log_server_event(ip, "offline_end", duration_seconds=duration)
                        await log_server_event(ip, "online", duration_seconds=0)
                        del offline_starts[ip]
                    elif status == "online":
                        await log_server_event(ip, "online", duration_seconds=0)
                    logger.info(f"Logged event for {ip}: {status}")
                except Exception as e:
                    logger.error(f"Failed to log event for {ip}: {str(e)}\n{traceback.format_exc()}")

        for ip, (payload, last_attempt) in list(pending_retries.items()):
            if current_time - last_attempt >= timedelta(minutes=5):
                logger.info(f"Scheduling retry webhook for {ip}")
                tasks.append((ip, payload))
                del pending_retries[ip]

        if tasks:
            results = await asyncio.gather(*(send_webhook(ip, payload) for ip, payload in tasks), return_exceptions=True)
            for (ip, payload), result in zip(tasks, results):
                if isinstance(result, Exception) or result is False:
                    pending_retries[ip] = (payload, current_time)
                    logger.error(f"Webhook for {ip} failed, scheduled retry in 5 minutes")
                else:
                    logger.info(f"Webhook for {ip} succeeded")

        previous_statuses.clear()
        previous_statuses.update(current_statuses)
        logger.debug(f"Updated previous statuses: {current_statuses}")
    except Exception as e:
        logger.error(f"Error in background status check: {str(e)}\n{traceback.format_exc()}")

scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await init_db()
        logger.info("Database initialized successfully")
        scheduler.add_job(update_vless_keys_from_subscription, 'interval', hours=int(os.getenv('SUBSCRIPTION_REFRESH_HOURS', 1)))
        scheduler.add_job(check_server_statuses, 'interval', minutes=1)
        scheduler.start()
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}\n{traceback.format_exc()}")
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
        logger.error(f"Error serving index.html: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/nodemanager/add", response_class=HTMLResponse)
async def add_server_page():
    try:
        with open("static/add_server.html") as f:
            logger.info("Serving add_server.html")
            return HTMLResponse(content=f.read())
    except Exception as e:
        logger.error(f"Error serving add_server.html: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/nodemanager/setup", response_class=HTMLResponse)
async def setup_server_page():
    try:
        with open("static/setup_server.html") as f:
            logger.info("Serving setup_server.html")
            return HTMLResponse(content=f.read())
    except Exception as e:
        logger.error(f"Error serving setup_server.html: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/nodemanager/list", response_class=HTMLResponse)
async def server_list_page():
    try:
        with open("static/server_list.html") as f:
            logger.info("Serving server_list.html")
            return HTMLResponse(content=f.read())
    except Exception as e:
        logger.error(f"Error serving server_list.html: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/nodemanager/uptime", response_class=HTMLResponse)
async def uptime_page():
    try:
        with open("static/uptime.html") as f:
            logger.info("Serving uptime.html")
            return HTMLResponse(content=f.read())
    except Exception as e:
        logger.error(f"Error serving uptime.html: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/nodemanager/settings/subscription", response_class=HTMLResponse)
async def settings_subscription_page():
    try:
        with open("static/settings_subscription.html") as f:
            logger.info("Serving settings_subscription.html")
            return HTMLResponse(content=f.read())
    except Exception as e:
        logger.error(f"Error serving settings_subscription.html: {e}\n{traceback.format_exc()}")
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
        logger.error(f"Failed to fetch vless keys: {e}\n{traceback.format_exc()}")
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
        logger.error(f"Failed to fetch scripts: {e}\n{traceback.format_exc()}")
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
            ipaddress.ip_address(ip)
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
                if not await check_ip_in_xray_checker(ip):
                    if not await update_xray_checker_json(ip, request.inbound_tag, key['vless_key']):
                        return {"ip": ip, "success": False, "message": "Failed to update Xray Checker JSON"}
                success, message = await deploy_script(ip, script_name)
                logger.debug(f"deploy_script result for {ip}: success={success}, message={message}")
                if not isinstance(success, bool):
                    logger.error(f"Invalid success type from deploy_script: {success} for {ip}")
                    return {"ip": ip, "success": False, "message": f"Invalid deploy_script response: {success}"}
                if success:
                    add_success = await add_server(ip, request.inbound_tag)
                    logger.debug(f"add_server result for {ip}: {add_success}")
                    if isinstance(add_success, str):
                        logger.warning(f"add_server returned string '{add_success}' for {ip}, converting to bool")
                        add_success = add_success.lower() == 'true'
                    if not isinstance(add_success, bool):
                        logger.error(f"Invalid add_server response: {add_success} for {ip}")
                        return {"ip": ip, "success": False, "message": f"Invalid add_server response: {add_success}"}
                    if add_success:
                        logger.info(f"Server {ip} added successfully")
                        return {"ip": ip, "success": True, "message": "Server added successfully"}
                    else:
                        logger.error(f"Failed to save server {ip} to database")
                        return {"ip": ip, "success": False, "message": "Failed to save server to database"}
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
            ipaddress.ip_address(ip)
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
            if not await check_ip_in_xray_checker(ip):
                if not await update_xray_checker_json(ip, request.inbound_tag, key['vless_key']):
                    results.append({"ip": ip, "success": False, "message": "Failed to update Xray Checker JSON"})
                    continue
            add_success = await add_server(ip, request.inbound_tag)
            logger.debug(f"add_server result for {ip}: {add_success}")
            if isinstance(add_success, str):
                logger.warning(f"add_server returned string '{add_success}' for {ip}, converting to bool")
                add_success = add_success.lower() == 'true'
            if not isinstance(add_success, bool):
                logger.error(f"Invalid add_server response: {add_success} for {ip}")
                results.append({"ip": ip, "success": False, "message": f"Invalid add_server response: {add_success}"})
                continue
            if add_success:
                logger.info(f"Server {ip} added successfully")
                results.append({"ip": ip, "success": True, "message": "Server added successfully"})
            else:
                logger.error(f"Failed to save server {ip} to database")
                results.append({"ip": ip, "success": False, "message": "Failed to save server to database"})
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
            } for s in servers if s[0] != 'n.unfence.nl'  # Exclude n.unfence.nl
        ]
        logger.info(f"Returning {len(formatted_servers)} servers")
        return {"servers": formatted_servers}
    except Exception as e:
        logger.error(f"Failed to fetch servers: {e}\n{traceback.format_exc()}")
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
                    return await deploy_script(ip, request.script_name)
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
        server = next((s for s in s if s[0] == request.old_ip), None)
        if not server:
            logger.error(f"Server {request.old_ip} not found")
            raise HTTPException(status_code=404, detail="Server not found")
        key = await get_vless_key(request.new_inbound_tag)
        if not key:
            logger.error(f"Inbound tag {request.new_inbound_tag} not found")
            raise HTTPException(status_code=400, detail=f"Inbound tag {request.new_inbound_tag} not found")
        if request.old_ip != request.new_ip or server[1] != request.new_inbound_tag:
            if not await remove_existing_json(request.old_ip):
                logger.error(f"Failed to remove JSON for {request.old_ip}")
                raise HTTPException(status_code=500, detail="Failed to remove old JSON")
        if not await update_xray_checker_json(request.new_ip, request.new_inbound_tag, key['vless_key']):
            logger.error(f"Failed to update JSON for {request.new_ip}")
            raise HTTPException(status_code=500, detail="Failed to update Xray Checker JSON")
        if not await delete_server(request.old_ip):
            logger.error(f"Failed to delete {request.old_ip} from database")
            raise HTTPException(status_code=500, detail="Failed to update database")
        if not await add_server(request.new_ip, request.new_inbound_tag):
            logger.error(f"Failed to add {request.new_ip} to database")
            raise HTTPException(status_code=500, detail="Failed to update database")
        logger.info(f"Server updated: {request.old_ip} -> {request.new_ip}, inbound_tag: {request.new_inbound_tag}")
        return {"success": True, "message": "Server updated"}
    except Exception as e:
        logger.error(f"Error editing {request.old_ip}: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

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
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            async with session.get(f"{XRAY_CHECKER_URL}/metrics") as response:
                logger.info(f"Xray Checker /metrics status: {response.status}")
                if response.status != 200:
                    logger.error(f"Xray Checker returned status: {response.status}, reason: {response.reason}")
                    return {"statuses": {}}
                metrics = await response.text()
                logger.debug(f"Xray Checker metrics response: {metrics[:500]}")
        
        statuses = {}
        pattern = r'xray_proxy_status\{[^}]*address="([^:]+):\d+"[^}]*protocol="[^"]+"[^}]*\} (\d)'
        for line in metrics.splitlines():
            logger.debug(f"Parsing metric line: {line}")
            match = re.match(pattern, line)
            if match:
                ip, status = match.groups()
                if ip != 'n.unfence.nl':  # Ignore n.unfence.nl
                    statuses[ip] = "online" if status == "1" else "offline"
                    logger.debug(f"Matched IP: {ip}, Status: {status}")
            else:
                logger.debug(f"No match for line: {line}")
        
        logger.info(f"Parsed statuses: {statuses}")
        return {"statuses": statuses}
    except Exception as e:
        logger.error(f"Error fetching Xray Checker metrics: {str(e)}\n{traceback.format_exc()}")
        return {"statuses": {}}

@app.get("/api/server_events")
async def get_server_events_api(period: str = Query('24h'), server_ip: str = Query(None), limit: int = Query(50)):
    try:
        period_hours = {'24h': 24, '7d': 168, '30d': 720}.get(period, 24)
        events = await get_server_events(period_hours, server_ip, limit)
        logger.info(f"Returning {len(events)} server events for period {period}")
        formatted_events = [
            {
                'id': e['id'],
                'server_ip': e['server_ip'],
                'event_type': e['event_type'],
                'event_time': e['event_time'],
                'duration_seconds': e['duration_seconds'] if e['duration_seconds'] is not None else 0
            } for e in events
        ]
        return {"events": formatted_events}
    except Exception as e:
        logger.error(f"Error fetching server events: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Failed to fetch server events")

@app.get("/api/uptime/summary")
async def get_uptime_summary(period: str = Query('24h')):
    try:
        period_hours = {'24h': 24, '7d': 168, '30d': 720}.get(period, 24)
        servers = await get_servers()
        statuses = (await get_server_status())['statuses']
        events = await get_server_events(period_hours, limit=50)
        
        summary = []
        for server in servers:
            ip = server[0]
            if ip == 'n.unfence.nl':  # Exclude n.unfence.nl
                continue
            server_events = [e for e in events if e['server_ip'] == ip]
            total_checks = len(server_events)
            online_checks = len([e for e in server_events if e['event_type'] == 'online'])
            uptime_percentage = (online_checks / total_checks * 100) if total_checks > 0 else 100.0
            
            last_event = server_events[0] if server_events else None
            last_check = last_event['event_time'] if last_event else datetime.utcnow().isoformat()
            
            summary.append({
                'server_ip': ip,
                'current_status': statuses.get(ip, 'offline'),
                'uptime_percentage': round(uptime_percentage, 1),
                'total_checks': total_checks,
                'last_check': last_check
            })
        
        logger.info(f"Returning uptime summary for {len(summary)} servers")
        return {"data": summary}
    except Exception as e:
        logger.error(f"Error fetching uptime summary: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Failed to fetch uptime summary")

async def check_ip_in_xray_checker(ip):
    host = 'localhost' if os.getenv('XRAY_CHECKER_HOST') in ['localhost', '127.0.0.1'] else os.getenv('XRAY_CHECKER_HOST')
    url = f"http://{host}:{os.getenv('XRAY_CHECKER_PORT')}/metrics"
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    logger.error(f"Xray Checker status: {response.status}")
                    return False
                metrics = await response.text()
                pattern = rf'xray_proxy_status{{[^}}]*address="{ip}:\d+"[^}}]*}} \d'
                return bool(re.search(pattern, metrics))
    except Exception as e:
        logger.error(f"Error checking IP {ip}: {str(e)}\n{traceback.format_exc()}")
        return False

def show_toast(message, type):
    logger.info(f"Toast: {type} - {message}")
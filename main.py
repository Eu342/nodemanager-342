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
from db import init_db, get_vless_keys, get_vless_key, update_vless_key, add_server, get_servers, delete_server
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

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

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

def get_script_name(inbound_tag: str) -> str:
    safe_tag = re.sub(r'[\U0001F1E6-\U0001F1FF]+', '', inbound_tag).strip()
    script_name = safe_tag.lower().replace(" ", "_") + ".sh"
    logger.info(f"Generated script name: {script_name} for inbound_tag: {inbound_tag}")
    return script_name

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
            async with asyncssh.connect(os.getenv('XRAY_CHECKER_HOST'), client_keys=[os.getenv('XRAY_CHECKER_SSH_KEY')], known_hosts=None) as conn:
                async with conn.start_sftp_client() as sftp:
                    try:
                        await sftp.stat(os.path.dirname(remote_path))
                        logger.debug(f"Remote path {os.path.dirname(remote_path)} exists")
                    except asyncssh.SFTPError:
                        logger.info(f"Remote path {os.path.dirname(remote_path)} does not exist, creating it")
                        try:
                            await sftp.makedirs(os.path.dirname(remote_path))
                            logger.info(f"Created remote directory {os.path.dirname(remote_path)}")
                        except Exception as e:
                            logger.error(f"Failed to create remote directory {os.path.dirname(remote_path)}: {str(e)}\n{traceback.format_exc()}")
                            raise ValueError(f"Failed to create remote directory {os.path.dirname(remote_path)}: {str(e)}")
                    await sftp.put(local_path, remote_path)
                    logger.info(f"JSON copied to {remote_path}")
                try:
                    result = await conn.run('sudo docker restart xraychecker-xray-checker')
                    if result.exit_status != 0:
                        logger.error(f"Docker restart failed: {result.stderr}")
                        show_toast("Ошибка перезапуска Xray Checker", "error")
                    else:
                        logger.info("Xray Checker restarted successfully")
                except asyncssh.ProcessError as e:
                    logger.error(f"Failed to restart Xray Checker container: {str(e)}\n{traceback.format_exc()}")
                    show_toast("Ошибка перезапуска Xray Checker", "error")
        elif os.getenv('XRAY_CHECKER_HOST') in ['localhost', '127.0.0.1']:
            logger.info(f"Copying JSON to local {remote_path}")
            if not os.path.exists(os.path.dirname(remote_path)):
                logger.info(f"Local path {os.path.dirname(remote_path)} does not exist, creating it")
                os.makedirs(os.path.dirname(remote_path), exist_ok=True)
                logger.info(f"Created local directory {os.path.dirname(remote_path)}")
            shutil.copy2(local_path, remote_path)
            logger.info(f"JSON copied to {remote_path}")
            try:
                result = subprocess.run(['sudo', 'docker', 'restart', 'xraychecker-xray-checker'], capture_output=True, text=True)
                if result.returncode != 0:
                    logger.error(f"Docker restart failed: {result.stderr}")
                    show_toast("Ошибка перезапуска Xray Checker", "error")
                else:
                    logger.info("Xray Checker restarted successfully")
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to restart Xray Checker container: {str(e)}\n{traceback.format_exc()}")
                show_toast("Ошибка перезапуска Xray Checker", "error")
        else:
            logger.error("Invalid Xray Checker configuration: SSH key or host not set")
            raise ValueError("SSH key or valid host required for Xray Checker")
    except Exception as e:
        logger.error(f"Failed to copy JSON for {ip}: {str(e)}\n{traceback.format_exc()}")
        show_toast(f"Ошибка копирования JSON для {ip}: {str(e)}", "error")
        raise
    finally:
        if os.path.exists(local_path):
            logger.info(f"Removing temporary JSON at {local_path}")
            os.remove(local_path)

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

scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await init_db()
        logger.info("Database initialized successfully")
        scheduler.add_job(update_vless_keys_from_subscription, 'interval', hours=int(os.getenv('SUBSCRIPTION_REFRESH_HOURS', 1)))
        scheduler.start()
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}\n{traceback.format_exc()}")
        raise
    yield

app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

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
    semaphore = asyncio.Semaphore(20)
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
                    try:
                        logger.debug(f"Calling create_outbound_json for {ip} with vless_key: {key['vless_key'][:50]}...")
                        json_data = create_outbound_json(ip, request.inbound_tag, key['vless_key'])
                        if json_data is None:
                            logger.error(f"create_outbound_json returned None for {ip}")
                            return {"ip": ip, "success": False, "message": "Failed to create outbound JSON"}
                        logger.debug(f"JSON data for {ip}: {json.dumps(json_data, indent=2)}")
                        await copy_json_to_xray_checker(ip, json_data)
                    except ValueError as e:
                        logger.warning(f"Invalid key for {request.inbound_tag}: {str(e)}\n{traceback.format_exc()}")
                        return {"ip": ip, "success": False, "message": f"Invalid key for {request.inbound_tag}: {str(e)}"}
                    except Exception as e:
                        logger.error(f"Unexpected error in create_outbound_json for {ip}: {str(e)}\n{traceback.format_exc()}")
                        return {"ip": ip, "success": False, "message": f"Unexpected error: {str(e)}"}
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
                try:
                    logger.debug(f"Calling create_outbound_json for {ip} with vless_key: {key['vless_key'][:50]}...")
                    json_data = create_outbound_json(ip, request.inbound_tag, key['vless_key'])
                    if json_data is None:
                        logger.error(f"create_outbound_json returned None for {ip}")
                        results.append({"ip": ip, "success": False, "message": "Failed to create outbound JSON"})
                        continue
                    logger.debug(f"JSON data for {ip}: {json.dumps(json_data, indent=2)}")
                    await copy_json_to_xray_checker(ip, json_data)
                except ValueError as e:
                    logger.warning(f"Invalid key for {request.inbound_tag}: {str(e)}\n{traceback.format_exc()}")
                    results.append({"ip": ip, "success": False, "message": f"Invalid key for {request.inbound_tag}: {str(e)}"})
                    continue
                except Exception as e:
                    logger.error(f"Unexpected error in create_outbound_json for {ip}: {str(e)}\n{traceback.format_exc()}")
                    results.append({"ip": ip, "success": False, "message": f"Unexpected error: {str(e)}"})
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
            } for s in servers
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
    logger.info(f"Server {ip} deleted successfully")
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
        logger.error(f"Exception in deploy_script for {ip}: {e}\n{traceback.format_exc()}")
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
    semaphore = asyncio.Semaphore(20)
    async def run_deploy_script(ip):
        async with semaphore:
            logger.info(f"Attempting to reboot server {ip} with script {script_name}")
            try:
                success, message = await deploy_script(ip, script_name)
                return {"ip": ip, "success": success, "message": message}
            except Exception as e:
                logger.error(f"Exception in deploy_script for {ip}: {e}\n{traceback.format_exc()}")
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
    semaphore = asyncio.Semaphore(20)
    async def run_deploy_script(ip):
        async with semaphore:
            logger.info(f"Attempting to run script {request.script_name} on {ip}")
            try:
                success, message = await deploy_script(ip, script_name)
                return {"ip": ip, "success": success, "message": message}
            except Exception as e:
                logger.error(f"Exception in deploy_script for {ip}: {e}\n{traceback.format_exc()}")
                return {"ip": ip, "success": False, "message": str(e)}
    tasks = [run_deploy_script(ip) for ip in request.ips]
    results = await asyncio.gather(*tasks)
    response = {"results": results}
    logger.info(f"Script execution completed: {response}")
    return response

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
                statuses[ip] = "online" if status == "1" else "offline"
                logger.debug(f"Matched IP: {ip}, Status: {status}")
            else:
                logger.debug(f"No match for line: {line}")
        
        logger.info(f"Parsed statuses: {statuses}")
        return {"statuses": statuses}
    except Exception as e:
        logger.error(f"Error fetching Xray Checker metrics: {str(e)}\n{traceback.format_exc()}")
        return {"statuses": {}}

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
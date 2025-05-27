import asyncio
import ipaddress
import logging
import os
import re
from contextlib import asynccontextmanager
from typing import List
from fastapi import FastAPI, Form, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from db import get_remote_inbounds, add_server, get_servers, init_db, delete_server
from ssh_utils import deploy_script, check_server_availability
from config import Config
import aiohttp
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ServerForm(BaseModel):
    ip: str
    inbound: str

class RebootRequest(BaseModel):
    ips: List[str]

class RunScriptsRequest(BaseModel):
    ips: List[str]
    script_name: str

class AddServerRequest(BaseModel):
    ips: List[str]
    inbound: str

def get_script_name(inbound_tag: str) -> str:
    safe_tag = re.sub(r'[^a-zA-Z0-9\s]', '', inbound_tag)
    script_name = safe_tag.lower().replace(" ", "_") + ".sh"
    return script_name

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
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
        logger.error(f"Error serving index.html: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/nodemanager/add", response_class=HTMLResponse)
async def add_server_page():
    try:
        with open("static/add_server.html") as f:
            logger.info("Serving add_server.html")
            return HTMLResponse(content=f.read())
    except Exception as e:
        logger.error(f"Error serving add_server.html: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/nodemanager/setup", response_class=HTMLResponse)
async def setup_server_page():
    try:
        with open("static/setup_server.html") as f:
            logger.info("Serving setup_server.html")
            return HTMLResponse(content=f.read())
    except Exception as e:
        logger.error(f"Error serving setup_server.html: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/nodemanager/list", response_class=HTMLResponse)
async def server_list_page():
    try:
        with open("static/server_list.html") as f:
            logger.info("Serving server_list.html")
            return HTMLResponse(content=f.read())
    except Exception as e:
        logger.error(f"Error serving server_list.html: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/inbounds")
async def get_inbounds():
    try:
        inbounds = await get_remote_inbounds()
        if not inbounds:
            logger.warning("No inbounds returned from database")
            return {"inbounds": []}
        logger.info(f"Returning {len(inbounds)} inbounds")
        return {"inbounds": inbounds}
    except Exception as e:
        logger.error(f"Failed to fetch inbounds: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch inbounds")

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
        logger.error(f"Failed to fetch scripts: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch scripts")

@app.post("/api/add_server")
async def add_server_api(ips: List[str] = Form(...), inbound: str = Form(...)):
    try:
        for ip in ips:
            ipaddress.ip_address(ip)
    except ValueError:
        logger.error(f"Invalid IP address in {ips}")
        raise HTTPException(status_code=400, detail="Invalid IP address")
    script_name = get_script_name(inbound)
    logger.info(f"Generated script {script_name} for inbound: {inbound}")
    results = []
    semaphore = asyncio.Semaphore(20)
    async def deploy_and_add(ip):
        async with semaphore:
            logger.info(f"Attempting to deploy script {script_name} on {ip}")
            try:
                success, message = await deploy_script(ip, script_name)
                if success and await add_server(ip, inbound):
                    logger.info(f"Server {ip} added successfully")
                    return {"ip": ip, "success": True, "message": "Server added successfully"}
                logger.error(f"Failed to save server {ip}: {message}")
                return {"ip": ip, "success": False, "message": message}
            except Exception as e:
                logger.error(f"Error deploying script on {ip}: {e}")
                return {"ip": ip, "success": False, "message": str(e)}
    tasks = [deploy_and_add(ip) for ip in ips]
    results = await asyncio.gather(*tasks)
    response = {"results": results}
    logger.info(f"Batch server setup completed: {response}")
    return response

@app.post("/api/add_server_manual")
async def add_server_manual_api(
    request: AddServerRequest = None,
    ips: List[str] = Form(None),
    inbound: str = Form(None)
):
    if request:
        ips, inbound = request.ips, request.inbound
    elif not (ips and inbound):
        logger.error("Missing required fields in add_server_manual request")
        raise HTTPException(status_code=422, detail="Missing required fields")
    try:
        for ip in ips:
            ipaddress.ip_address(ip)
    except ValueError:
        logger.error(f"Invalid IP address in {ips}")
        raise HTTPException(status_code=400, detail="Invalid IP address")
    results = []
    for ip in ips:
        logger.info(f"Attempting to add server {ip} to database")
        try:
            if await add_server(ip, inbound):
                logger.info(f"Server {ip} added successfully")
                results.append({"ip": ip, "success": True, "message": "Server added successfully"})
            else:
                logger.error(f"Failed to save server {ip} to database")
                results.append({"ip": ip, "success": False, "message": "Failed to save server to database"})
        except Exception as e:
            logger.error(f"Error adding server {ip}: {e}")
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
                'inbound': s[1],
                'install_date': s[2].isoformat() if s[2] else None
            } for s in servers
        ]
        logger.info(f"Returning {len(formatted_servers)} servers")
        return {"servers": formatted_servers}
    except Exception as e:
        logger.error(f"Failed to fetch servers: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch servers")

@app.delete("/api/delete_server")
async def delete_server_api(ip: str = Query(...)):
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        logger.error(f"Invalid IP address for deletion: {ip}")
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
        logger.error(f"Invalid IP address for reboot: {ip}")
        raise HTTPException(status_code=400, detail="Invalid IP address")
    script_name = "reboot.sh"
    try:
        success, message = await deploy_script(ip, script_name)
        if not success:
            logger.error(f"Failed to reboot server {ip}: {message}")
            raise HTTPException(status_code=500, detail=f"Failed to reboot server: {message}")
    except Exception as e:
        logger.error(f"Exception in deploy_script for {ip}: {e}")
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
            logger.error(f"Invalid IP address: {ip}")
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
                logger.error(f"Exception in deploy_script for {ip}: {e}")
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
            logger.error(f"Invalid IP address: {ip}")
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
                success, message = await deploy_script(ip, request.script_name)
                return {"ip": ip, "success": success, "message": message}
            except Exception as e:
                logger.error(f"Exception in deploy_script for {ip}: {e}")
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
        raise HTTPException(status_code=400, detail="Invalid IP address")
    is_available = await check_server_availability(ip)
    return {"ip": ip, "available": is_available}

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
        logger.error(f"Error fetching Xray Checker metrics: {str(e)}")
        return {"statuses": {}}
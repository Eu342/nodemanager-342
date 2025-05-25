from fastapi import FastAPI, Form, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import ipaddress
import asyncio
from db import get_remote_inbounds, add_server, get_servers, init_db, delete_server
from ssh_utils import deploy_script
from contextlib import asynccontextmanager
import re
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Инициализация при старте приложения."""
    try:
        await init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise
    yield

app = FastAPI(lifespan=lifespan)

# Монтируем папку static
app.mount("/static", StaticFiles(directory="static"), name="static")

class ServerForm(BaseModel):
    ip: str
    inbound: str

def get_script_name(inbound_tag: str) -> str:
    """
    Генерирует имя .sh скрипта из inbound тега.
    Например: "USA VLESS TCP" → "usa_vless_tcp.sh", "RU VLESS TCP 3" → "ru_vless_tcp_3.sh"
    """
    safe_tag = re.sub(r'[^a-zA-Z0-9\s]', '', inbound_tag)
    script_name = safe_tag.lower().replace(" ", "_") + ".sh"
    return script_name

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

@app.post("/api/add_server")
async def add_server_api(ip: str = Form(...), inbound: str = Form(...)):
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        logger.error(f"Invalid IP address: {ip}")
        raise HTTPException(status_code=400, detail="Invalid IP address")

    script_name = get_script_name(inbound)
    logger.info(f"Generated script name: {script_name} for inbound: {inbound}")

    loop = asyncio.get_event_loop()
    success, message = await loop.run_in_executor(None, deploy_script, ip, script_name)
    if not success:
        logger.error(f"Failed to deploy script {script_name} on {ip}: {message}")
        raise HTTPException(status_code=500, detail=f"Failed to deploy script: {message}")

    if not await add_server(ip, inbound):
        logger.error(f"Failed to save server {ip} with inbound {inbound} to database")
        raise HTTPException(status_code=500, detail="Failed to save server to database")

    logger.info(f"Server {ip} added successfully with inbound {inbound}")
    return {"message": "Server added successfully"}

@app.post("/api/add_server_manual")
async def add_server_manual_api(ip: str = Form(...), inbound: str = Form(...)):
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        logger.error(f"Invalid IP address: {ip}")
        raise HTTPException(status_code=400, detail="Invalid IP address")

    if not await add_server(ip, inbound):
        logger.error(f"Failed to save server {ip} with inbound {inbound} to database")
        raise HTTPException(status_code=500, detail="Failed to save server to database")

    logger.info(f"Server {ip} added manually with inbound {inbound}")
    return {"message": "Server added successfully"}

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
    try:
        ipaddress.ip_address(ip)
        logger.info(f"Valid IP address for reboot: {ip}")
    except ValueError:
        logger.error(f"Invalid IP address for reboot: {ip}")
        raise HTTPException(status_code=400, detail="Invalid IP address")

    script_name = "reboot.sh"
    logger.info(f"Attempting to reboot server {ip} with script {script_name}")

    loop = asyncio.get_event_loop()
    try:
        success, message = await loop.run_in_executor(None, deploy_script, ip, script_name)
        logger.info(f"deploy_script result for {ip}: success={success}, message={message}")
        if not success:
            logger.error(f"Failed to reboot server {ip}: {message}")
            raise HTTPException(status_code=500, detail=f"Failed to reboot server: {message}")
    except Exception as e:
        logger.error(f"Exception in deploy_script for {ip}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to reboot server: {str(e)}")

    logger.info(f"Server {ip} rebooted successfully")
    return {"message": "Server rebooted successfully"}
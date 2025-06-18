import asyncssh
import socket
import os
import logging
from config import Config
import asyncio

logger = logging.getLogger(__name__)

async def check_server_availability(ip, port=22, timeout=5):
    """Проверяет доступность сервера по IP и порту асинхронно."""
    try:
        # Создаем корутину для проверки соединения
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port),
            timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
        logger.info(f"Server {ip} is reachable on port {port}")
        return True, "Server is reachable"
    except asyncio.TimeoutError:
        logger.warning(f"Connection to {ip}:{port} timed out")
        return False, "Connection timed out"
    except Exception as e:
        logger.error(f"Error checking server {ip}: {str(e)}")
        return False, f"Error checking server: {str(e)}"

async def deploy_script(ip: str, script_name: str, timeout: int = 120):
    """Asynchronously deploy and execute a bash script on a remote server via SSH with timeout."""
    # Check server availability
    is_available, message = await check_server_availability(ip)
    if not is_available:
        logger.error(f"Failed to deploy script on {ip}: {message}")
        return False, message

    # Check if local script exists
    script_path = os.path.join(Config.SCRIPTS_PATH, script_name)
    if not os.path.exists(script_path):
        logger.error(f"Script '{script_name}' not found in {Config.SCRIPTS_PATH}")
        return False, f"Script '{script_name}' not found"

    try:
        # Set connection timeout
        conn_options = asyncssh.SSHClientConnectionOptions(
            known_hosts=None,
            connect_timeout=30,
            login_timeout=30
        )
        
        async with asyncssh.connect(
            ip,
            username=Config.SSH_USER,
            client_keys=[Config.SSH_KEY_PATH],
            options=conn_options
        ) as conn:
            # Upload script via SFTP
            remote_path = f"/tmp/{script_name}"
            async with conn.start_sftp_client() as sftp:
                await sftp.put(script_path, remote_path)
            
            # Make script executable
            await conn.run(f"chmod +x {remote_path}", check=True)
            
            # Execute script with timeout
            try:
                result = await asyncio.wait_for(
                    conn.run(f"bash {remote_path}", check=False),
                    timeout=timeout
                )
                
                stdout_output = result.stdout.strip()
                stderr_output = result.stderr.strip()
                exit_code = result.exit_status

                if exit_code != 0:
                    error_message = f"Script execution failed with exit code {exit_code}\n"
                    error_message += f"STDERR: {stderr_output}\n"
                    error_message += f"STDOUT: {stdout_output}"
                    logger.error(f"Failed to execute {script_name} on {ip}: {error_message}")
                    return False, error_message

                logger.info(f"Successfully executed {script_name} on {ip}: {stdout_output}")
                return True, "Script executed successfully"
                
            except asyncio.TimeoutError:
                logger.error(f"Script execution timed out after {timeout} seconds on {ip}")
                return False, f"Script execution timed out after {timeout} seconds"
                
    except asyncssh.DisconnectError as e:
        logger.error(f"SSH connection failed to {ip}: {e}")
        return False, f"Connection failed: {str(e)}"
    except asyncssh.ProcessError as e:
        logger.error(f"Command failed on {ip}: {e}")
        return False, f"Command failed: {str(e)}"
    except asyncssh.SFTPError as e:
        logger.error(f"SFTP error on {ip}: {e}")
        return False, f"SFTP error: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected error on {ip}: {e}")
        return False, f"Unexpected error: {str(e)}"
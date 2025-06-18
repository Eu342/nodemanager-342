<<<<<<< HEAD
import asyncssh
import socket
import os
import logging
from config import Config

logger = logging.getLogger(__name__)

=======
import paramiko
import os
import socket
from config import Config

>>>>>>> 26a4cfa9a7433dd8ae3df4677490dce261a4058a
def check_server_availability(ip, port=22, timeout=5):
    """Проверяет доступность сервера по IP и порту."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, port))
        sock.close()
        if result == 0:
<<<<<<< HEAD
            logger.info(f"Server {ip} is reachable on port {port}")
            return True, "Server is reachable"
        else:
            logger.warning(f"Server {ip} is not reachable on port {port}")
            return False, "Server is not reachable"
    except socket.gaierror:
        logger.error(f"Invalid IP address or hostname: {ip}")
        return False, "Invalid IP address or hostname"
    except Exception as e:
        logger.error(f"Error checking server {ip}: {str(e)}")
        return False, f"Error checking server: {str(e)}"

async def deploy_script(ip: str, script_name: str):
    """Asynchronously deploy and execute a bash script on a remote server via SSH."""
    # Check server availability
    is_available, message = check_server_availability(ip)
    if not is_available:
        logger.error(f"Failed to deploy script on {ip}: {message}")
        return False, message

    # Check if local script exists
    script_path = os.path.join(Config.SCRIPTS_PATH, script_name)
    if not os.path.exists(script_path):
        logger.error(f"Script '{script_name}' not found in {Config.SCRIPTS_PATH}")
        return False, f"Script '{script_name}' not found in {Config.SCRIPTS_PATH}"

    try:
        async with asyncssh.connect(
            ip,
            username=Config.SSH_USER,
            client_keys=[Config.SSH_KEY_PATH],
            known_hosts=None  # Disable host key checking
        ) as conn:
            # Upload script via SFTP
            remote_path = f"/tmp/{script_name}"
            async with conn.start_sftp_client() as sftp:
                await sftp.put(script_path, remote_path)
            
            # Make script executable
            await conn.run(f"chmod +x {remote_path}", check=True)
            
            # Execute script
            result = await conn.run(f"bash {remote_path}", check=False)
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
=======
            return True, "Server is reachable"
        else:
            return False, "Server is not reachable"
    except socket.gaierror:
        return False, "Invalid IP address or hostname"
    except Exception as e:
        return False, f"Error checking server: {str(e)}"

def deploy_script(ip, script_name):
    """Разворачивает Bash-скрипт на сервере."""
    # Проверка доступности сервера
    is_available, message = check_server_availability(ip)
    if not is_available:
        return False, message

    script_path = os.path.join(Config.SCRIPTS_PATH, script_name)
    if not os.path.exists(script_path):
        return False, f"Script '{script_name}' not found in {Config.SCRIPTS_PATH}"

    try:
        # Инициализация SSH-клиента
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(ip, username=Config.SSH_USER, key_filename=Config.SSH_KEY_PATH)

        # Загрузка скрипта
        sftp = ssh.open_sftp()
        remote_path = f"/tmp/{script_name}"
        sftp.put(script_path, remote_path)
        sftp.close()

        # Выполнение скрипта
        ssh.exec_command(f"chmod +x {remote_path}")
        stdin, stdout, stderr = ssh.exec_command(f"bash {remote_path}")
        
        # Чтение вывода и кода возврата
        stdout_output = stdout.read().decode()
        stderr_output = stderr.read().decode()
        exit_code = stdout.channel.recv_exit_status()

        ssh.close()

        if exit_code != 0:
            error_message = f"Script execution failed with exit code {exit_code}\n"
            error_message += f"STDERR: {stderr_output}\n"
            error_message += f"STDOUT: {stdout_output}"
            return False, error_message

        return True, "Script executed successfully"
    except paramiko.AuthenticationException:
        return False, "Authentication failed. Check SSH key or user credentials."
    except paramiko.SSHException as e:
        return False, f"SSH error: {str(e)}"
    except Exception as e:
>>>>>>> 26a4cfa9a7433dd8ae3df4677490dce261a4058a
        return False, f"Unexpected error: {str(e)}"
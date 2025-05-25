import paramiko
import os
import socket
from config import Config

def check_server_availability(ip, port=22, timeout=5):
    """Проверяет доступность сервера по IP и порту."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, port))
        sock.close()
        if result == 0:
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
        return False, f"Unexpected error: {str(e)}"
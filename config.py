from dotenv import load_dotenv
import os

# Загружаем переменные из .env
load_dotenv()

class Config:
    # Путь к SSH-ключу
    SSH_KEY_PATH = os.getenv("SSH_KEY_PATH")
    # Папка с Bash-скриптами
    SCRIPTS_PATH = os.getenv("SCRIPTS_PATH")
    # Данные для локальной БД
    LOCAL_DB = {
        "dbname": os.getenv("LOCAL_DB_DBNAME"),
        "user": os.getenv("LOCAL_DB_USER"),
        "password": os.getenv("LOCAL_DB_PASSWORD"),
        "host": os.getenv("LOCAL_DB_HOST"),
        "port": os.getenv("LOCAL_DB_PORT")
    }
    # Данные для удаленной БД
    REMOTE_DB = {
        "dbname": os.getenv("REMOTE_DB_DBNAME"),
        "user": os.getenv("REMOTE_DB_USER"),
        "password": os.getenv("REMOTE_DB_PASSWORD"),
        "host": os.getenv("REMOTE_DB_HOST"),
        "port": os.getenv("REMOTE_DB_PORT")
    }
    # SSH-пользователь
    SSH_USER = os.getenv("SSH_USER")
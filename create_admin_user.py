#!/usr/bin/env python3
"""
Скрипт для создания администратора NodeManager
"""

import asyncio
import asyncpg
import bcrypt
import os
from dotenv import load_dotenv
import getpass

load_dotenv()

async def create_admin():
    # Используем правильные переменные окружения
    DATABASE_URL = os.getenv('DATABASE_URL')
    
    if DATABASE_URL:
        # Если есть DATABASE_URL, используем его
        pool = await asyncpg.create_pool(DATABASE_URL)
    else:
        # Иначе используем отдельные параметры
        pool = await asyncpg.create_pool(
            database=os.getenv('DB_NAME', 'nodemanager'),
            user=os.getenv('DB_USER', 'postgres'),
            password=os.getenv('DB_PASSWORD', ''),
            host=os.getenv('DB_HOST', 'localhost'),
            port=int(os.getenv('DB_PORT', '5432'))
        )
    
    try:
        async with pool.acquire() as conn:
            # Проверяем существование таблицы users
            table_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'users'
                )
            """)
            
            if not table_exists:
                print("❌ Таблица users не существует. Создаём таблицу...")
                
                # Создаем таблицу users
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS users (
                        id SERIAL PRIMARY KEY,
                        username VARCHAR(50) UNIQUE NOT NULL,
                        password_hash VARCHAR(100) NOT NULL,
                        is_active BOOLEAN DEFAULT true,
                        is_admin BOOLEAN DEFAULT false,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_login TIMESTAMP,
                        failed_attempts INTEGER DEFAULT 0,
                        locked_until TIMESTAMP
                    )
                ''')
                
                # Создаем индекс
                await conn.execute('CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)')
                
                print("✅ Таблица users создана")
            
            print("🔑 Создание администратора NodeManager\n")
            
            # Запрашиваем данные
            username = input("Имя пользователя (по умолчанию 'admin'): ").strip()
            if not username:
                username = 'admin'
            
            # Проверяем существование пользователя
            user_exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM users WHERE username = $1)",
                username
            )
            
            if user_exists:
                update = input(f"⚠️  Пользователь '{username}' уже существует. Обновить пароль? (y/n): ")
                if update.lower() != 'y':
                    print("Отменено.")
                    return
            
            # Запрашиваем пароль
            while True:
                password = getpass.getpass("Пароль (минимум 8 символов): ")
                if len(password) < 8:
                    print("❌ Пароль должен быть не менее 8 символов!")
                    continue
                    
                password_confirm = getpass.getpass("Подтвердите пароль: ")
                if password != password_confirm:
                    print("❌ Пароли не совпадают!")
                    continue
                    
                break
            
            # Хешируем пароль
            password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            
            # Создаем или обновляем пользователя
            if user_exists:
                await conn.execute(
                    """
                    UPDATE users 
                    SET password_hash = $1, is_admin = true, 
                        failed_attempts = 0, locked_until = NULL
                    WHERE username = $2
                    """,
                    password_hash, username
                )
                print(f"✅ Пароль для администратора '{username}' обновлен!")
            else:
                await conn.execute(
                    """
                    INSERT INTO users (username, password_hash, is_admin, is_active)
                    VALUES ($1, $2, true, true)
                    """,
                    username, password_hash
                )
                print(f"✅ Администратор '{username}' создан!")
            
            print(f"\n📌 Теперь вы можете войти:")
            print(f"   URL: http://localhost:8999/login")
            print(f"   Логин: {username}")
            print(f"   Пароль: [введенный вами пароль]")
            
    finally:
        await pool.close()

if __name__ == "__main__":
    asyncio.run(create_admin())
#!/bin/bash

# Прерывать выполнение при любой ошибке
set -e

# Проверяем, что скрипт выполняется с правами root
if [ "$(id -u)" -ne 0 ]; then
    echo "Ошибка: Этот скрипт должен выполняться с правами root (sudo)"
    exit 1
fi

# Устанавливаем git, если он не установлен
if ! command -v git &> /dev/null; then
    echo "Установка git..."
    apt-get update
    apt-get install -y git
    apt-get install -y curl
fi

# Проверяем и устанавливаем Docker, если он не установлен
if ! command -v docker &> /dev/null; then
    echo "Установка Docker..."
    curl -sSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
fi

# Проверяем, поддерживается ли docker compose
if ! docker compose version &> /dev/null; then
    echo "Ошибка: Docker Compose не найден или не поддерживается. Убедитесь, что установлен Docker с поддержкой compose."
    exit 1
fi

# Клонируем репозиторий Remnawave node
echo "Клонирование репозитория Remnawave node..."
git clone https://github.com/remnawave/node.git

# Переходим в папку с репозиторием
cd node

# Выводим текущую директорию и содержимое для отладки
echo "Текущая директория: $(pwd)"
echo "Содержимое директории node:"
ls -la
echo "Поиск всех файлов в папке node и подпапках:"
find . -type f

# Проверяем наличие файла .env.sample и переименовываем его в .env
if [ -f .env.sample ]; then
    echo "Переименование .env.sample в .env..."
    mv .env.sample .env
else
    echo "Предупреждение: файл .env.sample не найден в репозитории"
    exit 1
fi

# Заменяем строки в файле .env
if [ -f .env ]; then
    echo "Обновление файла .env: установка нового значения SSL_CERT..."
    sed -i "s|SSL_CERT=.*|SSL_CERT=\"eyJub2RlQ2VydFBlbSI6Ii0tLS0tQkVHSU4gQ0VSVElGSUNBVEUtLS0tLVxuTUlJQmZqQ0NBU1dnQXdJQkFnSUhBWFI1TWtJeVZUQUtCZ2dxaGtqT1BRUURBakFvTVNZd0pBWURWUVFERXgxVFxuYURSTU9FeG9lbkJtTjFZMVJtTXpPREJIU2xGdFkyYzRVa0ZsVWpBZUZ3MHlOVEExTWpJeE5qUTNNRE5hRncweVxuT0RBMU1qSXhOalEzTUROYU1Db3hLREFtQmdOVkJBTVRIMkUxYmpWQ1MweHRVMVZOVFd0UU9FRTJhbXBUUzJVNVxuUTBKdFZFTXhPSFV3V1RBVEJnY3Foa2pPUFFJQkJnZ3Foa2pPUFFNQkJ3TkNBQVNQZllDckZ6TkhvUzBzSkR6c1xuKzM2bkF1aXRiL2IrWVVaajVpZmFESDBrVURzTVpMWm5vL0dqRUtZb2F0UFdXYWdFNWlUV3czaW1oRTJRT2MvNFxuUkpoZG96Z3dOakFNQmdOVkhSTUJBZjhFQWpBQU1BNEdBMVVkRHdFQi93UUVBd0lGb0RBV0JnTlZIU1VCQWY4RVxuRERBS0JnZ3JCZ0VGQlFjREFUQUtCZ2dxaGtqT1BRUURBZ05IQURCRUFpQVJ4LzZZaWJYVVcvRnd2eURiZytrVlxuMXhWVzhJY3BaTEI2aDdkWk1oQVY3d0lnUmtwM1F4OXNpT0l5VUVHVXZzLzRmY2RrQnRzZDNUNHRNL3g0MGVITFxuN3o0PVxuLS0tLS1FTkQgQ0VSVElGSUNBVEUtLS0tLSIsIm5vZGVLZXlQZW0iOiItLS0tLUJFR0lOIFBSSVZBVEUgS0VZLS0tLS1cbk1JR0hBZ0VBTUJNR0J5cUdTTTQ5QWdFR0NDcUdTTTQ5QXdFSEJHMHdhd0lCQVFRZ1pBWGgrTFZ4SUltejdNVHlcbmNiaXZTZEN5ejRsZjZDQ3cvaStHM2kxNlczQ2hSQU5DQUFTUGZZQ3JGek5Ib1Mwc0pEenMrMzZuQXVpdGIvYitcbllVWmo1aWZhREgwa1VEc01aTFpuby9HakVLWW9hdFBXV2FnRTVpVFd3M2ltaEUyUU9jLzRSSmhkXG4tLS0tLUVORCBQUklWQVRFIEtFWS0tLS0tIiwiY2FDZXJ0UGVtIjoiLS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0tXG5NSUlCWWpDQ0FRaWdBd0lCQWdJQkFUQUtCZ2dxaGtqT1BRUURBakFvTVNZd0pBWURWUVFERXgxVGFEUk1PRXhvXG5lbkJtTjFZMVJtTXpPREJIU2xGdFkyYzRVa0ZsVWpBZUZ3MHlOVEExTWpJeE5qSXlNREphRncwek5UQTFNakl4XG5Oakl5TURKYU1DZ3hKakFrQmdOVkJBTVRIVk5vTkV3NFRHaDZjR1kzVmpWR1l6TTRNRWRLVVcxalp6aFNRV1ZTXG5NRmt3RXdZSEtvWkl6ajBDQVFZSUtvWkl6ajBEQVFjRFFnQUVyV2hmay8rRFBSOGt0OGk2U2lrcm0xMUFYOTJEXG5YNGdCN2hnbkl3Q0hpdXBMYWJZNHFWVmNFcFByeW5xVDJsMVlEc053SmhJQWNOa1h1VDRUbUtOVy9xTWpNQ0V3XG5Ed1lEVlIwVEFRSC9CQVV3QXdFQi96QU9CZ05WSFE4QkFmOEVCQU1DQW9Rd0NnWUlLb1pJemowRUF3SURTQUF3XG5SUUlnRVVoWkFxajBjZ3Uxc0dLNFhKY2ZEZFIzTngzeGMvWThsVUJoT2dLaUI0Y0NJUURCR3BIckRraFRTamhpXG5qU1RVWWo3ZzFyMy9KVFNobmNvQ3ozZTFseVhudXc9PVxuLS0tLS1FTkQgQ0VSVElGSUNBVEUtLS0tLSIsImp3dFB1YmxpY0tleSI6Ii0tLS0tQkVHSU4gUFVCTElDIEtFWS0tLS0tXG5NSUlCSWpBTkJna3Foa2lHOXcwQkFRRUZBQU9DQVE4QU1JSUJDZ0tDQVFFQXMrSEZERXlNS3UxZGQrMXh3NTJVXG5yRHNkT3NMZ0hpYmdrditaWUJrUEx1YjNyUmh1cU1PNXFhNFlvcjZOVklCbnpTbjZEMHlHazVzR1p3WlJJZE1UXG5Zcm1NTENWYUdpTkFTNE1DOUx1QW0rS2hJSHlXY3dFZDdqSWNRZk5ZQ0t4MWJGNXdOK2hTOVZLRlRtclE1Y3gwXG5VdlJvWGtMU08vVkJBbloxdGE4c3YwdDI1SkUwR3hGQ2ZFWHU0QmZTdWplVEViMWNvS3lSdnVSZWZsbDdBY0cyXG5tUlYzS21qa3FDS3luWWNKUjdDd1c5QXVCWDhiOFJ4ZDB3RzgxdFZMcUtGd3lTOE1qbkJRYjFHV3laalRYYmhvXG5qQnpwaVBtWDVoeEF3SE5zcFh2NVNNam9QVEpObUh3Zyt5cUJnY3B0bTdQaDBOSlZaRFZoTVNVSktabXVDaTE0XG5Hd0lEQVFBQlxuLS0tLS1FTkQgUFVCTElDIEtFWS0tLS0tXG4ifQ==\"|" .env
    echo "Обновление файла .env: установка APP_PORT=3447..."
    sed -i "s/APP_PORT=3000/APP_PORT=3447/" .env
else
    echo "Ошибка: файл .env не найден"
    exit 1
fi

# Устанавливаем nftables, если он не установлен
echo "Установка nftables..."
apt-get update
apt-get install -y nftables

# Создаем конфигурационный файл nftables
echo "Создание конфигурации /etc/nftables.conf..."
cat << EOF > /etc/nftables.conf
#!/usr/sbin/nft -f

table inet filter {
  chain input {
    type filter hook input priority 0; policy accept;
    # Разрешить локальный трафик
    iif lo accept
    # Разрешить доступ к портам 62050 и 62051 только для IP 212.34.130.149
    tcp dport { 4713 } ip saddr 5.35.34.66 accept
    tcp dport { 4713 } drop

    # Разрешить доступ к порту 7891 локально
    tcp dport 7891 accept

    # Запретить доступ к порту 7891 извнx
    tcp dport 7891 drop

    # Разрешить доступ к порту 443
    tcp dport 443 accept
    udp dport 443 accept
  }
  chain forward {
    type filter hook forward priority 0; policy accept;
  }
  chain output {
    type filter hook output priority 0; policy accept;
  }
}
# Перенаправление с порта 443 на 7891
table inet nat {
  chain prerouting {
    type nat hook prerouting priority 0; policy accept;
    tcp dport 443 redirect to :7891
  }
}

EOF

# Устанавливаем правильные права доступа
chmod 0644 /etc/nftables.conf
chown root:root /etc/nftables.conf

# Включаем и перезапускаем службу nftables
echo "Запуск и активация службы nftables..."
systemctl enable nftables
systemctl restart nftables

# Применяем правила nftables
echo "Применение правил nftables..."
nft -f /etc/nftables.conf
if [ $? -eq 0 ]; then
    echo "Правила nftables успешно применены"
else
    echo "Ошибка при применении правил nftables"
    exit 1
fi



############################################################
############################################################ 

# Указываем директорию поиска
SEARCH_DIR="/root/node"

# Проверяем доступ к директории
if [ ! -r "$SEARCH_DIR" ]; then
    echo "Ошибка: нет доступа к директории $SEARCH_DIR"
    exit 1
fi

# Проверяем наличие docker compose
if ! command -v docker compose >/dev/null 2>&1; then
    echo "Ошибка: команда 'docker compose' не найдена"
    exit 1
fi

echo "Поиск файла docker-compose.yml или docker-compose-prod.yml в $SEARCH_DIR..."
COMPOSE_FILE=$(find "$SEARCH_DIR" -type f \( -name "docker-compose.yml" -o -name "docker-compose-prod.yml" \) -print -quit)

if [ -n "$COMPOSE_FILE" ]; then
    echo "Найден файл: $COMPOSE_FILE"
    echo "Запуск Docker Compose..."
    docker compose -f "$COMPOSE_FILE" up -d
    if [ $? -eq 0 ]; then
        echo "Docker Compose успешно запущен"
    else
        echo "Ошибка при запуске Docker Compose"
        exit 1
    fi
else
    echo "Ошибка: файл docker-compose.yml или docker-compose-prod.yml не найден в $SEARCH_DIR или её подпапках"
    echo "Содержимое директории $SEARCH_DIR (первые 10 файлов):"
    find "$SEARCH_DIR" -type f | head -n 10
    exit 1
fi

############################################################

echo "Установка и настройка успешно завершены!"
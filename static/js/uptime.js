const SCRIPT_VERSION = '2025-06-03-v16';
let currentPeriod = '24h';
let serversData = [];
let eventsData = [];
let currentFilter = 'all';
let searchQuery = '';
let eventLimit = 20; // Default event limit

function waitForElement(id, maxAttempts = 100, delay = 200) {
    return new Promise((resolve, reject) => {
        let attempts = 0;
        const check = () => {
            const element = document.getElementById(id);
            if (element) {
                console.log(`Found ${id} after ${attempts} attempts`);
                resolve(element);
            } else if (attempts >= maxAttempts) {
                console.error(`${id} not found after ${maxAttempts} attempts`);
                reject(new Error(`${id} not found`));
            } else {
                attempts++;
                setTimeout(check, delay);
            }
        };
        check();
    });
}

async function fetchWithRetry(url, retries = 3, delay = 1000) {
    for (let i = 0; i < retries; i++) {
        try {
            console.log(`Fetching ${url}, attempt ${i + 1}`);
            const response = await fetch(url, { 
                cache: 'no-store',
                headers: { 'Accept': 'application/json' },
                mode: 'cors'
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            const data = await response.json();
            console.log(`Fetched ${url} successfully, data:`, data);
            return data;
        } catch (err) {
            console.error(`Fetch failed for ${url}:`, err);
            if (i < retries - 1) await new Promise(resolve => setTimeout(resolve, delay));
            else throw err;
        }
    }
}

document.addEventListener('DOMContentLoaded', async () => {
    console.log(`uptime.js v${SCRIPT_VERSION} loaded at ${new Date().toISOString()}`);
    try {
        loadTheme();
        await loadData();
        setupEventListeners();
    } catch (err) {
        console.error('Init failed:', err);
        showToast('Ошибка загрузки страницы: ' + err.message, 'error');
    }
});

function setupEventListeners() {
    console.log('Setting up event listeners');
    const periodButtons = document.querySelectorAll('.period-button');
    periodButtons.forEach(button => {
        button.addEventListener('click', () => {
            currentPeriod = button.dataset.period;
            periodButtons.forEach(btn => btn.classList.remove('active'));
            button.classList.add('active');
            loadData();
        });
    });
    const refreshButton = document.getElementById('refreshButton');
    if (refreshButton) {
        refreshButton.addEventListener('click', () => {
            const originalHTML = refreshButton.innerHTML;
            refreshButton.innerHTML = `<svg class="nav-item-icon" style="width: 16px; height: 16px; animation: spin 1s linear infinite;" viewBox="0 0 24 24" fill="none" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg> Обновление...`;
            setTimeout(() => {
                refreshButton.innerHTML = originalHTML;
                loadData();
            }, 1500);
        });
    }
    const themeButton = document.getElementById('themeButton');
    if (themeButton) themeButton.addEventListener('click', toggleTheme);

    const serverSearch = document.getElementById('serverSearch');
    if (serverSearch) {
        serverSearch.addEventListener('input', (e) => {
            searchQuery = e.target.value.toLowerCase();
            renderServersGrid();
        });
    }

    const filterButtons = document.querySelectorAll('.filter-button');
    filterButtons.forEach(button => {
        button.addEventListener('click', () => {
            currentFilter = button.dataset.filter;
            filterButtons.forEach(btn => btn.classList.remove('active'));
            button.classList.add('active');
            renderServersGrid();
        });
    });

    const eventLimitButtons = document.querySelectorAll('.event-limit-button');
    eventLimitButtons.forEach(button => {
        button.addEventListener('click', () => {
            eventLimit = parseInt(button.dataset.limit);
            eventLimitButtons.forEach(btn => btn.classList.remove('active'));
            button.classList.add('active');
            renderEvents();
        });
    });
}

async function loadData() {
    try {
        console.log('Starting data load for period:', currentPeriod);
        showToast('Загрузка данных...', 'info');

        console.log('Loading /api/uptime/summary');
        const summaryData = await fetchWithRetry(`/api/uptime/summary?period=${currentPeriod}`);
        serversData = summaryData.data || [];
        console.log('Summary data loaded:', serversData);

        console.log('Loading /api/server_events');
        const eventsDataResponse = await fetchWithRetry(`/api/server_events?period=${currentPeriod}&limit=100`);
        eventsData = eventsDataResponse.events || [];
        console.log('Events data loaded:', eventsData);

        console.log('Loading /api/servers for inbound tags');
        const serversResponse = await fetchWithRetry('/api/servers');
        const serverTags = serversResponse.servers.reduce((acc, server) => {
            acc[server.ip] = server.inbound_tag;
            return acc;
        }, {});
        serversData = serversData.map(server => ({
            ...server,
            inbound_tag: serverTags[server.server_ip] || 'N/A'
        }));
        console.log('Servers with tags:', serversData);

        await updateStats();
        await renderServersGrid();
        await renderEvents();
        showToast('Данные загружены', 'success');
    } catch (error) {
        console.error('Load data error:', error, error.stack);
        showToast('Ошибка загрузки: ' + error.message, 'error');
        const serversGrid = document.getElementById('serversGrid');
        if (serversGrid) serversGrid.innerHTML = '<div style="text-align: center; padding: 40px;">Ошибка загрузки серверов: ' + error.message + '</div>';
        else console.error('serversGrid not found');
        const eventsList = document.getElementById('eventsList');
        if (eventsList) eventsList.innerHTML = '<div style="text-align: center; padding: 20px;">Ошибка загрузки событий: ' + error.message + '</div>';
        else console.error('eventsList not found');
    }
}

async function updateStats() {
    try {
        console.log('Updating stats');
        const [totalServers, onlineServers, averageUptime, allCount, activeCount, problematicCount] = await Promise.all([
            waitForElement('totalServers'),
            waitForElement('onlineServers'),
            waitForElement('averageUptime'),
            waitForElement('allCount').catch(() => null),
            waitForElement('activeCount').catch(() => null),
            waitForElement('problematicCount').catch(() => null)
        ]);
        const total = serversData.length;
        const online = serversData.filter(s => s.current_status === 'online').length;
        const problematic = serversData.filter(s => s.current_status === 'offline' || s.current_status === 'unknown').length;
        const average = total > 0 ? serversData.reduce((sum, s) => sum + s.uptime_percentage, 0) / total : 0;
        totalServers.innerHTML = total;
        onlineServers.innerHTML = online;
        averageUptime.innerHTML = average.toFixed(1) + '%';
        if (allCount) allCount.innerHTML = total;
        if (activeCount) activeCount.innerHTML = online;
        if (problematicCount) problematicCount.innerHTML = problematic;
        console.log('Stats updated:', { total, online, problematic, average });
    } catch (err) {
        console.error('Stats render error:', err);
    }
}

function filterServers(servers) {
    return servers.filter(server => {
        const matchesSearch = !searchQuery || 
            server.server_ip.toLowerCase().includes(searchQuery) ||
            (server.inbound_tag && server.inbound_tag.toLowerCase().includes(searchQuery));
        const matchesFilter = currentFilter === 'all' ||
            (currentFilter === 'active' && server.current_status === 'online') ||
            (currentFilter === 'problematic' && (server.current_status === 'offline' || server.current_status === 'unknown'));
        return matchesSearch && matchesFilter;
    });
}

async function renderServersGrid() {
    try {
        console.log('Rendering servers grid');
        const container = await waitForElement('serversGrid');
        const filteredServers = filterServers(serversData);
        if (!filteredServers.length) {
            container.innerHTML = '<div style="text-align: center; padding: 40px; grid-column: 1 / -1;">Нет серверов по заданным критериям</div>';
            return;
        }
        container.innerHTML = filteredServers.map(server => {
            const uptimeClass = server.uptime_percentage >= 95 ? '' : server.uptime_percentage >= 80 ? 'medium' : 'low';
            const statusClass = server.current_status === 'unknown' ? 'unknown' : server.current_status;
            return `
                <div class="server-uptime-card ${statusClass}">
                    <div class="server-header">
                        <div class="server-info">
                            <div class="server-status-indicator ${statusClass}"></div>
                            <div class="server-ip">${server.server_ip}</div>
                        </div>
                        <div class="uptime-percentage ${uptimeClass}">${server.uptime_percentage.toFixed(1)}%</div>
                    </div>
                    <div class="server-timeline" id="timeline-${server.server_ip.replace(/\./g, '-')}">
                        ${renderTimeline(server.server_ip)}
                    </div>
                    <div class="server-meta">
                        <span>Событий: ${server.total_events}</span>
                        <span>Статус изменён: ${formatDate(server.last_status_change)}</span>
                    </div>
                </div>
            `;
        }).join('');
    } catch (err) {
        console.error('Servers grid render error:', err);
    }
}

function renderTimeline(serverIp) {
    console.log('Rendering timeline for:', serverIp);
    const serverEvents = eventsData.filter(e => e.server_ip === serverIp).reverse();
    if (!serverEvents.length) return '<div style="padding: 10px; text-align: center;">Нет данных</div>';
    const segments = 24;
    const periodHours = { '24h': 24, '7d': 168, '30d': 720 }[currentPeriod];
    const interval = periodHours * 3600 / segments;
    let html = '';
    let lastStatus = 'online';
    for (let i = 0; i < segments; i++) {
        const segmentStart = new Date(Date.now() - (segments - i) * interval * 1000);
        const segmentEnd = new Date(segmentStart.getTime() + interval * 1000);
        let status = 'online';
        for (const event of serverEvents) {
            const eventTime = new Date(event.event_time);
            if (eventTime < segmentStart) {
                lastStatus = event.event_type === 'offline_start' ? 'offline' : 'online';
            } else if (eventTime >= segmentStart && eventTime < segmentEnd) {
                if (event.event_type === 'offline_start') {
                    status = 'offline';
                    break;
                } else if (event.event_type === 'offline_end' || event.event_type === 'online') {
                    status = 'online';
                    break;
                }
            }
        }
        if (status === 'online' && lastStatus === 'offline') status = 'offline';
        html += `<div class="server-timeline-bar ${status}" style="left: ${i * (100 / segments)}%; width: calc((100% / 24) * 0.7);"></div>`;
        lastStatus = status;
    }
    return html;
}

async function renderEvents() {
    try {
        console.log('Rendering events, count:', eventsData.length, 'limit:', eventLimit);
        const container = await waitForElement('eventsList');
        if (!eventsData.length) {
            container.innerHTML = '<div style="text-align: center; padding: 20px;">Нет событий</div>';
            return;
        }
        container.innerHTML = eventsData.slice(0, eventLimit).map(event => {
            const isSuccess = event.event_type === 'online' || event.event_type === 'offline_end';
            const iconClass = isSuccess ? 'success' : 'danger';
            const actionText = event.event_type === 'online' ? `Сервер ${event.server_ip} подключен` :
                              event.event_type === 'offline_start' ? `Сервер ${event.server_ip} оффлайн` :
                              `Сервер ${event.server_ip} вернулся онлайн`;
            const duration = (event.duration_seconds && event.duration_seconds > 0) ? ` (длительность: ${formatDuration(event.duration_seconds)})` : '';
            return `
                <div class="activity-item" style="opacity: 0;">
                    <div class="activity-icon ${iconClass}">
                        <svg style="width: 16px; height: 16px;" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                            ${isSuccess ? 
                                '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>' :
                                '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.664-.833-2.464 0L4.348 16.5c-.77.833.192 2.5 1.732 2.5z"/>'
                            }
                        </svg>
                    </div>
                    <div class="activity-text">
                        <div class="activity-action">${actionText}${duration}</div>
                        <div class="activity-time">${formatDate(event.event_time)}</div>
                    </div>
                </div>
            `;
        }).join('');
        setTimeout(() => {
            const items = document.querySelectorAll('.activity-item');
            items.forEach((item, index) => {
                setTimeout(() => {
                    item.style.opacity = '1';
                    item.style.transform = 'translateY(0)';
                }, index * 100);
            });
        }, 100);
    } catch (err) {
        console.error('Events render error:', err);
        const eventsList = document.getElementById('eventsList');
        if (eventsList) eventsList.innerHTML = '<div style="text-align: center; padding: 20px;">Ошибка рендеринга событий: ' + err.message + '</div>';
    }
}

function formatDate(dateString) {
    try {
        const date = new Date(dateString);
        const now = new Date();
        const diff = now - date;
        if (diff < 60000) return 'Только что';
        if (diff < 3600000) return `${Math.floor(diff / 60000)} мин назад`;
        if (diff < 86400000) return `${Math.floor(diff / 3600000)} ч назад`;
        return date.toLocaleString('ru-RU', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    } catch (e) {
        return 'Неверная дата';
    }
}

function formatDuration(seconds) {
    if (!seconds || seconds <= 0) return '';
    if (seconds < 60) return `${seconds} сек`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)} мин`;
    return `${Math.floor(seconds / 3600)} ч ${Math.floor((seconds % 3600) / 60)} мин`;
}

function loadTheme() {
    console.log('Loading theme');
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme === 'dark') document.documentElement.setAttribute('data-theme', 'dark');
}

function toggleTheme() {
    console.log('Toggling theme');
    const isDark = document.documentElement.hasAttribute('data-theme');
    if (isDark) {
        document.documentElement.removeAttribute('data-theme');
        localStorage.removeItem('theme');
        showToast('Включена светлая тема', 'info');
    } else {
        document.documentElement.setAttribute('data-theme', 'dark');
        localStorage.setItem('theme', 'dark');
        showToast('Включена тёмная тема', 'info');
    }
}

function showToast(message, type = 'info') {
    console.log('Showing toast:', message, type);
    const container = document.getElementById('toastContainer');
    if (!container) {
        console.error('toastContainer not found');
        return;
    }
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `
        <svg class="toast-icon" viewBox="0 0 24 24">
            ${type === 'success' ? 
                '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>' :
                type === 'error' ?
                '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>' :
                '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>'
            }
        </svg>
        <div class="toast-message">${message}</div>
    `;
    container.appendChild(toast);
    setTimeout(() => toast.classList.add('show'), 100);
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => container.removeChild(toast), 300);
    }, 4000);
}
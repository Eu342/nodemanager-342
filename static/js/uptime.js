const SCRIPT_VERSION = '2025-06-04-v9-fixes';
let currentPeriod = '24h';
let serversData = [];
let eventsData = [];
let currentFilter = 'all';
let searchQuery = '';
let eventLimit = 20;

function waitForElement(selector, maxAttempts = 50, delay = 100) {
    return new Promise((resolve, reject) => {
        let attempts = 0;
        const check = () => {
            const element = document.querySelector(selector);
            if (element) {
                resolve(element);
            } else if (attempts >= maxAttempts) {
                console.error(`Element ${selector} not found after ${maxAttempts} attempts`);
                reject(new Error(`Element ${selector} not found`));
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
            const response = await fetch(url, {
                cache: 'no-store',
                headers: { 'Accept': 'application/json' },
                mode: 'cors'
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.statusText} for ${url}`);
            await new Promise(resolve => setTimeout(resolve, 100 + Math.random() * 200));
            const data = await response.json();
            return data;
        } catch (err) {
            console.error(`Fetch failed for ${url} (attempt ${i+1}):`, err);
            if (i < retries - 1) await new Promise(resolve => setTimeout(resolve, delay * (i+1)));
            else throw err;
        }
    }
}

function generateMockServerMetrics(ip) {
    const seed = ip.split('.').reduce((acc, val) => acc + parseInt(val), 0) + Math.floor(Date.now() / 300000);
    const cpu = (seed % 50) + 10 + Math.floor(Math.random() * 25);
    const mem = (seed % 60) + 20 + Math.floor(Math.random() * 15);
    const resp = (seed % 80) + 5 + Math.floor(Math.random() * 50);
    return {
        cpuUsagePercent: cpu,
        memoryUsagePercent: mem,
        responseTimeMs: resp,
    };
}


document.addEventListener('DOMContentLoaded', async () => {
    console.log(`NodeManager Uptime v${SCRIPT_VERSION} loaded at ${new Date().toISOString()}`);
    loadTheme();
    setupEventListeners();
    await loadData();

    setTimeout(() => {
        showToast('Мониторинг аптайма активен 📊', 'success');
    }, 1000);
});

function setupEventListeners() {
    console.log('Setting up event listeners');

    const periodButtons = document.querySelectorAll('.period-button');
    periodButtons.forEach(button => {
        button.addEventListener('click', () => {
            currentPeriod = button.dataset.period;
            document.querySelectorAll('.period-button').forEach(btn => btn.classList.remove('active'));
            document.querySelectorAll(`.period-button[data-period="${currentPeriod}"]`).forEach(btn => btn.classList.add('active'));
            loadData();
        });
    });

    const refreshButton = document.getElementById('refreshButton');
    if (refreshButton) {
        refreshButton.addEventListener('click', refreshData);
    }

    const themeButton = document.getElementById('themeButton');
    if (themeButton) {
        themeButton.addEventListener('click', toggleTheme);
    }

    const serverSearchInput = document.getElementById('serverSearchInput');
    if (serverSearchInput) {
        serverSearchInput.addEventListener('input', (e) => {
            searchQuery = e.target.value.toLowerCase();
            renderFilteredServers();
        });
    }

    const filterTabs = document.querySelectorAll('.filter-tab[data-filter]');
    filterTabs.forEach(tab => {
        tab.addEventListener('click', (e) => {
            currentFilter = e.currentTarget.dataset.filter;
            filterTabs.forEach(t => t.classList.remove('active'));
            e.currentTarget.classList.add('active');
            renderFilteredServers();
        });
    });

    const eventLimitButtons = document.querySelectorAll('.event-limit-button');
    eventLimitButtons.forEach(button => {
        button.addEventListener('click', () => {
            eventLimit = parseInt(button.dataset.limit);
            eventLimitButtons.forEach(btn => btn.classList.remove('active'));
            button.classList.add('active');
            renderActivityFeed();
        });
    });

    const mobileMenuToggle = document.getElementById('mobileMenuToggle');
    if (mobileMenuToggle) {
        mobileMenuToggle.addEventListener('click', toggleMobileMenu);
    }
    const mobileOverlay = document.getElementById('mobileOverlay');
    if (mobileOverlay) {
        mobileOverlay.addEventListener('click', closeMobileMenu);
    }
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeMobileMenu();
        }
    });
}


async function loadData() {
    try {
        showToast('Обновление данных...', 'info', 2000);
        console.log('Starting data load for period:', currentPeriod);

        // Adjusted ID array for overview stats
        ['totalServers', 'onlineServers', 'averageUptime'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.innerHTML = `<span class="loading"><span class="spinner"></span></span>`;
        });
        const sGrid = document.getElementById('serversGrid');
        if (sGrid) sGrid.innerHTML = `<div class="loading" style="grid-column: 1 / -1;"><span class="spinner"></span> Загрузка серверов...</div>`;
        const actList = document.getElementById('activityList');
        if (actList) actList.innerHTML = `<div class="loading"><span class="spinner"></span> Загрузка событий...</div>`;

        const summaryData = await fetchWithRetry(`/api/uptime/summary?period=${currentPeriod}`);
        let rawServersData = summaryData.data || [];

        const eventsDataResponse = await fetchWithRetry(`/api/server_events?period=${currentPeriod}&limit=250`); // Fetch more for timeline
        eventsData = eventsDataResponse.events || [];

        const serversDetailsResponse = await fetchWithRetry('/api/servers');
        const serverTagsAndDetails = serversDetailsResponse.servers.reduce((acc, server) => {
            acc[server.ip] = { inbound_tag: server.inbound_tag, os_info: server.os_info };
            return acc;
        }, {});

        serversData = rawServersData.map(server => {
            const details = serverTagsAndDetails[server.server_ip] || { inbound_tag: 'N/A', os_info: 'N/A' };
            const mockMetrics = generateMockServerMetrics(server.server_ip);
            return {
                ...server,
                inbound_tag: details.inbound_tag,
                os_info: details.os_info,
                ...mockMetrics
            };
        });

        console.log('Processed serversData:', serversData);
        console.log('Loaded eventsData:', eventsData);

        updateOverviewStats();
        renderFilteredServers();
        renderActivityFeed();
        showToast('Данные успешно загружены!', 'success');

    } catch (error) {
        console.error('Load data error:', error, error.stack);
        showToast('Ошибка загрузки: ' + error.message, 'error');
         ['totalServers', 'onlineServers', 'averageUptime'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.textContent = "Ошибка";
        });
        const sGrid = document.getElementById('serversGrid');
        if (sGrid) sGrid.innerHTML = `<div class="loading" style="grid-column:1/-1;">Ошибка загрузки серверов. ${error.message}</div>`;
        const actList = document.getElementById('activityList');
        if (actList) actList.innerHTML = `<div class="loading">Ошибка загрузки событий. ${error.message}</div>`;
    }
}

function updateOverviewStats() {
    try {
        const total = serversData.length;
        const online = serversData.filter(s => s.current_status === 'online').length;
        // Problematic count is no longer displayed in a dedicated card
        const avgUptime = total > 0 ? (serversData.reduce((sum, s) => sum + s.uptime_percentage, 0) / total) : 0;

        waitForElement('#totalServers').then(el => el.textContent = total).catch(console.error);
        waitForElement('#onlineServers').then(el => el.textContent = online).catch(console.error);
        waitForElement('#averageUptime').then(el => el.textContent = avgUptime.toFixed(1) + '%').catch(console.error);
        // Removed problematicServersCount and problematicServersCard updates

        waitForElement('#allCount').then(el => el.textContent = total).catch(console.error);
        waitForElement('#activeCount').then(el => el.textContent = online).catch(console.error);
        // Removed problematicCount update

        console.log('Overview stats updated:', { total, online, avgUptime });
    } catch (err) {
        console.error('Overview stats render error:', err);
    }
}


function filterAndSortServers() {
    return serversData
        .filter(server => {
            const serverIpLower = server.server_ip.toLowerCase();
            const tagLower = (server.inbound_tag || '').toLowerCase();
            const searchLower = searchQuery.toLowerCase();

            const matchesSearch = !searchLower ||
                serverIpLower.includes(searchLower) ||
                (tagLower && tagLower.includes(searchLower));

            // Adjusted filter logic: removed 'problematic'
            const matchesFilter = currentFilter === 'all' ||
                (currentFilter === 'active' && server.current_status === 'online');

            return matchesSearch && matchesFilter;
        })
        .sort((a, b) => {
            const statusOrder = { 'offline': 0, 'unknown': 1, 'online': 2 };
            if (statusOrder[a.current_status] < statusOrder[b.current_status]) return -1;
            if (statusOrder[a.current_status] > statusOrder[b.current_status]) return 1;
            return a.server_ip.localeCompare(b.server_ip);
        });
}

function renderTimeline(serverIp, currentServerStatus) {
    const serverEvents = eventsData
        .filter(e => e.server_ip === serverIp)
        .sort((a, b) => new Date(a.event_time) - new Date(b.event_time));

    const segments = 24;
    const periodHours = { '24h': 24, '7d': 168, '30d': 720 }[currentPeriod];

    if (!periodHours) {
        console.warn("Invalid currentPeriod for timeline:", currentPeriod, "Falling back to current status bar.");
        return `<div class="server-timeline-bar ${currentServerStatus || 'unknown'}" style="left: 0%; width: 100%;"></div>`;
    }

    const nowMs = Date.now();
    const periodDurationMs = periodHours * 3600 * 1000;
    const periodStartMs = nowMs - periodDurationMs;
    const segmentDurationMs = periodDurationMs / segments;
    let html = '';

    let statusAtPeriodBeginning = currentServerStatus;
    const eventsBeforeThisPeriod = serverEvents.filter(e => new Date(e.event_time).getTime() < periodStartMs);
    if (eventsBeforeThisPeriod.length > 0) {
        const lastEventBefore = eventsBeforeThisPeriod[eventsBeforeThisPeriod.length - 1];
        statusAtPeriodBeginning = (lastEventBefore.event_type === 'offline_start') ? 'offline' : 'online';
    } else {
        const server = serversData.find(s => s.server_ip === serverIp);
        if (server && new Date(server.last_status_change).getTime() < periodStartMs) {
            statusAtPeriodBeginning = server.current_status;
        }
    }
    
    for (let i = 0; i < segments; i++) {
        const segmentStartMs = periodStartMs + (i * segmentDurationMs);
        const segmentEndMs = segmentStartMs + segmentDurationMs;
        
        let currentSegmentStatus = statusAtPeriodBeginning; // Assume status from start of period initially for this segment
        let lastEventTimeInOrBeforeSegment = 0;

        // Find the latest event that defines the status at the beginning or during this segment
        for (const event of serverEvents) {
            const eventTimeMs = new Date(event.event_time).getTime();
            if (eventTimeMs < segmentEndMs) { // Event is relevant if it's before the end of this segment
                if (eventTimeMs >= lastEventTimeInOrBeforeSegment) { // Take the latest event that applies
                    currentSegmentStatus = (event.event_type === 'offline_start') ? 'offline' : 'online';
                    lastEventTimeInOrBeforeSegment = eventTimeMs;
                }
            } else {
                break; // Events are sorted, so no need to check further
            }
        }
        // Update statusAtPeriodBeginning for the *next* segment based on the status found for *this* one.
        statusAtPeriodBeginning = currentSegmentStatus;

        html += `<div class="server-timeline-bar ${currentSegmentStatus}" style="left: ${(i / segments) * 100}%; width: ${(1 / segments) * 100}%;"></div>`;
    }

    if (html === '') {
        return `<div class="server-timeline-bar ${currentServerStatus || 'unknown'}" style="left: 0%; width: 100%;"></div>`;
    }
    return html;
}


async function renderFilteredServers() {
    try {
        const container = await waitForElement('#serversGrid');
        const filteredServers = filterAndSortServers();

        document.getElementById('visibleServerCount').textContent = filteredServers.length;

        if (!filteredServers.length) {
            container.innerHTML = `<div class="loading" style="grid-column: 1 / -1;">Нет серверов по заданным критериям.</div>`;
            return;
        }

        container.innerHTML = filteredServers.map(server => {
            const statusText = server.current_status === 'online' ? 'Online' :
                               server.current_status === 'offline' ? 'Offline' : 'Unknown';
            const timelineHtml = renderTimeline(server.server_ip, server.current_status);

            let uptimeClass = 'high';
            if (server.uptime_percentage < 80) uptimeClass = 'low';
            else if (server.uptime_percentage < 95) uptimeClass = 'medium';

            return `
                <div class="server-card ${server.current_status}" data-ip="${server.server_ip}">
                    <div class="server-header">
                        <div class="server-info">
                            <div class="server-ip">${server.server_ip}</div>
                            ${server.inbound_tag && server.inbound_tag !== "N/A" ? `<div class="server-tag">${server.inbound_tag}</div>` : ''}
                        </div>
                        <div class="server-header-right">
                             <div class="server-uptime-value ${uptimeClass}">${server.uptime_percentage.toFixed(1)}%</div>
                             <div class="server-status ${server.current_status}">
                                <span class="status-dot"></span>
                                ${statusText}
                            </div>
                        </div>
                    </div>
                    <div class="server-metrics">
                        <div class="metric">
                            <div class="metric-value">${server.cpuUsagePercent || 'N/A'}%</div>
                            <div class="metric-label">CPU</div>
                        </div>
                        <div class="metric">
                            <div class="metric-value">${server.memoryUsagePercent || 'N/A'}%</div>
                            <div class="metric-label">RAM</div>
                        </div>
                        <div class="metric">
                            <div class="metric-value">${server.responseTimeMs || 'N/A'}ms</div>
                            <div class="metric-label">Ping</div>
                        </div>
                    </div>
                    <div class="server-timeline" id="timeline-${server.server_ip.replace(/\./g, '-')}">
                        ${timelineHtml}
                    </div>
                    <div class="server-meta-info">
                        <span>Событий: ${server.total_events || 0}</span>
                        <span>Статус изм.: ${server.last_status_change ? formatDate(server.last_status_change, true) : 'N/A'}</span>
                    </div>
                </div>
            `;
        }).join('');
    } catch (err) {
        console.error('Servers grid render error:', err);
        const container = document.getElementById('serversGrid');
        if (container) container.innerHTML = `<div class="loading" style="grid-column: 1 / -1;">Ошибка отображения серверов: ${err.message}</div>`;
    }
}

async function renderActivityFeed() {
    try {
        const container = await waitForElement('#activityList');
        const sortedEvents = [...eventsData].sort((a,b) => new Date(b.event_time) - new Date(a.event_time));
        const displayedEvents = sortedEvents.slice(0, eventLimit);


        if (!displayedEvents.length) {
            container.innerHTML = '<div class="loading" style="padding:10px 0;">Нет недавних событий.</div>';
            return;
        }

        container.innerHTML = displayedEvents.map(event => {
            let iconClass = 'info';
            let iconSvg = '<circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line>';

            if (event.event_type === 'online' || event.event_type === 'offline_end') {
                iconClass = 'success';
                iconSvg = '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>';
            } else if (event.event_type === 'offline_start') {
                iconClass = 'warning';
                iconSvg = '<polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2"></polygon><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line>';
            } else if (event.event_type === 'high_load') {
                 iconClass = 'warning';
                 iconSvg = '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/>';
            }

            let actionText = '';
            const serverDisplayIP = event.server_ip; // Always use IP as requested

            switch(event.event_type) {
                case 'online':
                    actionText = `Сервер <strong>${serverDisplayIP}</strong> подключен.`;
                    break;
                case 'offline_start':
                    actionText = `Соединение с <strong>${serverDisplayIP}</strong> потеряно.`;
                    break;
                case 'offline_end':
                    actionText = `<strong>${serverDisplayIP}</strong> снова онлайн.`;
                    if (event.duration_seconds && event.duration_seconds > 0) {
                        actionText += ` (Недоступен: ${formatDuration(event.duration_seconds)})`; // Changed "Простой" to "Недоступен"
                    }
                    break;
                case 'high_load':
                    actionText = `Высокая нагрузка на <strong>${serverDisplayIP}</strong>.`;
                    break;
                default:
                    actionText = `Событие '${event.event_type}' для <strong>${serverDisplayIP}</strong>.`;
            }


            return `
                <div class="activity-item">
                    <div class="activity-icon ${iconClass}">
                        <svg viewBox="0 0 24 24" style="width: 14px; height: 14px;" fill="none" stroke="currentColor" stroke-width="2">
                            ${iconSvg}
                        </svg>
                    </div>
                    <div class="activity-text">
                        <div class="activity-action">${actionText}</div>
                        <div class="activity-time">${formatDate(event.event_time)}</div>
                    </div>
                </div>
            `;
        }).join('');

        const items = container.querySelectorAll('.activity-item');
        items.forEach((item, index) => {
            requestAnimationFrame(() => {
                setTimeout(() => {
                    item.style.opacity = '1';
                    item.style.transform = 'translateY(0)';
                }, index * 50);
            });
        });

    } catch (err) {
        console.error('Events render error:', err);
        const container = document.getElementById('activityList');
        if (container) container.innerHTML = `<div class="loading">Ошибка отображения событий: ${err.message}</div>`;
    }
}

function formatDate(dateString, short = false) {
    if (!dateString || dateString === 'N/A') return 'N/A';
    try {
        const date = new Date(dateString);
        if (isNaN(date.getTime())) return 'Неверная дата';
        const now = new Date();
        const diffMs = now - date;
        const diffSec = Math.floor(diffMs / 1000);
        const diffMin = Math.floor(diffSec / 60);
        const diffHr = Math.floor(diffMin / 60);
        const diffDay = Math.floor(diffHr / 24);

        if (short) {
            if (diffMin < 1) return 'только что';
            if (diffMin < 60) return `${diffMin}м`;
            if (diffHr < 24) return `${diffHr}ч`;
            if (diffDay < 7) return `${diffDay}д`;
            return date.toLocaleDateString('ru-RU', { day:'numeric', month:'short' });
        }

        if (diffMin < 1) return 'Только что';
        if (diffMin < 60) return `${diffMin} мин. назад`;
        if (diffHr < 24) return `${diffHr} ч. ${diffMin % 60} мин. назад`;
        return date.toLocaleString('ru-RU', { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    } catch (e) {
        console.error("Error formatting date:", dateString, e);
        return 'Неверная дата';
    }
}

function formatDuration(totalSeconds, type = 'full') {
    if (totalSeconds == null || totalSeconds < 0) return 'N/A';
    if (totalSeconds === 0) return '0с';

    const days = Math.floor(totalSeconds / (3600 * 24));
    const hours = Math.floor((totalSeconds % (3600 * 24)) / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = Math.floor(totalSeconds % 60);

    let parts = [];
    if (days > 0) parts.push(`${days}д`);
    if (hours > 0) parts.push(`${hours}ч`);
    if (minutes > 0) parts.push(`${minutes}м`);
    if (seconds > 0 || parts.length === 0) parts.push(`${seconds}с`);

    if (type === 'short') return parts.slice(0, 2).join(' ') || (totalSeconds > 0 ? '~0с' : '0с');
    return parts.join(' ');
}

function toggleTheme() {
    const isDark = document.documentElement.hasAttribute('data-theme');
    if (isDark) {
        document.documentElement.removeAttribute('data-theme');
        localStorage.removeItem('theme');
        showToast('Светлая тема включена', 'info');
    } else {
        document.documentElement.setAttribute('data-theme', 'dark');
        localStorage.setItem('theme', 'dark');
        showToast('Тёмная тема включена', 'info');
    }
}

function loadTheme() {
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme === 'dark') {
        document.documentElement.setAttribute('data-theme', 'dark');
    }
}

function showToast(message, type = 'info', duration = 4000) {
    const container = document.getElementById('toastContainer');
    if (!container) {
        console.error('toastContainer not found');
        return;
    }

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;

    let iconSvg = '';
    switch(type) {
        case 'success':
            iconSvg = '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>';
            break;
        case 'error':
            iconSvg = '<polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2"></polygon><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line>';
            break;
        case 'warning':
             iconSvg = '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line>';
            break;
        case 'info':
        default:
            iconSvg = '<circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line>';
            break;
    }

    toast.innerHTML = `
        <span class="toast-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                ${iconSvg}
            </svg>
        </span>
        <div class="toast-message">${message}</div>
    `;

    container.appendChild(toast);

    setTimeout(() => toast.classList.add('show'), 10);

    setTimeout(() => {
        toast.classList.remove('show');
        toast.addEventListener('transitionend', () => {
            if (container.contains(toast)) {
                container.removeChild(toast);
            }
        }, { once: true });
    }, duration);
}

async function refreshData() {
    const button = document.getElementById('refreshButton');
    const icon = button ? button.querySelector('svg') : null;

    if (icon) {
        icon.style.transform = 'rotate(360deg)';
    }

    if(button) button.disabled = true;

    try {
        await loadData();
    } catch(e) {
        // Error already handled by loadData and showToast
    } finally {
        if (icon) {
            setTimeout(() => {
                icon.style.transform = 'rotate(0deg)';
            }, 300);
        }
        if(button) button.disabled = false;
    }
}

function toggleMobileMenu() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('mobileOverlay');
    const menuButton = document.getElementById('mobileMenuToggle');

    const isOpen = sidebar.classList.contains('mobile-open');

    if (isOpen) {
        closeMobileMenu();
    } else {
        sidebar.classList.add('mobile-open');
        overlay.classList.add('show');
        menuButton.classList.add('active');
        document.body.style.overflow = 'hidden';
    }
}

function closeMobileMenu() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('mobileOverlay');
    const menuButton = document.getElementById('mobileMenuToggle');

    if (sidebar.classList.contains('mobile-open')) {
        sidebar.classList.remove('mobile-open');
        overlay.classList.remove('show');
        menuButton.classList.remove('active');
        document.body.style.overflow = '';
    }
}
(function() {
    'use strict';
    
    const SCRIPT_VERSION = '2025-01-21-fixed';

    // --- Проверка загрузки auth_utils ---
    if (typeof window.authUtils === 'undefined') {
        console.error('auth_utils.js must be loaded before uptime.js');
    }

    // Создаем локальную ссылку на fetchWithAuth для удобства
    const fetchWithAuth = window.authUtils?.fetchWithAuth || fetch;

    let currentPeriod = '24h';
    let serversData = [];
    let eventsData = [];
    let currentFilter = 'all';
    let searchQuery = '';
    let eventLimit = 20;

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

            // Show loading spinners
            ['totalServers', 'onlineServers', 'averageUptime'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.innerHTML = `<span class="loading"><span class="spinner"></span></span>`;
            });
            const sGrid = document.getElementById('serversGrid');
            if (sGrid) sGrid.innerHTML = `<div class="loading" style="grid-column: 1 / -1;"><span class="spinner"></span> Загрузка серверов...</div>`;
            const actList = document.getElementById('activityList');
            if (actList) actList.innerHTML = `<div class="loading"><span class="spinner"></span> Загрузка событий...</div>`;

            // Load all data in parallel like in server_list.js
            const [summaryResponse, eventsResponse, serversResponse] = await Promise.all([
                fetchWithAuth(`/api/uptime/summary?period=${currentPeriod}`),
                fetchWithAuth(`/api/server_events?period=${currentPeriod}&limit=250`),
                fetchWithAuth('/api/servers')
            ]);

            if (!summaryResponse.ok) throw new Error(`HTTP error! status: ${summaryResponse.status}`);
            if (!eventsResponse.ok) throw new Error(`HTTP error! status: ${eventsResponse.status}`);
            if (!serversResponse.ok) throw new Error(`HTTP error! status: ${serversResponse.status}`);

            const summaryData = await summaryResponse.json();
            const eventsDataResponse = await eventsResponse.json();
            const serversDetailsResponse = await serversResponse.json();

            let rawServersData = summaryData.data || [];
            eventsData = eventsDataResponse.events || [];

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
            console.error('Load data error:', error);
            showToast('Ошибка загрузки: ' + error.message, 'error');
            
            // Set empty data like in server_list.js
            serversData = [];
            eventsData = [];
            
            ['totalServers', 'onlineServers', 'averageUptime'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.textContent = "0";
            });
            const sGrid = document.getElementById('serversGrid');
            if (sGrid) sGrid.innerHTML = `<div class="loading" style="grid-column:1/-1;">Ошибка загрузки серверов</div>`;
            const actList = document.getElementById('activityList');
            if (actList) actList.innerHTML = `<div class="loading">Ошибка загрузки событий</div>`;
            
            updateOverviewStats();
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

    function updateOverviewStats() {
        try {
            const total = serversData.length;
            const online = serversData.filter(s => s.current_status === 'online').length;
            const avgUptime = total > 0 ? (serversData.reduce((sum, s) => sum + s.uptime_percentage, 0) / total) : 0;

            document.getElementById('totalServers').textContent = total;
            document.getElementById('onlineServers').textContent = online;
            document.getElementById('averageUptime').textContent = avgUptime.toFixed(1) + '%';

            document.getElementById('allCount').textContent = total;
            document.getElementById('activeCount').textContent = online;

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
            
            let currentSegmentStatus = statusAtPeriodBeginning;
            let lastEventTimeInOrBeforeSegment = 0;

            for (const event of serverEvents) {
                const eventTimeMs = new Date(event.event_time).getTime();
                if (eventTimeMs < segmentEndMs) {
                    if (eventTimeMs >= lastEventTimeInOrBeforeSegment) {
                        currentSegmentStatus = (event.event_type === 'offline_start') ? 'offline' : 'online';
                        lastEventTimeInOrBeforeSegment = eventTimeMs;
                    }
                } else {
                    break;
                }
            }
            statusAtPeriodBeginning = currentSegmentStatus;

            html += `<div class="server-timeline-bar ${currentSegmentStatus}" style="left: ${(i / segments) * 100}%; width: ${(1 / segments) * 100}%;"></div>`;
        }

        if (html === '') {
            return `<div class="server-timeline-bar ${currentServerStatus || 'unknown'}" style="left: 0%; width: 100%;"></div>`;
        }
        return html;
    }

    function renderFilteredServers() {
        try {
            const container = document.getElementById('serversGrid');
            if (!container) return;

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

    function renderActivityFeed() {
        try {
            const container = document.getElementById('activityList');
            if (!container) return;

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
                const serverDisplayIP = event.server_ip;

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
                            actionText += ` (Недоступен: ${formatDuration(event.duration_seconds)})`;
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

})(); // Конец IIFE
(function() {
    'use strict';
    
    const SCRIPT_VERSION = 'original-logic-themed-v2.4-dropdown-fix-auth';

    // --- Проверка загрузки auth_utils ---
    if (typeof window.authUtils === 'undefined') {
        console.error('auth_utils.js must be loaded before server_list.js');
    }

    // Создаем локальную ссылку на fetchWithAuth для удобства
    const fetchWithAuth = window.authUtils?.fetchWithAuth || fetch;

    // --- Глобальные переменные из вашего оригинального JS ---
    let allServers = [];
let filteredServers = [];
let selectedServers = new Set();
let currentSort = { field: 'install_date', direction: 'desc' };
let currentModalAction = null;
let currentModalData = null;
let availableScripts = [];

// --- Общие UI функции темы (стандартизированные) ---
function loadTheme() {
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme === 'dark') {
        document.documentElement.setAttribute('data-theme', 'dark');
    } else {
        document.documentElement.removeAttribute('data-theme');
    }
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

function showToast(message, type = 'info', duration = 4000) {
    const container = document.getElementById('toastContainer');
    if (!container) { console.error('toastContainer not found'); return; }
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    let iconSvg = '';
    switch(type) {
        case 'success': iconSvg = '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>'; break;
        case 'error': iconSvg = '<polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2"></polygon><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line>'; break;
        case 'warning': iconSvg = '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line>'; break;
        default: iconSvg = '<circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line>'; break;
    }
    toast.innerHTML = `<span class="toast-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">${iconSvg}</svg></span><div class="toast-message">${message}</div>`;
    container.appendChild(toast);
    setTimeout(() => toast.classList.add('show'), 10);
    setTimeout(() => {
        toast.classList.remove('show');
        toast.addEventListener('transitionend', () => { if (container.contains(toast)) container.removeChild(toast); }, { once: true });
    }, duration);
}

function toggleMobileMenu() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('mobileOverlay');
    const menuButton = document.getElementById('mobileMenuToggle');
    if (!sidebar || !overlay) return;
    const isOpen = sidebar.classList.contains('mobile-open');
    if (isOpen) closeMobileMenu();
    else {
        sidebar.classList.add('mobile-open');
        overlay.classList.add('show');
        if(menuButton) menuButton.classList.add('active');
        document.body.style.overflow = 'hidden';
    }
}

function closeMobileMenu() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('mobileOverlay');
    const menuButton = document.getElementById('mobileMenuToggle');
    if (!sidebar || !overlay) return;
    if (sidebar.classList.contains('mobile-open')) {
        sidebar.classList.remove('mobile-open');
        overlay.classList.remove('show');
        if(menuButton) menuButton.classList.remove('active');
        document.body.style.overflow = '';
    }
}
// --- Конец общих UI функций темы ---

document.addEventListener('DOMContentLoaded', () => {
    console.log(`server_list.js ${SCRIPT_VERSION} loaded`);
    loadTheme();
    setupMobileMenuEventListeners();
    
    loadServers();
    loadScripts();
    setupEventListeners();
    setupSearch();
    
    updateStats();
    updateSelectedActionsBar();
    updateRunButtonState();
    updateRebootButtonState();
});

function setupMobileMenuEventListeners() {
    const mobileMenuToggle = document.getElementById('mobileMenuToggle');
    if (mobileMenuToggle) mobileMenuToggle.addEventListener('click', toggleMobileMenu);
    
    const overlay = document.getElementById('mobileOverlay');
    if(overlay) overlay.addEventListener('click', closeMobileMenu);
}

async function loadServers() {
    const totalEl = document.getElementById('totalServersStat');
    const onlineEl = document.getElementById('onlineServersStat');
    if(totalEl) totalEl.innerHTML = `<span class="loading"><span class="spinner"></span></span>`;
    if(onlineEl) onlineEl.innerHTML = `<span class="loading"><span class="spinner"></span></span>`;

    try {
        const [serversResponse, statusesResponse] = await Promise.all([
            fetchWithAuth('/api/servers'),
            fetchWithAuth('/api/server_status')
        ]);
        if (!serversResponse.ok) throw new Error(`HTTP error! status: ${serversResponse.status}`);
        if (!statusesResponse.ok) throw new Error(`HTTP error! status: ${statusesResponse.status}`);
        const serversData = await serversResponse.json();
        const statusesData = await statusesResponse.json();
        allServers = (serversData.servers || []).map(server => ({
            ...server,
            status: (statusesData.statuses || {})[server.ip] || 'unknown' 
        }));
        sortServers(currentSort.field, currentSort.direction, false);
        filteredServers = [...allServers];
        renderServers();
        showToast(`Загружено ${allServers.length} серверов`, 'success');
    } catch (error) {
        console.error('Error loading servers:', error);
        showToast('Ошибка загрузки серверов: ' + error.message, 'error');
        allServers = [];
        filteredServers = [];
        renderServers();
    } finally {
        updateStats();
    }
}

async function loadScripts() {
    try {
        const response = await fetchWithAuth('/api/scripts');
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        availableScripts = (await response.json()).scripts || [];
        populateScriptSelect(document.getElementById('scriptSelect'));
    } catch (error) {
        console.error('Error loading scripts:', error);
        showToast('Ошибка загрузки скриптов: ' + error.message, 'error');
        const scriptSelectEl = document.getElementById('scriptSelect');
        if(scriptSelectEl) scriptSelectEl.innerHTML = '<option value="">Ошибка загрузки скриптов</option>';
    }
}

function populateScriptSelect(selectElement) {
    if (!selectElement) return;
    selectElement.innerHTML = '<option value="">Выберите скрипт...</option>' +
        (availableScripts.map(script => `<option value="${script}">${script}</option>`).join('') || '<option value="" disabled>Скрипты не найдены</option>');
}

function setupEventListeners() {
    console.log('Setting up event listeners');
    const themeBtn = document.getElementById('themeButton');
    if(themeBtn) themeBtn.addEventListener('click', toggleTheme);

    document.addEventListener('click', (e) => {
        if (!e.target.closest('.action-menu-button') && !e.target.closest('#rowActionDropdown')) {
            closeDropdown();
        }
    });
    const modalOverlayEl = document.getElementById('confirmationModalOverlay');
    if(modalOverlayEl) {
        modalOverlayEl.addEventListener('click', (e) => {
            if (e.target === e.currentTarget) closeModal();
        });
    }
    const modalCancelBtn = document.getElementById('modalCancelButton');
    if(modalCancelBtn) modalCancelBtn.addEventListener('click', closeModal);
    const modalConfirmBtn = document.getElementById('modalConfirmButton');
    if(modalConfirmBtn) modalConfirmBtn.addEventListener('click', confirmModalAction);

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') { closeDropdown(); closeModal(); closeMobileMenu(); }
        if (document.activeElement.tagName !== 'INPUT' && document.activeElement.tagName !== 'TEXTAREA') {
            if (e.key === 'Delete' && selectedServers.size > 0) { e.preventDefault(); bulkDelete(); }
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'a') { 
                e.preventDefault(); 
                const selectAllCheckbox = document.getElementById('selectAllCheckbox');
                if(selectAllCheckbox){
                    if (filteredServers.length > 0 && selectedServers.size === filteredServers.length) {
                        clearSelection();
                    } else {
                        selectAllFilteredServers();
                    }
                }
            }
        }
    });

    const rebootButton = document.getElementById('rebootSelectedButton');
    if (rebootButton) {
        rebootButton.addEventListener('click', bulkReboot);
    }
    const scriptSel = document.getElementById('scriptSelect');
    if(scriptSel) scriptSel.addEventListener('change', updateRunButtonState);
    
    updateRunButtonState();
    updateRebootButtonState();
}

function setupSearch() {
    console.log('Setting up search');
    const searchInput = document.getElementById('serverSearchInput');
    if (!searchInput) { console.error("Search input #serverSearchInput not found"); return; }
    let searchTimeout;
    searchInput.addEventListener('input', (e) => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => filterServers(e.target.value), 300);
    });
}

function filterServers(query) {
    console.log('Filtering servers with query:', query);
    const searchTerm = (query || "").toLowerCase().trim();
    if (!searchTerm) {
        filteredServers = [...allServers];
    } else {
        filteredServers = allServers.filter(server => 
            (server.ip && server.ip.toLowerCase().includes(searchTerm)) ||
            (server.inbound_tag && server.inbound_tag.toLowerCase().includes(searchTerm)) ||
            (server.install_date && formatDateDisplay(server.install_date).toLowerCase().includes(searchTerm)) ||
            (server.status && getStatusText(server.status).toLowerCase().includes(searchTerm))
        );
    }
    sortServers(currentSort.field, currentSort.direction, false);
    renderServers();
    updateStats();
    updateSelectAllCheckboxState();
}

function renderServers() {
    console.log('Rendering servers:', filteredServers.length);
    const tbody = document.getElementById('serversTableBody');
    const emptyContainer = document.getElementById('emptyStateContainer');

    if (!tbody || !emptyContainer) {
        console.error("Table body or empty state container not found for rendering servers.");
        return;
    }
    
    if (!filteredServers.length) {
        tbody.innerHTML = '';
        emptyContainer.style.display = 'flex';
        return;
    }
    emptyContainer.style.display = 'none';

    tbody.innerHTML = filteredServers.map(server => `
        <tr class="${selectedServers.has(server.ip) ? 'selected' : ''}" data-ip="${server.ip}">
            <td class="checkbox-cell">
                <label class="custom-checkbox">
                    <input type="checkbox" ${selectedServers.has(server.ip) ? 'checked' : ''} onchange="toggleServerSelection('${server.ip}', this.checked)">
                    <span class="checkmark"></span>
                </label>
            </td>
            <td><div class="server-ip">${server.ip}</div></td>
            <td>${server.inbound_tag || 'N/A'}</td>
            <td>
                <span class="server-status status-${server.status || 'unknown'}">
                    <span class="status-dot"></span>
                    <span class="status-text-mobile-hidden">${getStatusText(server.status)}</span>
                </span>
            </td>
            <td>${formatDateDisplay(server.install_date)}</td>
            <td class="actions-cell">
                <button class="action-menu-button" onclick="toggleDropdown(this, '${server.ip}')">
                    <svg style="width: 18px; height: 18px;" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                        <circle cx="12" cy="12" r="1.5" /><circle cx="12" cy="5" r="1.5" /><circle cx="12" cy="19" r="1.5" />
                    </svg>
                </button>
            </td>
        </tr>
    `).join('');
}

function getStatusText(status) {
    switch (status) {
        case 'online': return 'Онлайн';
        case 'offline': return 'Офлайн';
        default: return 'Неизвестно';
    }
}

function toggleServerSelection(ip, isChecked) {
    if (isChecked) {
        selectedServers.add(ip);
    } else {
        selectedServers.delete(ip);
    }
    updateSelectionUI();
}

function toggleSelectAll() {
    const selectAllCheckbox = document.getElementById('selectAllCheckbox');
    if (!selectAllCheckbox) return;
    if (selectAllCheckbox.checked) {
        selectAllFilteredServers();
    } else {
        clearSelection();
    }
}

function selectAllFilteredServers() {
    filteredServers.forEach(server => selectedServers.add(server.ip));
    updateSelectionUI();
}

function clearSelection() {
    selectedServers.clear();
    updateSelectionUI();
}

function updateSelectionUI() {
    document.querySelectorAll('#serversTableBody tr').forEach(row => {
        const ip = row.dataset.ip;
        if(ip) {
            row.classList.toggle('selected', selectedServers.has(ip));
            const checkbox = row.querySelector('input[type="checkbox"]');
            if (checkbox) checkbox.checked = selectedServers.has(ip);
        }
    });
    updateSelectAllCheckboxState();
    updateStats();
    updateSelectedActionsBar();
    updateRunButtonState();
    updateRebootButtonState();
}

function updateSelectAllCheckboxState() {
    const selectAllCheckbox = document.getElementById('selectAllCheckbox');
    if (!selectAllCheckbox) return;
    
    const selectedInFilteredCount = filteredServers.filter(s => selectedServers.has(s.ip)).length;
    const totalFiltered = filteredServers.length;

    if (totalFiltered === 0) {
        selectAllCheckbox.checked = false;
        selectAllCheckbox.indeterminate = false;
    } else if (selectedInFilteredCount === totalFiltered) {
        selectAllCheckbox.checked = true;
        selectAllCheckbox.indeterminate = false;
    } else if (selectedInFilteredCount > 0) {
        selectAllCheckbox.checked = false;
        selectAllCheckbox.indeterminate = true;
    } else {
        selectAllCheckbox.checked = false;
        selectAllCheckbox.indeterminate = false;
    }
}

function updateSelectedActionsBar() {
    const bar = document.getElementById('selectedActionsBar');
    const countText = document.getElementById('selectedServersCountText');
    if (!bar || !countText) return;
    countText.textContent = `${selectedServers.size} выбрано`;
    bar.classList.toggle('visible', selectedServers.size > 0);
}

function updateRunButtonState() {
    const btn = document.getElementById('runScriptButton');
    const textSpan = document.getElementById('runButtonText');
    const select = document.getElementById('scriptSelect');
    if (!btn || !textSpan || !select) return;
    btn.disabled = !(selectedServers.size > 0 && select.value);
    textSpan.textContent = select.value ? `Запустить "${select.options[select.selectedIndex].text}"` : 'Запустить скрипт';
}

function updateRebootButtonState() {
    const btn = document.getElementById('rebootSelectedButton');
    if (btn) btn.disabled = selectedServers.size === 0;
}

function updateStats() {
    const totalEl = document.getElementById('totalServersStat');
    const onlineEl = document.getElementById('onlineServersStat');
    const selectedEl = document.getElementById('selectedServersStat');
    if(totalEl) totalEl.textContent = allServers.length;
    if(onlineEl) onlineEl.textContent = allServers.filter(s => s.status === 'online').length;
    if(selectedEl) selectedEl.textContent = selectedServers.size;
}

function sortTable(field) {
    const newDirection = (currentSort.field === field && currentSort.direction === 'asc') ? 'desc' : 'asc';
    sortServers(field, newDirection, true);
}

function sortServers(field, direction, updateIconUI = true) {
    currentSort = { field, direction };
    if (updateIconUI) {
        document.querySelectorAll('th.sortable').forEach(th => {
            th.classList.remove('active', 'asc', 'desc');
            if (th.getAttribute('onclick')?.includes(`sortTable('${field}')`)) {
                th.classList.add('active', direction);
            }
        });
    }
    const sorter = (a,b) => {
        let aVal = a[field], bVal = b[field];
        if (field === 'install_date') {
            aVal = aVal ? new Date(aVal).getTime() : 0;
            bVal = bVal ? new Date(bVal).getTime() : 0;
        } else if (typeof aVal === 'string' && typeof bVal === 'string') {
            aVal = aVal.toLowerCase(); bVal = bVal.toLowerCase();
        } else if (aVal == null) aVal = direction === 'asc' ? Infinity : -Infinity;
        else if (bVal == null) bVal = direction === 'asc' ? Infinity : -Infinity;
        if (aVal < bVal) return direction === 'asc' ? -1 : 1;
        if (aVal > bVal) return direction === 'asc' ? 1 : -1;
        return 0;
    };
    allServers.sort(sorter);
    filteredServers.sort(sorter);
    renderServers();
}

function toggleDropdown(button, ip) {
    const dropdown = document.getElementById('rowActionDropdown');
    if (!dropdown) {
        console.error("Dropdown menu element #rowActionDropdown not found!");
        return;
    }

    const isActiveForThisButton = dropdown.classList.contains('active') && dropdown.dataset.currentIp === ip;

    closeDropdown(); // Close any currently open dropdown

    if (!isActiveForThisButton) {
        dropdown.dataset.currentIp = ip;
        const rect = button.getBoundingClientRect();

        // Use fixed approximate dimensions for boundary checking, actual size is by CSS
        const DDE_APPROX_WIDTH = 200; 
        const DDE_APPROX_HEIGHT = 170; // Approx height for 4 items

        let top = rect.bottom + window.scrollY + 5; // Preferred: below button
        let left = rect.left + window.scrollX;   // Preferred: align left with button

        // Horizontal boundary check
        if (left + DDE_APPROX_WIDTH > window.innerWidth - 10) { // If right edge goes off-screen
            left = window.innerWidth - DDE_APPROX_WIDTH - 10; // Align to right viewport edge
        }
        if (left < 10) { // If left edge goes off-screen
            left = 10;
        }

        // Vertical boundary check
        if (top + DDE_APPROX_HEIGHT > (window.innerHeight + window.scrollY) - 10) { // If bottom edge goes off-screen
            top = rect.top + window.scrollY - DDE_APPROX_HEIGHT - 5; // Position above button
        }
        if (top < window.scrollY + 10) { // If still too high (or button is near top)
             top = window.scrollY + 10; // Stick to top of viewport
        }
         // Final check to ensure it's not negative if calculations were off
        if (top < 0) top = 10;


        dropdown.style.top = `${top}px`;
        dropdown.style.left = `${left}px`;
        
        dropdown.classList.add('active');

        // Attach event listeners to items
        document.getElementById('dropdownRunScript').onclick = () => { showRunScriptModal([ip]); closeDropdown(); };
        document.getElementById('dropdownEditServer').onclick = () => { showEditServerModal(ip); closeDropdown(); };
        document.getElementById('dropdownRebootServer').onclick = () => { rebootServer(ip); closeDropdown(); };
        document.getElementById('dropdownDeleteServer').onclick = () => { showDeleteModal([ip]); closeDropdown(); };
    }
}

function closeDropdown() {
    const dd = document.getElementById('rowActionDropdown');
    if(dd) {
        dd.classList.remove('active');
        delete dd.dataset.currentIp;
    }
}

function formatDateDisplay(dateString) {
    if (!dateString || dateString === "0001-01-01T00:00:00Z") return '—';
    try {
        const date = new Date(dateString);
        if (isNaN(date.getTime())) return 'Неверная дата';
        return date.toLocaleDateString('ru-RU', {
            day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit'
        }).replace(',', '');
    } catch (e) { return 'Неверная дата'; }
}

// --- Modal Functions ---
function showModal(title, descriptionText, actionType, data, confirmBtnText = "Подтвердить", confirmBtnType = "primary", dynamicHTML = "") {
    currentModalAction = actionType;
    currentModalData = data;
    document.getElementById('modalTitle').textContent = title;
    document.getElementById('modalDescriptionText').textContent = descriptionText;
    document.getElementById('modalDynamicContent').innerHTML = dynamicHTML;
    const confirmButton = document.getElementById('modalConfirmButton');
    confirmButton.textContent = confirmBtnText;
    confirmButton.className = `modal-button ${confirmBtnType}`;
    document.getElementById('confirmationModalOverlay').classList.add('active');
}

function closeModal() {
    document.getElementById('confirmationModalOverlay').classList.remove('active');
    document.getElementById('modalDynamicContent').innerHTML = '';
    currentModalAction = null; currentModalData = null;
}

async function confirmModalAction() {
    if (!currentModalAction) return;
    const confirmBtn = document.getElementById('modalConfirmButton');
    if(confirmBtn) confirmBtn.disabled = true;

    try {
        switch (currentModalAction) {
            case 'run_script_modal':
                const scriptSelect = document.getElementById('modalPromptScriptSelect');
                const scriptName = scriptSelect ? scriptSelect.value : null;
                if (!scriptName) { 
                    showToast('Пожалуйста, выберите скрипт.', 'error'); 
                    if(confirmBtn) confirmBtn.disabled = false;
                    return; 
                }
                await executeRunScript(currentModalData.ips, scriptName);
                break;
            case 'edit_server': await executeEditServer(currentModalData); break;
            case 'delete_servers': await executeDeleteServers(currentModalData); break;
            case 'reboot_single': await executeReboot([currentModalData]); break;
            case 'reboot_bulk': await executeReboot(currentModalData); break;
            default: console.warn('Unknown modal action:', currentModalAction);
        }
    } finally {
        if(confirmBtn) confirmBtn.disabled = false;
        if (currentModalAction !== 'run_script_modal' || (document.getElementById('modalPromptScriptSelect') && document.getElementById('modalPromptScriptSelect').value) ) {
             closeModal();
        }
    }
}

// --- Action Execution Functions ---
function bulkRunScriptFromBar() {
    if (selectedServers.size === 0) { showToast('Выберите серверы.', 'error'); return; }
    const scriptSelect = document.getElementById('scriptSelect');
    if (!scriptSelect || !scriptSelect.value) { showToast('Выберите скрипт.', 'error'); return; }
    showRunScriptModal(Array.from(selectedServers), scriptSelect.value);
}

async function executeRunScript(ips, scriptName) {
    const btnInBar = document.getElementById('runScriptButton');
    if(btnInBar) { btnInBar.classList.add('loading'); btnInBar.disabled = true; }
    
    try {
        showToast(`Запуск "${scriptName}" на ${ips.length} сервер(ах)...`, 'info', 5000);
        const response = await fetchWithAuth('/api/run_scripts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ips, script_name: scriptName }) });
        if (!response.ok) { const err = await response.json().catch(()=>({})); throw new Error(err.detail || `HTTP ${response.status}`); }
        const data = await response.json();
        let successes = 0, errors = 0, errorMsgs = [];
        (data.results || []).forEach(r => r.success ? successes++ : (errors++, errorMsgs.push(`${r.ip}: ${r.message||'Ошибка'}`)));
        if (errors === 0) showToast(`Скрипт "${scriptName}" выполнен на ${successes} сервер(ах).`, 'success');
        else showToast(`Выполнено: ${successes}, ошибок: ${errors}. ${errorMsgs.join('; ')}`, successes > 0 ? 'warning' : 'error', 7000);
        if (successes > 0 || errors > 0) clearSelection();
    } catch (e) { showToast(`Ошибка запуска скрипта: ${e.message}`, 'error', 7000); }
    finally { if(btnInBar) {btnInBar.classList.remove('loading'); updateRunButtonState(); }}
}

async function rebootServer(ip) {
    showModal('Перезагрузка сервера', `Перезагрузить сервер ${ip}?`, 'reboot_single', ip, 'Перезагрузить', 'danger');
}

async function bulkReboot() {
    if (selectedServers.size === 0) { showToast('Выберите серверы для перезагрузки.', 'error'); return; }
    showModal('Массовая перезагрузка', `Перезагрузить ${selectedServers.size} выбранных серверов?`, 'reboot_bulk', Array.from(selectedServers), 'Перезагрузить все', 'danger');
}

async function executeReboot(ips) {
    const btnInBar = document.getElementById('rebootSelectedButton');
    if(btnInBar) { btnInBar.classList.add('loading'); btnInBar.disabled = true; }
    try {
        showToast(`Перезагрузка ${ips.length} сервер(ах)...`, 'info', 5000);
        const response = await fetchWithAuth('/api/reboot_servers', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ips }) });
        if (!response.ok) { const err = await response.json().catch(()=>({})); throw new Error(err.detail || `HTTP ${response.status}`); }
        const data = await response.json();
        let successes = 0, errors = 0, errorMsgs = [];
        (data.results || []).forEach(r => r.success ? successes++ : (errors++, errorMsgs.push(`${r.ip}: ${r.message||'Ошибка'}`)));
        if (errors === 0) showToast(`${successes} сервер(ов) успешно перезагружены.`, 'success');
        else showToast(`Перезагружено: ${successes}, ошибок: ${errors}. ${errorMsgs.join('; ')}`, successes > 0 ? 'warning' : 'error', 7000);
        if (successes > 0 || errors > 0) clearSelection();
    } catch (e) { showToast(`Ошибка перезагрузки: ${e.message}`, 'error', 7000); }
    finally { if(btnInBar) {btnInBar.classList.remove('loading'); updateRebootButtonState(); }}
}

async function showEditServerModal(ip) {
    const server = allServers.find(s => s.ip === ip);
    if (!server) { showToast('Сервер не найден.', 'error'); return; }
    let tags = []; 
    try { 
        const r = await fetchWithAuth('/api/inbound_tags'); 
        if(r.ok) tags=(await r.json()).tags||[];
    } catch(e){
        console.error("Failed to load tags for edit:", e);
    }
    const content = `
        <div class="form-group"><label for="modalEditIpInput">IP адрес:</label><input type="text" id="modalEditIpInput" class="form-input" value="${server.ip}" required></div>
        <div class="form-group"><label for="modalEditInboundTagInput">Inbound Tag:</label><select id="modalEditInboundTagInput" class="form-select" required><option value="">Выберите тег...</option>${tags.map(t => `<option value="${t}" ${t === server.inbound_tag ? 'selected' : ''}>${t}</option>`).join('')}${(!tags.includes(server.inbound_tag) && server.inbound_tag && server.inbound_tag !== 'N/A') ? `<option value="${server.inbound_tag}" selected>${server.inbound_tag} (текущий)</option>` : ''}</select></div>`;
    showModal('Редактировать сервер', `Сервер ${ip}:`, 'edit_server', { oldIp: ip }, 'Сохранить', 'primary', content);
}

async function executeEditServer(data) {
    const newIp = document.getElementById('modalEditIpInput')?.value;
    const newTag = document.getElementById('modalEditInboundTagInput')?.value;
    if (!newIp || !newTag) { showToast('Заполните все поля.', 'error'); return; }
    try {
        showToast(`Сохранение ${data.oldIp}...`, 'info');
        const response = await fetchWithAuth('/api/edit_server', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ old_ip: data.oldIp, new_ip: newIp, new_inbound_tag: newTag }) });
        if (!response.ok) { const err = await response.json().catch(()=>({})); throw new Error(err.detail || `HTTP ${response.status}`); }
        const result = await response.json();
        if (result.success) { showToast(`Сервер ${data.oldIp} обновлен.`, 'success'); await loadServers(); }
        else throw new Error(result.message || 'Не удалось обновить.');
    } catch (e) { showToast(`Ошибка редактирования: ${e.message}`, 'error'); }
}

function showDeleteModal(ips) {
    const multi = ips.length > 1;
    showModal(multi ? 'Удалить серверы' : 'Удалить сервер', `Удалить ${multi ? ips.length + ' выбранных серверов' : 'сервер ' + ips[0]}? Действие необратимо.`, 'delete_servers', ips, multi ? 'Удалить выбранные' : 'Удалить сервер', 'danger');
}

function showRunScriptModal(ips, preSelectedScript = null) {
    const isMultiple = ips.length > 1;
    const title = isMultiple ? 'Запустить скрипт на серверах' : 'Запустить скрипт на сервере';
    let description = isMultiple ? `Запуск скрипта на ${ips.length} серверах.` : `Запуск скрипта на сервере ${ips[0]}.`;
    description += " Выберите скрипт из списка:";
    currentModalData = { ips, preSelectedScript };
    let dynamicContentHTML = `<div class="form-group" style="margin-top: 1rem;"><label for="modalPromptScriptSelect" style="display:none;">Выберите скрипт</label><select id="modalPromptScriptSelect" class="form-select"><option value="">Загрузка скриптов...</option></select></div>`;
    showModal(title, description, 'run_script_modal', currentModalData, 'Запустить', 'primary', dynamicContentHTML);
    const modalScriptSelect = document.getElementById('modalPromptScriptSelect');
    if(modalScriptSelect) {
        populateScriptSelect(modalScriptSelect);
        if(preSelectedScript) modalScriptSelect.value = preSelectedScript;
    }
}

async function executeDeleteServers(ips) {
    if (!ips || ips.length === 0) { showToast('Нет серверов для удаления.', 'warning'); return; }
    const confirmBtn = document.getElementById('modalConfirmButton');
    if(confirmBtn) confirmBtn.disabled = true;

    showToast(`Удаление ${ips.length} сервер(ах)...`, 'info', 3000 + ips.length * 300);

    const results = await Promise.allSettled(
        ips.map(ip =>
            fetchWithAuth(`/api/delete_server?ip=${encodeURIComponent(ip)}`, {
                method: 'DELETE'
            }).then(async response => { 
                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({ detail: `HTTP ${response.status} для ${ip}` }));
                    throw new Error(errorData.detail || `Ошибка ${response.status} для ${ip}`);
                }
                let responseData = { message: `Сервер ${ip} удален.`};
                try {
                    const contentType = response.headers.get("content-type");
                    if (contentType && contentType.indexOf("application/json") !== -1) {
                        responseData = await response.json();
                    }
                } catch (e) { /* Ignore if no JSON body */ }
                return { success: true, ip: ip, message: responseData.message || `Сервер ${ip} удален.` };
            }).catch(error => ({ success: false, ip: ip, message: error.message }))
        )
    );

    let successCount = 0;
    let errorMessages = [];
    results.forEach(result => {
        if (result.status === 'fulfilled' && result.value.success) {
            successCount++;
            allServers = allServers.filter(server => server.ip !== result.value.ip);
            filteredServers = filteredServers.filter(server => server.ip !== result.value.ip);
            selectedServers.delete(result.value.ip);
        } else if (result.status === 'fulfilled' && !result.value.success) {
            errorMessages.push(result.value.message);
        } else if (result.status === 'rejected') {
            errorMessages.push(result.reason.message || `Неизвестная ошибка удаления для одного из серверов.`);
        }
    });

    if (errorMessages.length === 0 && successCount > 0) {
        showToast(`${successCount} сервер(ов) успешно удалены.`, 'success');
    } else if (successCount > 0) {
        showToast(`Удалено: ${successCount}, ошибок: ${errorMessages.length}. Детали: ${errorMessages.join('; ')}`, 'warning', 7000);
    } else if (errorMessages.length > 0) {
        showToast(`Ошибка удаления серверов. Детали: ${errorMessages.join('; ')}`, 'error', 7000);
    }
    
    renderServers();
    updateSelectionUI();
    if(confirmBtn) confirmBtn.disabled = false;
}

function bulkDelete() {
    if (selectedServers.size === 0) { showToast('Выберите серверы для удаления.', 'error'); return; }
    showDeleteModal(Array.from(selectedServers));
}

// Make functions available globally (for inline event handlers)
window.toggleServerSelection = toggleServerSelection;
window.toggleSelectAll = toggleSelectAll;
window.sortTable = sortTable;
window.toggleDropdown = toggleDropdown;
window.bulkRunScriptFromBar = bulkRunScriptFromBar;

})(); // Конец IIFE
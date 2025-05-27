let allServers = [];
let filteredServers = [];
let selectedServers = new Set();
let currentSort = { field: null, direction: 'asc' };
let currentModalAction = null;
let currentModalData = null;
let availableScripts = [];

document.addEventListener('DOMContentLoaded', () => {
    console.log('DOM loaded');
    loadServers();
    loadScripts();
    setupEventListeners();
    setupSearch();
    loadTheme();
});

async function loadServers() {
    try {
        showToast('Загрузка серверов...', 'info');
        const [serversResponse, statusesResponse] = await Promise.all([
            fetch('/api/servers'),
            fetch('/api/server_status')
        ]);
        if (!serversResponse.ok) throw new Error(`HTTP error! status: ${serversResponse.status}`);
        if (!statusesResponse.ok) throw new Error(`HTTP error! status: ${statusesResponse.status}`);
        const serversData = await serversResponse.json();
        const statusesData = await statusesResponse.json();
        allServers = serversData.servers || [];
        const statuses = statusesData.statuses || {};
        let missingServers = [];
        allServers = allServers.map(server => {
            const status = statuses[server.ip] || 'offline';
            if (!statuses[server.ip]) missingServers.push(server.ip);
            return { ...server, status };
        });
        filteredServers = [...allServers];
        if (missingServers.length > 0) {
            showAlert(`Серверы не найдены в Xray Checker: ${missingServers.join(', ')}`, 'error');
        }
        renderServers();
        updateStats();
        console.log('Servers loaded:', allServers.length);
        showToast(`Загружено ${allServers.length} серверов`, 'success');
    } catch (error) {
        console.error('Error loading servers:', error);
        showToast('Ошибка загрузки серверов: ' + error.message, 'error');
        allServers = [];
        filteredServers = [];
        renderServers();
        updateStats();
    }
}

async function loadScripts() {
    try {
        const response = await fetch('/api/scripts');
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        const data = await response.json();
        availableScripts = data.scripts || [];
        populateScriptSelect();
        console.log('Scripts loaded:', availableScripts.length);
    } catch (error) {
        console.error('Error loading scripts:', error);
        showToast('Ошибка загрузки скриптов: ' + error.message, 'error');
        document.getElementById('scriptSelect').innerHTML = '<option value="">Ошибка загрузки скриптов</option>';
    }
}

function populateScriptSelect() {
    const select = document.getElementById('scriptSelect');
    if (availableScripts.length === 0) {
        select.innerHTML = '<option value="">Скрипты не найдены</option>';
        return;
    }
    select.innerHTML = '<option value="">Выберите скрипт...</option>' + 
        availableScripts.map(script => `<option value="${script}">${script}</option>`).join('');
}

function setupEventListeners() {
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.action-menu-button') && !e.target.closest('.dropdown-menu')) {
            closeDropdown();
        }
    });
    document.getElementById('modalOverlay').addEventListener('click', (e) => {
        if (e.target === e.currentTarget) closeModal();
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') { closeDropdown(); closeModal(); }
        if (e.key === 'Delete' && selectedServers.size > 0) bulkDelete();
        if (e.ctrlKey && e.key === 'a') { e.preventDefault(); selectAllServers(); }
    });
}

function setupSearch() {
    const searchInput = document.getElementById('searchInput');
    let searchTimeout;
    searchInput.addEventListener('input', (e) => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => filterServers(e.target.value), 300);
    });
}

function filterServers(query) {
    if (!query.trim()) {
        filteredServers = [...allServers];
    } else {
        const searchTerm = query.toLowerCase();
        filteredServers = allServers.filter(server => 
            server.ip.toLowerCase().includes(searchTerm) ||
            server.inbound.toLowerCase().includes(searchTerm) ||
            formatDate(server.install_date).toLowerCase().includes(searchTerm) ||
            getStatusText(server.status).toLowerCase().includes(searchTerm)
        );
    }
    renderServers();
    updateStats();
}

function renderServers() {
    const tbody = document.getElementById('serversTableBody');
    if (!filteredServers.length) {
        tbody.innerHTML = `
            <tr>
                <td colspan="6" class="empty-state">
                    <svg class="empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2"/>
                    </svg>
                    <div class="empty-title">Серверы не найдены</div>
                    <div class="empty-description">Попробуйте изменить условия поиска или добавьте новый сервер</div>
                </td>
            </tr>
        `;
        return;
    }
    tbody.innerHTML = filteredServers.map(server => `
        <tr class="${selectedServers.has(server.ip) ? 'selected' : ''}" data-ip="${server.ip}">
            <td class="checkbox-cell">
                <label class="custom-checkbox">
                    <input type="checkbox" ${selectedServers.has(server.ip) ? 'checked' : ''} onchange="toggleServerSelection('${server.ip}')">
                    <span class="checkmark"></span>
                </label>
            </td>
            <td><div class="server-ip">${server.ip}</div></td>
            <td>${server.inbound}</td>
            <td>
                <span class="server-status status-${server.status}">
                    <span class="status-dot"></span> ${getStatusText(server.status)}
                </span>
            </td>
            <td>${formatDate(server.install_date)}</td>
            <td class="actions-cell">
                <button class="action-menu-button" onclick="toggleDropdown(this, '${server.ip}')">
                    <svg style="width: 16px; height: 16px;" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 5v.01M12 12v.01M12 19v.01M12 6a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2z"/>
                    </svg>
                </button>
            </td>
        </tr>
    `).join('');
    updateSelectionUI();
}

function getStatusText(status) {
    switch (status) {
        case 'online': return 'Онлайн';
        case 'offline': return 'Офлайн';
        default: return 'Неизвестно';
    }
}

function toggleServerSelection(ip) {
    if (selectedServers.has(ip)) selectedServers.delete(ip);
    else selectedServers.add(ip);
    updateSelectionUI();
    updateRunButton();
}

function toggleSelectAll() {
    const selectAllCheckbox = document.getElementById('selectAll');
    if (selectAllCheckbox.checked) selectAllServers();
    else clearSelection();
}

function selectAllServers() {
    filteredServers.forEach(server => selectedServers.add(server.ip));
    updateSelectionUI();
    updateRunButton();
}

function clearSelection() {
    selectedServers.clear();
    updateSelectionUI();
    updateRunButton();
}

function updateSelectionUI() {
    const selectAllCheckbox = document.getElementById('selectAll');
    const selectedCount = selectedServers.size;
    const visibleCount = filteredServers.length;
    if (selectedCount === 0) {
        selectAllCheckbox.checked = false;
        selectAllCheckbox.indeterminate = false;
    } else if (selectedCount === visibleCount && visibleCount > 0) {
        selectAllCheckbox.checked = true;
        selectAllCheckbox.indeterminate = false;
    } else {
        selectAllCheckbox.checked = false;
        selectAllCheckbox.indeterminate = true;
    }
    document.querySelectorAll('tbody tr').forEach(row => {
        const ip = row.dataset.ip;
        if (ip) {
            const isSelected = selectedServers.has(ip);
            row.classList.toggle('selected', isSelected);
            const checkbox = row.querySelector('input[type="checkbox"]');
            if (checkbox) checkbox.checked = isSelected;
        }
    });
    updateStats();
    updateSelectedActions();
}

function updateSelectedActions() {
    const selectedActions = document.getElementById('selectedActions');
    const selectedCount = document.getElementById('selectedCount');
    selectedCount.textContent = `${selectedServers.size} выбрано`;
    if (selectedServers.size > 0) selectedActions.classList.add('visible');
    else selectedActions.classList.remove('visible');
}

function updateRunButton() {
    const runScriptButton = document.getElementById('runScriptButton');
    const runButtonText = document.getElementById('runButtonText');
    const scriptSelect = document.getElementById('scriptSelect');
    runScriptButton.disabled = !(selectedServers.size > 0 && scriptSelect.value);
    if (scriptSelect.value) {
        runButtonText.textContent = `Запустить ${scriptSelect.options[scriptSelect.selectedIndex].text}`;
    } else {
        runButtonText.textContent = 'Запустить скрипт';
    }
}

function updateStats() {
    const totalServers = document.getElementById('totalServers');
    const onlineServers = document.getElementById('onlineServers');
    const selectedServersCount = document.getElementById('selectedServers');
    const onlineCount = allServers.filter(s => s.status === 'online').length;
    totalServers.textContent = allServers.length;
    onlineServers.textContent = onlineCount;
    selectedServersCount.textContent = selectedServers.size;
}

function sortTable(field) {
    const direction = currentSort.field === field && currentSort.direction === 'asc' ? 'desc' : 'asc';
    document.querySelectorAll('th').forEach(th => th.classList.remove('active', 'asc', 'desc'));
    const clickedTh = event.target.closest('th');
    clickedTh.classList.add('active', direction);
    filteredServers.sort((a, b) => {
        let aVal = a[field];
        let bVal = b[field];
        if (field === 'install_date') {
            aVal = new Date(aVal);
            bVal = new Date(bVal);
        } else if (typeof aVal === 'string') {
            aVal = aVal.toLowerCase();
            bVal = bVal.toLowerCase();
        }
        if (direction === 'asc') return aVal > bVal ? 1 : -1;
        return aVal < bVal ? 1 : -1;
    });
    currentSort = { field, direction };
    renderServers();
}

function toggleDropdown(button, ip) {
    const dropdown = document.getElementById('dropdownMenu');
    const wasActive = dropdown.classList.contains('active');
    closeDropdown();
    if (!wasActive) {
        const rect = button.getBoundingClientRect();
        let top = rect.bottom + window.scrollY + 8;
        let left = rect.right + window.scrollX - 200;
        if (left < 0) left = rect.left + window.scrollX;
        if (top + 120 > window.innerHeight + window.scrollY) {
            top = rect.top + window.scrollY - 120 - 8;
        }
        dropdown.style.top = `${top}px`;
        dropdown.style.left = `${left}px`;
        dropdown.classList.add('active');
        document.getElementById('runScriptAction').onclick = () => {
            showRunScriptModal([ip]);
            closeDropdown();
        };
        document.getElementById('editAction').onclick = () => {
            editServer(ip);
            closeDropdown();
        };
        document.getElementById('deleteAction').onclick = () => {
            showDeleteModal([ip]);
            closeDropdown();
        };
    }
}

function closeDropdown() {
    document.getElementById('dropdownMenu').classList.remove('active');
}

function formatDate(dateString) {
    if (!dateString) return 'Не указана';
    try {
        const date = new Date(dateString);
        return date.toLocaleDateString('ru-RU', {
            year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'
        });
    } catch (e) {
        return 'Неверная дата';
    }
}

function editServer(ip) {
    showToast(`Редактирование сервера ${ip} (функция в разработке)`, 'info');
}

async function runScript(ip, scriptName) {
    try {
        showToast(`Запуск скрипта ${scriptName} на сервере ${ip}...`, 'info');
        const response = await fetch('/api/run_scripts', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ips: [ip], script_name: scriptName })
        });
        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || 'Ошибка запуска скрипта');
        }
        const result = await response.json();
        const success = result.results[0].success;
        const message = result.results[0].message;
        if (success) {
            showToast(`Скрипт ${scriptName} успешно выполнен на ${ip}`, 'success');
        } else {
            throw new Error(message);
        }
    } catch (error) {
        console.error('Error running script:', error);
        showToast(`Ошибка запуска скрипта ${scriptName} на ${ip}: ${error.message}`, 'error');
    }
}

async function bulkRunScript() {
    if (selectedServers.size === 0) return;
    const serverList = Array.from(selectedServers);
    const scriptSelect = document.getElementById('scriptSelect');
    const scriptName = scriptSelect.value;
    if (!scriptName) {
        showToast('Выберите скрипт для запуска', 'error');
        return;
    }
    const runScriptButton = document.getElementById('runScriptButton');
    runScriptButton.classList.add('loading');
    runScriptButton.disabled = true;
    try {
        showToast(`Запуск скрипта ${scriptName} на ${serverList.length} серверах...`, 'info');
        const response = await fetch('/api/run_scripts', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ips: serverList, script_name: scriptName })
        });
        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || 'Ошибка массового запуска скрипта');
        }
        const data = await response.json();
        const results = data.results || [];
        let successCount = 0;
        let errorCount = 0;
        results.forEach(result => {
            if (result.success) successCount++;
            else {
                console.error(`Error running script on ${result.ip}: ${result.message}`);
                errorCount++;
            }
        });
        if (successCount > 0 && errorCount === 0) {
            showToast(`${successCount} серверов успешно обработаны`, 'success');
        } else if (successCount > 0 && errorCount > 0) {
            showToast(`Выполнено: ${successCount}, ошибок: ${errorCount}`, 'error');
        } else {
            showToast(`Ошибка выполнения скрипта: ${errorCount} ошибок`, 'error');
        }
        clearSelection();
    } catch (error) {
        console.error('Error in bulk script execution:', error);
        showToast('Ошибка при массовом запуске скрипта', 'error');
    } finally {
        runScriptButton.classList.remove('loading');
        runScriptButton.disabled = false;
    }
}

function showRunScriptModal(ips) {
    const modal = document.getElementById('modalOverlay');
    const title = document.getElementById('modalTitle');
    const description = document.getElementById('modalDescription');
    const confirmButton = document.getElementById('modalConfirmButton');
    const isMultiple = ips.length > 1;
    title.textContent = isMultiple ? 'Запустить скрипт на серверах' : 'Запустить скрипт на сервере';
    description.textContent = isMultiple 
        ? `Выберите скрипт для запуска на ${ips.length} серверах:`
        : `Выберите скрипт для запуска на сервере ${ips[0]}:`;
    confirmButton.textContent = 'Запустить';
    confirmButton.classList.remove('danger');
    confirmButton.classList.add('primary');
    currentModalAction = 'run_script';
    currentModalData = ips;
    const existingSelect = document.getElementById('modalScriptSelect');
    if (existingSelect) existingSelect.remove();
    const scriptSelect = document.createElement('select');
    scriptSelect.id = 'modalScriptSelect';
    scriptSelect.className = 'form-select';
    scriptSelect.innerHTML = '<option value="">Выберите скрипт...</option>' + 
        availableScripts.map(script => `<option value="${script}">${script}</option>`).join('');
    description.insertAdjacentElement('afterend', scriptSelect);
    modal.classList.add('active');
}

function showDeleteModal(ips) {
    const modal = document.getElementById('modalOverlay');
    const title = document.getElementById('modalTitle');
    const description = document.getElementById('modalDescription');
    const confirmButton = document.getElementById('modalConfirmButton');
    const isMultiple = ips.length > 1;
    title.textContent = isMultiple ? 'Удалить серверы' : 'Удалить сервер';
    description.textContent = isMultiple 
        ? `Вы уверены, что хотите удалить ${ips.length} серверов? Это действие нельзя отменить.`
        : `Вы уверены, что хотите удалить сервер ${ips[0]}? Это действие нельзя отменить.`;
    confirmButton.textContent = isMultiple ? 'Удалить серверы' : 'Удалить сервер';
    confirmButton.classList.add('danger');
    confirmButton.classList.remove('primary');
    currentModalAction = 'delete';
    currentModalData = ips;
    const existingSelect = document.getElementById('modalScriptSelect');
    if (existingSelect) existingSelect.remove();
    modal.classList.add('active');
}

function closeModal() {
    document.getElementById('modalOverlay').classList.remove('active');
    currentModalAction = null;
    currentModalData = null;
    const existingSelect = document.getElementById('modalScriptSelect');
    if (existingSelect) existingSelect.remove();
}

async function confirmModalAction() {
    if (currentModalAction === 'run_script' && currentModalData) {
        const scriptSelect = document.getElementById('modalScriptSelect');
        const scriptName = scriptSelect ? scriptSelect.value : null;
        if (!scriptName) {
            showToast('Выберите скрипт для запуска', 'error');
            return;
        }
        const serverList = currentModalData;
        if (serverList.length === 1) {
            await runScript(serverList[0], scriptName);
        } else {
            await bulkRunScriptWithScript(serverList, scriptName);
        }
    } else if (currentModalAction === 'delete' && currentModalData) {
        await deleteServers(currentModalData);
    }
    closeModal();
}

async function bulkRunScriptWithScript(serverList, scriptName) {
    const runScriptButton = document.getElementById('runScriptButton');
    runScriptButton.classList.add('loading');
    runScriptButton.disabled = true;
    try {
        showToast(`Запуск скрипта ${scriptName} на ${serverList.length} серверах...`, 'info');
        const response = await fetch('/api/run_scripts', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ips: serverList, script_name: scriptName })
        });
        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || 'Ошибка массового запуска скрипта');
        }
        const data = await response.json();
        const results = data.results || [];
        let successCount = 0;
        let errorCount = 0;
        results.forEach(result => {
            if (result.success) successCount++;
            else {
                console.error(`Error running script on ${result.ip}: ${result.message}`);
                errorCount++;
            }
        });
        if (successCount > 0 && errorCount === 0) {
            showToast(`${successCount} серверов успешно обработаны`, 'success');
        } else if (successCount > 0 && errorCount > 0) {
            showToast(`Выполнено: ${successCount}, ошибок: ${errorCount}`, 'error');
        } else {
            showToast(`Ошибка выполнения скрипта: ${errorCount} ошибок`, 'error');
        }
        clearSelection();
    } catch (error) {
        console.error('Error in bulk script execution:', error);
        showToast('Ошибка при массовом запуске скрипта', 'error');
    } finally {
        runScriptButton.classList.remove('loading');
        runScriptButton.disabled = false;
    }
}

async function deleteServers(ips) {
    try {
        showToast(`Удаление ${ips.length} серверов...`, 'info');
        const results = await Promise.allSettled(
            ips.map(ip => fetch(`/api/delete_server?ip=${encodeURIComponent(ip)}`, { method: 'DELETE' }))
        );
        const successCount = results.filter(r => r.status === 'fulfilled' && r.value.ok).length;
        const failCount = results.length - successCount;
        if (successCount > 0) {
            const successfullyDeleted = [];
            results.forEach((result, index) => {
                if (result.status === 'fulfilled' && result.value.ok) successfullyDeleted.push(ips[index]);
            });
            allServers = allServers.filter(server => !successfullyDeleted.includes(server.ip));
            filteredServers = filteredServers.filter(server => !successfullyDeleted.includes(server.ip));
            successfullyDeleted.forEach(ip => selectedServers.delete(ip));
            renderServers();
            updateStats();
            updateSelectedActions();
        }
        if (failCount === 0) {
            showToast(`${ips.length} серверов успешно удалены`, 'success');
        } else {
            showToast(`Удалено: ${successCount}, ошибок: ${failCount}`, 'error');
        }
    } catch (error) {
        console.error('Error deleting servers:', error);
        showToast('Ошибка при удалении серверов', 'error');
    }
}

function bulkDelete() {
    if (selectedServers.size === 0) return;
    showDeleteModal(Array.from(selectedServers));
}

function showAlert(message, type = 'info') {
    const alert = document.getElementById('alert');
    if (alert) {
        alert.textContent = message;
        alert.className = `alert ${type}`;
        setTimeout(() => {
            alert.className = 'alert';
        }, 5000);
    } else {
        showToast(message, type);
    }
}

function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
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
        setTimeout(() => {
            if (container.contains(toast)) container.removeChild(toast);
        }, 300);
    }, 4000);
}

function toggleTheme() {
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

function loadTheme() {
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme === 'dark') {
        document.documentElement.setAttribute('data-theme', 'dark');
    }
}
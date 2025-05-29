let allServers = [];
let filteredServers = [];
let selectedServers = new Set();
let currentSort = { field: null, direction: 'asc' };
let currentModalAction = null;
let currentModalData = null;
let availableScripts = [];

document.addEventListener('DOMContentLoaded', () => {
    console.log('server_list.js loaded');
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
    console.log('Setting up event listeners');
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
    const rebootButton = document.getElementById('rebootSelectedButton');
    if (rebootButton) {
        rebootButton.addEventListener('click', () => {
            console.log('Reboot selected button clicked');
            bulkReboot();
        });
    } else {
        console.error('Reboot selected button not found');
    }
}

function setupSearch() {
    console.log('Setting up search');
    const searchInput = document.getElementById('searchInput');
    let searchTimeout;
    searchInput.addEventListener('input', (e) => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => filterServers(e.target.value), 300);
    });
}

function filterServers(query) {
    console.log('Filtering servers with query:', query);
    if (!query.trim()) {
        filteredServers = [...allServers];
    } else {
        const searchTerm = query.toLowerCase();
        filteredServers = allServers.filter(server => 
            server.ip.toLowerCase().includes(searchTerm) ||
            server.inbound_tag.toLowerCase().includes(searchTerm) ||
            formatDate(server.install_date).toLowerCase().includes(searchTerm) ||
            getStatusText(server.status).toLowerCase().includes(searchTerm)
        );
    }
    renderServers();
    updateStats();
}

function renderServers() {
    console.log('Rendering servers:', filteredServers.length);
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
            <td>${server.inbound_tag}</td>
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
    console.log('Toggling selection for IP:', ip, 'Current selected:', Array.from(selectedServers));
    if (selectedServers.has(ip)) selectedServers.delete(ip);
    else selectedServers.add(ip);
    console.log('After toggle, selected:', Array.from(selectedServers));
    updateSelectionUI();
    updateRunButton();
    updateRebootButton();
}

function toggleSelectAll() {
    console.log('Toggling select all');
    const selectAllCheckbox = document.getElementById('selectAll');
    if (selectAllCheckbox.checked) selectAllServers();
    else clearSelection();
}

function selectAllServers() {
    console.log('Selecting all servers');
    filteredServers.forEach(server => selectedServers.add(server.ip));
    console.log('All selected:', Array.from(selectedServers));
    updateSelectionUI();
    updateRunButton();
    updateRebootButton();
}

function clearSelection() {
    console.log('Clearing selection');
    selectedServers.clear();
    console.log('Selection cleared:', Array.from(selectedServers));
    updateSelectionUI();
    updateRunButton();
    updateRebootButton();
}

function updateSelectionUI() {
    console.log('Updating selection UI, selected count:', selectedServers.size);
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
    console.log('Updating selected actions');
    const selectedActions = document.getElementById('selectedActions');
    const selectedCount = document.getElementById('selectedCount');
    selectedCount.textContent = `${selectedServers.size} выбрано`;
    if (selectedServers.size > 0) selectedActions.classList.add('visible');
    else selectedActions.classList.remove('visible');
}

function updateRunButton() {
    console.log('Updating run button');
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

function updateRebootButton() {
    console.log('Updating reboot button, selected count:', selectedServers.size);
    const rebootButton = document.getElementById('rebootSelectedButton');
    if (rebootButton) {
        rebootButton.disabled = selectedServers.size === 0;
        console.log('Reboot button disabled:', rebootButton.disabled);
    } else {
        console.error('Reboot button not found');
    }
}

function updateStats() {
    console.log('Updating stats');
    const totalServers = document.getElementById('totalServers');
    const onlineServers = document.getElementById('onlineServers');
    const selectedServersCount = document.getElementById('selectedServers');
    const onlineCount = allServers.filter(s => s.status === 'online').length;
    totalServers.innerHTML = totalServers.classList.contains('loading') ? allServers.length : totalServers.innerHTML.replace(/<span class="loading">.*<\/span>/, allServers.length);
    onlineServers.innerHTML = onlineServers.classList.contains('loading') ? onlineCount : onlineServers.innerHTML.replace(/<span class="loading">.*<\/span>/, onlineCount);
    selectedServersCount.textContent = selectedServers.size;
}

function sortTable(field) {
    console.log('Sorting table by:', field);
    const direction = currentSort.field === field && currentSort.direction === 'asc' ? 'desc' : 'asc';
    document.querySelectorAll('th.sortable').forEach(th => th.classList.remove('active', 'asc', 'desc'));
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
    console.log('Toggling dropdown for IP:', ip);
    const dropdown = document.getElementById('dropdownMenu');
    const wasActive = dropdown.classList.contains('active');
    closeDropdown();
    if (!wasActive) {
        const rect = button.getBoundingClientRect();
        let top = rect.bottom + window.scrollY + 8;
        let left = rect.right + window.scrollX - 200;
        if (left < 0) left = rect.left + window.scrollX;
        if (top + 200 > window.innerHeight + window.scrollY) {
            top = rect.top + window.scrollY - 200 - 8;
        }
        dropdown.style.top = `${top}px`;
        dropdown.style.left = `${left}px`;
        dropdown.classList.add('active');
        console.log('Dropdown opened for IP:', ip);
        document.getElementById('runScriptAction').onclick = () => {
            console.log('Run script action clicked for IP:', ip);
            showRunScriptModal([ip]);
            closeDropdown();
        };
        document.getElementById('editAction').onclick = () => {
            console.log('Edit action clicked for IP:', ip);
            showEditServerModal(ip);
            closeDropdown();
        };
        document.getElementById('rebootAction').onclick = () => {
            console.log('Reboot action clicked for IP:', ip);
            rebootServer(ip);
            closeDropdown();
        };
        document.getElementById('deleteAction').onclick = () => {
            console.log('Delete action clicked for IP:', ip);
            showDeleteModal([ip]);
            closeDropdown();
        };
    }
}

function closeDropdown() {
    console.log('Closing dropdown');
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

async function runScript(ip, scriptName) {
    console.log('Running script:', scriptName, 'on IP:', ip);
    try {
        showToast(`Запуск скрипта ${scriptName} на сервере ${ip}...`, 'info');
        const response = await fetch('/api/run_scripts', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ips: [ip], script_name: scriptName })
        });
        console.log('Run script response status:', response.status);
        if (!response.ok) {
            const errorData = await response.json();
            console.error('Run script error data:', errorData);
            throw new Error(errorData.detail || 'Ошибка запуска скрипта');
        }
        const result = await response.json();
        console.log('Run script result:', result);
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

async function rebootServer(ip) {
    console.log('Rebooting server:', ip);
    try {
        showToast(`Перезагрузка сервера ${ip}...`, 'info');
        const response = await fetch('/api/reboot_servers', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ips: [ip] })
        });
        console.log('Reboot response status:', response.status);
        if (!response.ok) {
            const errorData = await response.json();
            console.error('Reboot error data:', errorData);
            throw new Error(errorData.detail || 'Ошибка перезагрузки сервера');
        }
        const result = await response.json();
        console.log('Reboot result:', result);
        const success = result.results[0].success;
        const message = result.results[0].message;
        if (success) {
            showToast(`Сервер ${ip} успешно перезагружен`, 'success');
        } else {
            throw new Error(message);
        }
    } catch (error) {
        console.error('Error rebooting server:', error);
        showToast(`Ошибка перезагрузки сервера ${ip}: ${error.message}`, 'error');
    }
}

async function bulkRunScript() {
    console.log('Running bulk script');
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
        console.log('Bulk run script response status:', response.status);
        if (!response.ok) {
            const errorData = await response.json();
            console.error('Bulk run script error data:', errorData);
            throw new Error(errorData.detail || 'Ошибка массового запуска скрипта');
        }
        const data = await response.json();
        console.log('Bulk run script result:', data);
        const results = data.results || [];
        let successCount = 0;
        let errorCount = 0;
        let errorMessages = [];
        results.forEach(result => {
            if (result.success) {
                successCount++;
            } else {
                errorCount++;
                errorMessages.push(`Сервер ${result.ip}: ${result.message}`);
                console.error(`Error running script on ${result.ip}: ${result.message}`);
            }
        });
        if (successCount > 0 && errorCount === 0) {
            showToast(`${successCount} серверов успешно обработаны`, 'success');
        } else if (successCount > 0 && errorCount > 0) {
            showToast(`Выполнено: ${successCount}, ошибок: ${errorCount}. ${errorMessages.join('; ')}`, 'error');
        } else {
            showToast(`Ошибка выполнения скрипта: ${errorCount} ошибок. ${errorMessages.join('; ')}`, 'error');
        }
        clearSelection();
    } catch (error) {
        console.error('Error in bulk script execution:', error);
        showToast('Ошибка при массовом запуске скрипта: ' + error.message, 'error');
    } finally {
        runScriptButton.classList.remove('loading');
        runScriptButton.disabled = false;
    }
}

async function bulkReboot() {
    console.log('Running bulk reboot, selected servers:', Array.from(selectedServers));
    if (selectedServers.size === 0) {
        console.warn('No servers selected for bulk reboot');
        showToast('Выберите хотя бы один сервер', 'error');
        return;
    }
    const serverList = Array.from(selectedServers);
    console.log('Server list for reboot:', serverList);
    const rebootButton = document.getElementById('rebootSelectedButton');
    rebootButton.classList.add('loading');
    rebootButton.disabled = true;
    try {
        showToast(`Перезагрузка ${serverList.length} серверов...`, 'info');
        const response = await fetch('/api/reboot_servers', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ips: serverList })
        });
        console.log('Bulk reboot response status:', response.status);
        if (!response.ok) {
            const errorData = await response.json();
            console.error('Bulk reboot error data:', errorData);
            throw new Error(errorData.detail || 'Ошибка массовой перезагрузки');
        }
        const data = await response.json();
        console.log('Bulk reboot result:', data);
        const results = data.results || [];
        let successCount = 0;
        let errorCount = 0;
        let errorMessages = [];
        results.forEach(result => {
            if (result.success) {
                successCount++;
            } else {
                errorCount++;
                errorMessages.push(`Сервер ${result.ip}: ${result.message}`);
                console.error(`Error rebooting server ${result.ip}: ${result.message}`);
            }
        });
        if (successCount > 0 && errorCount === 0) {
            showToast(`${successCount} серверов успешно перезагружены`, 'success');
        } else if (successCount > 0 && errorCount > 0) {
            showToast(`Перезагружено: ${successCount}, ошибок: ${errorCount}. ${errorMessages.join('; ')}`, 'error');
        } else {
            showToast(`Ошибка перезагрузки: ${errorCount} ошибок. ${errorMessages.join('; ')}`, 'error');
        }
        clearSelection();
    } catch (error) {
        console.error('Error in bulk reboot:', error);
        showToast('Ошибка при массовой перезагрузке: ' + error.message, 'error');
    } finally {
        rebootButton.classList.remove('loading');
        rebootButton.disabled = false;
        updateRebootButton();
    }
}

async function showRunScriptModal(ips) {
    console.log('Showing run script modal for IPs:', ips);
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
    const existingInputs = document.getElementById('modalInputs');
    if (existingSelect) existingSelect.remove();
    if (existingInputs) existingInputs.remove();
    const scriptSelect = document.createElement('select');
    scriptSelect.id = 'modalScriptSelect';
    scriptSelect.className = 'form-select';
    scriptSelect.innerHTML = '<option value="">Выберите скрипт...</option>' + 
        availableScripts.map(script => `<option value="${script}">${script}</option>`).join('');
    description.insertAdjacentElement('afterend', scriptSelect);
    modal.classList.add('active');
}

async function showEditServerModal(ip) {
    console.log('Showing edit server modal for IP:', ip);
    const modal = document.getElementById('modalOverlay');
    const title = document.getElementById('modalTitle');
    const description = document.getElementById('modalDescription');
    const confirmButton = document.getElementById('modalConfirmButton');
    title.textContent = 'Редактировать сервер';
    description.textContent = `Редактируйте данные сервера ${ip}:`;
    confirmButton.textContent = 'Сохранить';
    confirmButton.classList.remove('danger');
    confirmButton.classList.add('primary');
    currentModalAction = 'edit_server';
    currentModalData = ip;

    const server = allServers.find(s => s.ip === ip);
    if (!server) {
        console.error('Server not found:', ip);
        showToast('Сервер не найден', 'error');
        return;
    }
    const existingSelect = document.getElementById('modalScriptSelect');
    const existingInputs = document.getElementById('modalInputs');
    if (existingSelect) existingSelect.remove();
    if (existingInputs) existingInputs.remove();
    
    let inboundTags = [];
    try {
        const response = await fetch('/api/inbound_tags');
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        const data = await response.json();
        inboundTags = data.tags || [];
        console.log('Inbound tags loaded:', inboundTags);
    } catch (error) {
        console.error('Error fetching inbound tags:', error);
        showToast('Ошибка загрузки тегов: ' + error.message, 'error');
    }
    
    const inputsDiv = document.createElement('div');
    inputsDiv.id = 'modalInputs';
    inputsDiv.innerHTML = `
        <div class="form-group">
            <label for="editIpInput">IP адрес:</label>
            <input type="text" id="editIpInput" class="form-input" value="${server.ip}" required>
        </div>
        <div class="form-group">
            <label for="editInboundTagInput">Inbound Tag:</label>
            <select id="editInboundTagInput" class="form-select" required>
                <option value="">Выберите тег...</option>
                ${inboundTags.map(tag => `<option value="${tag}" ${tag === server.inbound_tag ? 'selected' : ''}>${tag}</option>`).join('')}
            </select>
        </div>
    `;
    description.insertAdjacentElement('afterend', inputsDiv);
    modal.classList.add('active');
}

function showDeleteModal(ips) {
    console.log('Showing delete modal for IPs:', ips);
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
    const existingInputs = document.getElementById('modalInputs');
    if (existingSelect) existingSelect.remove();
    if (existingInputs) existingInputs.remove();
    modal.classList.add('active');
}

function closeModal() {
    console.log('Closing modal');
    document.getElementById('modalOverlay').classList.remove('active');
    currentModalAction = null;
    currentModalData = null;
    const existingSelect = document.getElementById('modalScriptSelect');
    const existingInputs = document.getElementById('modalInputs');
    if (existingSelect) existingSelect.remove();
    if (existingInputs) existingInputs.remove();
}

async function confirmModalAction() {
    console.log('Confirming modal action:', currentModalAction);
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
    } else if (currentModalAction === 'edit_server' && currentModalData) {
        const ipInput = document.getElementById('editIpInput');
        const inboundTagInput = document.getElementById('editInboundTagInput');
        if (!ipInput.value || !inboundTagInput.value) {
            showToast('Заполните все поля', 'error');
            return;
        }
        await editServer(currentModalData, ipInput.value, inboundTagInput.value);
    } else if (currentModalAction === 'delete' && currentModalData) {
        await deleteServers(currentModalData);
    }
    closeModal();
}

async function bulkRunScriptWithScript(serverList, scriptName) {
    console.log('Running bulk script with:', scriptName, 'on servers:', serverList);
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
        console.log('Bulk run script response status:', response.status);
        if (!response.ok) {
            const errorData = await response.json();
            console.error('Bulk run script error data:', errorData);
            throw new Error(errorData.detail || 'Ошибка массового запуска скрипта');
        }
        const data = await response.json();
        console.log('Bulk run script result:', data);
        const results = data.results || [];
        let successCount = 0;
        let errorCount = 0;
        let errorMessages = [];
        results.forEach(result => {
            if (result.success) {
                successCount++;
            } else {
                errorCount++;
                errorMessages.push(`Сервер ${result.ip}: ${result.message}`);
                console.error(`Error running script on ${result.ip}: ${result.message}`);
            }
        });
        if (successCount > 0 && errorCount === 0) {
            showToast(`${successCount} серверов успешно обработаны`, 'success');
        } else if (successCount > 0 && errorCount > 0) {
            showToast(`Выполнено: ${successCount}, ошибок: ${errorCount}. ${errorMessages.join('; ')}`, 'error');
        } else {
            showToast(`Ошибка выполнения скрипта: ${errorCount} ошибок. ${errorMessages.join('; ')}`, 'error');
        }
        clearSelection();
    } catch (error) {
        console.error('Error in bulk script execution:', error);
        showToast('Ошибка при массовом запуске скрипта: ' + error.message, 'error');
    } finally {
        runScriptButton.classList.remove('loading');
        runScriptButton.disabled = false;
    }
}

async function editServer(oldIp, newIp, newInboundTag) {
    console.log('Editing server:', oldIp, 'to new IP:', newIp, 'new inbound tag:', newInboundTag);
    try {
        showToast(`Сохранение изменений для сервера ${oldIp}...`, 'info');
        const response = await fetch('/api/edit_server', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ old_ip: oldIp, new_ip: newIp, new_inbound_tag: newInboundTag })
        });
        console.log('Edit response status:', response.status);
        if (!response.ok) {
            const errorData = await response.json();
            console.error('Edit error data:', errorData);
            throw new Error(errorData.detail || 'Ошибка редактирования сервера');
        }
        const result = await response.json();
        console.log('Edit result:', result);
        if (result.success) {
            showToast(`Сервер ${oldIp} успешно обновлён`, 'success');
            const serverIndex = allServers.findIndex(s => s.ip === oldIp);
            if (serverIndex !== -1) {
                allServers[serverIndex].ip = newIp;
                allServers[serverIndex].inbound_tag = newInboundTag;
            }
            filteredServers = [...allServers];
            renderServers();
            updateStats();
        } else {
            throw new Error(result.message);
        }
    } catch (error) {
        console.error('Error editing server:', error);
        showToast(`Ошибка редактирования сервера ${oldIp}: ${error.message}`, 'error');
    }
}

async function deleteServers(ips) {
    console.log('Deleting servers:', ips);
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
    console.log('Running bulk delete');
    if (selectedServers.size === 0) return;
    showDeleteModal(Array.from(selectedServers));
}

function showAlert(message, type = 'info') {
    console.log('Showing alert:', message, type);
    const toastContainer = document.getElementById('toastContainer');
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
    toastContainer.appendChild(toast);
    setTimeout(() => toast.classList.add('show'), 100);
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => {
            if (toastContainer.contains(toast)) toastContainer.removeChild(toast);
        }, 300);
    }, 4000);
}

function showToast(message, type = 'info') {
    showAlert(message, type);
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

function loadTheme() {
    console.log('Loading theme');
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme === 'dark') {
        document.documentElement.setAttribute('data-theme', 'dark');
    }
}
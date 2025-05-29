let availableInbounds = [];
let ipTags = [];

document.addEventListener('DOMContentLoaded', () => {
    console.log('setup_server.js: DOM loaded');
    loadInbounds();
    setupEventListeners();
    setupIPTagsInput();
    loadTheme();
});

async function loadInbounds() {
    try {
        console.log('setup_server.js: Fetching /api/vless_keys');
        const response = await fetch('/api/vless_keys');
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data = await response.json();
        console.log('setup_server.js: Received vless_keys:', data);
        availableInbounds = data.data || [];
        populateInboundSelect();
    } catch (error) {
        console.error('setup_server.js: Error loading locations:', error);
        showToast('Ошибка загрузки локаций: ' + error.message, 'error');
        const select = document.getElementById('inbound');
        select.innerHTML = '<option value="">Ошибка загрузки локаций</option>';
    }
}

function populateInboundSelect() {
    const select = document.getElementById('inbound');
    if (availableInbounds.length === 0) {
        select.innerHTML = '<option value="">Локации не найдены</option>';
        return;
    }
    select.innerHTML = '<option value="">Выберите локацию...</option>' + 
        availableInbounds.map(inbound => 
            `<option value="${inbound.inbound_tag}">${inbound.inbound_tag}</option>`
        ).join('');
}

function setupEventListeners() {
    console.log('setup_server.js: Setting up event listeners');
    const form = document.getElementById('setupServerForm');
    if (form) {
        console.log('setup_server.js: Form element found:', form);
        form.addEventListener('submit', handleSubmit);
    } else {
        console.error('setup_server.js: Form element with ID "setupServerForm" not found');
        showToast('Ошибка: форма не найдена на странице', 'error');
        // Log all forms to debug
        const forms = document.getElementsByTagName('form');
        console.log('setup_server.js: Available forms:', forms.length, Array.from(forms).map(f => f.id));
    }
}

function setupIPTagsInput() {
    console.log('setup_server.js: Setting up IP tags input');
    const container = document.getElementById('ipTagsInput');
    const input = document.getElementById('ipInput');
    if (!container || !input) {
        console.error('setup_server.js: IP tags input or container not found');
        showToast('Ошибка: элементы ввода IP не найдены', 'error');
        return;
    }

    function createIPTag(ip) {
        const tag = document.createElement('div');
        tag.className = 'ip-tag';
        const ipText = document.createElement('span');
        ipText.textContent = ip;
        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'ip-tag-remove';
        removeBtn.innerHTML = '×';
        removeBtn.onclick = (e) => {
            e.preventDefault();
            removeIPTag(ip);
        };
        tag.appendChild(ipText);
        tag.appendChild(removeBtn);
        return tag;
    }

    function addIPTag(ip) {
        ip = ip.trim();
        if (!ip) return;
        if (ipTags.includes(ip)) {
            showToast(`IP ${ip} уже добавлен`, 'error');
            return;
        }
        ipTags.push(ip);
        const tag = createIPTag(ip);
        container.insertBefore(tag, input);
        updateUI();
        input.value = '';
    }

    function removeIPTag(ip) {
        const index = ipTags.indexOf(ip);
        if (index > -1) {
            ipTags.splice(index, 1);
            const tagElements = container.querySelectorAll('.ip-tag');
            tagElements.forEach(tag => {
                if (tag.querySelector('span').textContent === ip) {
                    tag.remove();
                }
            });
            updateUI();
        }
    }

    function updateUI() {
        const count = ipTags.length;
        document.getElementById('ipCount').textContent = count;
        const submitButton = document.getElementById('submitButton');
        const buttonText = document.getElementById('buttonText');
        if (count > 0) {
            submitButton.disabled = false;
            buttonText.textContent = `Настроить ${count} ${count === 1 ? 'сервер' : 'серверов'}`;
        } else {
            submitButton.disabled = true;
            buttonText.textContent = 'Настроить серверы';
        }
    }

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ' || e.key === ',') {
            e.preventDefault();
            addIPTag(input.value);
        } else if (e.key === 'Backspace' && !input.value && ipTags.length > 0) {
            e.preventDefault();
            removeIPTag(ipTags[ipTags.length - 1]);
        }
    });

    input.addEventListener('paste', (e) => {
        e.preventDefault();
        const pastedText = (e.clipboardData || window.clipboardData).getData('text');
        const ips = pastedText.split(/[\s,\n]+/).filter(ip => ip.trim());
        ips.forEach(ip => addIPTag(ip));
    });

    input.addEventListener('blur', () => {
        if (input.value.trim()) {
            addIPTag(input.value);
        }
    });

    container.addEventListener('click', (e) => {
        if (e.target === container || !e.target.closest('.ip-tag')) {
            input.focus();
        }
    });

    updateUI();
}

async function handleSubmit(e) {
    e.preventDefault();
    console.log('setup_server.js: Form submitted');
    const submitButton = document.getElementById('submitButton');
    const buttonText = document.getElementById('buttonText');
    const originalText = buttonText.textContent;
    const inbound = document.getElementById('inbound').value;
    if (!inbound) {
        showAlert('Выберите локацию', 'error');
        showToast('Локация обязательна', 'error');
        return;
    }
    if (ipTags.length === 0) {
        showAlert('Добавьте хотя бы один IP адрес', 'error');
        showToast('IP адрес обязателен', 'error');
        return;
    }
    submitButton.classList.add('loading');
    buttonText.innerHTML = '<div class="loading-spinner"></div>Настройка...';
    submitButton.disabled = true;
    try {
        console.log('setup_server.js: Sending request to /api/add_server with:', { ips: ipTags, inbound_tag: inbound });
        const response = await fetch('/api/add_server', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ips: ipTags, inbound_tag: inbound })
        });
        if (!response.ok) {
            let errorMessage = `HTTP error! status: ${response.status}`;
            try {
                const errorData = await response.json();
                errorMessage = errorData.detail || errorMessage;
            } catch {
                // No JSON response
            }
            console.error('setup_server.js: Error response:', errorMessage);
            throw new Error(errorMessage);
        }
        const data = await response.json();
        console.log('setup_server.js: Response from /api/add_server:', data);
        const results = data.results || [];
        let successCount = 0;
        let errorCount = 0;
        results.forEach(result => {
            if (result.success) {
                successCount++;
            } else {
                console.error(`setup_server.js: Error setting up ${result.ip}: ${result.message}`);
                errorCount++;
            }
        });
        if (successCount > 0 && errorCount === 0) {
            showAlert(`Успешно настроено ${successCount} серверов`, 'success');
            showToast(`${successCount} серверов настроены`, 'success');
            document.getElementById('inbound').value = '';
            const container = document.getElementById('ipTagsInput');
            const tags = container.querySelectorAll('.ip-tag');
            tags.forEach(tag => tag.remove());
            ipTags = [];
            document.getElementById('ipCount').textContent = '0';
        } else if (successCount > 0 && errorCount > 0) {
            showAlert(`Настроено ${successCount} серверов, ошибок: ${errorCount}`, 'error');
            showToast(`Частично выполнено: ${successCount} успешно, ${errorCount} ошибок`, 'error');
        } else {
            showAlert(`Ошибка настройки серверов: ${errorCount} ошибок`, 'error');
            showToast('Не удалось настроить серверы: ' + (results[0]?.message || 'Неизвестная ошибка'), 'error');
        }
    } catch (error) {
        console.error('setup_server.js: Error submitting form:', error);
        showAlert('Ошибка при настройке серверов: ' + error.message, 'error');
        showToast('Ошибка подключения: ' + error.message, 'error');
    } finally {
        submitButton.classList.remove('loading');
        buttonText.textContent = originalText;
        if (ipTags.length > 0) {
            submitButton.disabled = false;
        }
    }
}

function showAlert(message, type) {
    const alert = document.getElementById('alert');
    alert.textContent = message;
    alert.className = `alert ${type}`;
    setTimeout(() => {
        alert.className = 'alert';
    }, 5000);
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
            if (container.contains(toast)) {
                container.removeChild(toast);
            }
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
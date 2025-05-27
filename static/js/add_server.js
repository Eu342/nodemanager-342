let availableInbounds = [];
let ipTags = [];

document.addEventListener('DOMContentLoaded', () => {
    loadInbounds();
    setupEventListeners();
    setupIPTagsInput();
    loadTheme();
});

async function loadInbounds() {
    try {
        const response = await fetch('/api/inbounds');
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data = await response.json();
        availableInbounds = data.inbounds || [];
        populateInboundSelect();
    } catch (error) {
        showToast('Ошибка загрузки инбаундов: ' + error.message, 'error');
        const select = document.getElementById('inbound');
        if (select) {
            select.innerHTML = '<option value="">Ошибка загрузки инбаундов</option>';
        }
    }
}

function populateInboundSelect() {
    const select = document.getElementById('inbound');
    if (!select) {
        return;
    }
    if (availableInbounds.length === 0) {
        select.innerHTML = '<option value="">Инбаунды не найдены</option>';
        return;
    }
    select.innerHTML = '<option value="">Выберите инбаунд...</option>' + 
        availableInbounds.map(inbound => 
            `<option value="${inbound}">${inbound}</option>`
        ).join('');
}

function setupEventListeners() {
    const form = document.getElementById('addServerForm');
    if (form) {
        form.addEventListener('submit', handleSubmit);
    }
}

function setupIPTagsInput() {
    const container = document.getElementById('ipTagsInput');
    const input = document.getElementById('ipInput');
    if (!container || !input) {
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
        const ipCount = document.getElementById('ipCount');
        const submitButton = document.getElementById('submitButton');
        const buttonText = document.getElementById('buttonText');
        if (ipCount) ipCount.textContent = count;
        if (submitButton && buttonText) {
            if (count > 0) {
                submitButton.disabled = false;
                buttonText.textContent = `Добавить ${count} ${count === 1 ? 'сервер' : 'серверов'}`;
            } else {
                submitButton.disabled = true;
                buttonText.textContent = 'Добавить серверы';
            }
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
    const submitButton = document.getElementById('submitButton');
    const buttonText = document.getElementById('buttonText');
    const originalText = buttonText.textContent;
    const inbound = document.getElementById('inbound').value;
    if (!inbound) {
        showAlert('Выберите инбаунд', 'error');
        showToast('Инбаунд обязателен', 'error');
        return;
    }
    if (ipTags.length === 0) {
        showAlert('Добавьте хотя бы один IP адрес', 'error');
        showToast('IP адрес обязателен', 'error');
        return;
    }
    submitButton.classList.add('loading');
    buttonText.innerHTML = '<div class="loading-spinner"></div>Добавление...';
    submitButton.disabled = true;
    try {
        const formData = new FormData();
        ipTags.forEach(ip => formData.append('ips', ip));
        formData.append('inbound', inbound);
        const response = await fetch('/api/add_server_manual', {
            method: 'POST',
            body: formData
        });
        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
        }
        const data = await response.json();
        const results = data.results || [];
        let successCount = 0;
        let errorCount = 0;
        results.forEach(result => {
            if (result.success) {
                successCount++;
            } else {
                errorCount++;
            }
        });
        if (successCount > 0 && errorCount === 0) {
            showAlert(`Успешно добавлено ${successCount} серверов`, 'success');
            showToast(`${successCount} серверов добавлены в базу данных`, 'success');
            document.getElementById('inbound').value = '';
            const container = document.getElementById('ipTagsInput');
            const tags = container.querySelectorAll('.ip-tag');
            tags.forEach(tag => tag.remove());
            ipTags = [];
            document.getElementById('ipCount').textContent = '0';
        } else if (successCount > 0 && errorCount > 0) {
            showAlert(`Добавлено ${successCount} серверов, ошибок: ${errorCount}`, 'error');
            showToast(`Частично выполнено: ${successCount} успешно, ${errorCount} ошибок`, 'error');
        } else {
            showAlert(`Ошибка добавления серверов: ${errorCount} ошибок`, 'error');
            showToast('Не удалось добавить серверы', 'error');
        }
    } catch (error) {
        showAlert('Ошибка при добавлении серверов: ' + error.message, 'error');
        showToast('Ошибка подключения', 'error');
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
        showToast('Включена темная тема', 'info');
    }
}

function loadTheme() {
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme === 'dark') {
        document.documentElement.setAttribute('data-theme', 'dark');
    }
}
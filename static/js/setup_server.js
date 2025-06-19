(function() {
    'use strict';
    
    const SCRIPT_VERSION = 'original-logic-themed-v2.6-setupserver-auth';

    // --- Проверка загрузки auth_utils ---
    if (typeof window.authUtils === 'undefined') {
        console.error('auth_utils.js must be loaded before setup_server.js');
    }

    // Создаем локальную ссылку на fetchWithAuth для удобства
    const fetchWithAuth = window.authUtils?.fetchWithAuth || fetch;

    // --- Глобальные переменные из вашего оригинального JS ---
    let availableInbounds = [];
    let ipTags = [];

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
    console.log(`setup_server.js: DOM loaded - ${SCRIPT_VERSION}`);
    loadTheme();
    setupMobileMenuEventListeners();
    
    loadInbounds();
    setupFormEventListeners(); 
    setupIPTagsInput();
});

function setupMobileMenuEventListeners() {
    const mobileMenuToggle = document.getElementById('mobileMenuToggle');
    if (mobileMenuToggle) mobileMenuToggle.addEventListener('click', toggleMobileMenu);
    
    const overlay = document.getElementById('mobileOverlay');
    if(overlay) overlay.addEventListener('click', closeMobileMenu);

    const themeBtnHeader = document.querySelector('.header-actions #themeButton'); 
    if(themeBtnHeader) themeBtnHeader.addEventListener('click', toggleTheme);
    
    document.addEventListener('keydown', (e) => { 
        if (e.key === 'Escape') {
            closeMobileMenu();
        }
    });
}


async function loadInbounds() {
    try {
        console.log('setup_server.js: Fetching /api/vless_keys');
        const response = await fetchWithAuth('/api/vless_keys');
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
        if (select) { // Проверка существования элемента
            select.innerHTML = '<option value="">Ошибка загрузки локаций</option>';
        }
    }
}

function populateInboundSelect() {
    const select = document.getElementById('inbound');
    if (!select) {
        console.error('setup_server.js: Select element #inbound not found');
        return;
    }
    if (availableInbounds.length === 0) {
        select.innerHTML = '<option value="">Локации не найдены</option>';
        return;
    }
    select.innerHTML = '<option value="">Выберите локацию...</option>' + 
        availableInbounds.map(inbound => 
            `<option value="${inbound.inbound_tag}">${inbound.inbound_tag}</option>`
        ).join('');
}

// ИСПРАВЛЕНИЕ: Функция вынесена на глобальный уровень
function updateIPInputUI() {
    const count = ipTags.length;
    const ipCountEl = document.getElementById('ipCount');
    const submitButtonEl = document.getElementById('submitSetupServerButton'); 
    const buttonTextEl = document.getElementById('submitButtonText'); 
    
    if (ipCountEl) ipCountEl.textContent = count;
    
    if (submitButtonEl && buttonTextEl) {
        const serverWord = (n) => {
            if (n % 10 === 1 && n % 100 !== 11) return 'сервер';
            if (n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 10 || n % 100 >= 20)) return 'сервера';
            return 'серверов';
        };

        if (count > 0) {
            submitButtonEl.disabled = false;
            buttonTextEl.textContent = `Настроить ${count} ${serverWord(count)}`; 
        } else {
            submitButtonEl.disabled = true;
            buttonTextEl.textContent = 'Настроить серверы';
        }
    }
}

function setupFormEventListeners() {
    console.log('setup_server.js: Setting up form event listeners');
    const form = document.getElementById('setupServerForm');
    if (form) {
        form.addEventListener('submit', handleSubmit);
    } else {
        console.error('setup_server.js: Form element with ID "setupServerForm" not found');
    }
}

function setupIPTagsInput() {
    console.log('setup_server.js: Setting up IP tags input');
    const container = document.getElementById('ipTagsInputContainer'); 
    const input = document.getElementById('ipAddressInput'); 
    if (!container || !input) {
        console.error('setup_server.js: IP tags input container or input not found');
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
        if (!/^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(:\d+)?$/.test(ip) && 
            !/^\[?[a-fA-F0-9:]+\]?(:\d+)?$/.test(ip) && 
            !/^[a-zA-Z0-9][a-zA-Z0-9.-]*[a-zA-Z0-9](:\d+)?$/.test(ip) ) {
             showToast(`Неверный формат IP/домена: ${ip}`, 'error');
             input.value = '';
             return;
        }
        if (ipTags.includes(ip)) {
            showToast(`IP/домен ${ip} уже добавлен`, 'warning');
            input.value = '';
            return;
        }
        ipTags.push(ip);
        const tagElement = createIPTag(ip);
        container.insertBefore(tagElement, input);
        updateIPInputUI();
        input.value = '';
    }

    function removeIPTag(ip) {
        const index = ipTags.indexOf(ip);
        if (index > -1) {
            ipTags.splice(index, 1);
            const tagElements = container.querySelectorAll('.ip-tag');
            tagElements.forEach(tagEl => {
                if (tagEl.querySelector('span').textContent === ip) {
                    tagEl.remove();
                }
            });
            updateIPInputUI();
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
        if (e.target === container || e.target.classList.contains('ip-tags-input')) {
            input.focus();
        }
    });

    updateIPInputUI();
}

async function handleSubmit(e) {
    e.preventDefault();
    console.log('setup_server.js: Form submitted');
    const submitButton = document.getElementById('submitSetupServerButton');
    const buttonText = document.getElementById('submitButtonText');
    const originalText = buttonText.textContent;
    const inbound = document.getElementById('inbound').value;
    const alertEl = document.getElementById('alert');

    if (!inbound) {
        if(alertEl) { alertEl.textContent = 'Выберите локацию (инбаунд)'; alertEl.className = 'alert error'; alertEl.style.display = 'block'; setTimeout(()=> alertEl.style.display = 'none', 5000); }
        showToast('Локация (инбаунд) обязательна', 'error');
        return;
    }
    if (ipTags.length === 0) {
        if(alertEl) { alertEl.textContent = 'Добавьте хотя бы один IP адрес'; alertEl.className = 'alert error'; alertEl.style.display = 'block'; setTimeout(()=> alertEl.style.display = 'none', 5000); }
        showToast('IP адрес обязателен', 'error');
        return;
    }
    if(alertEl) alertEl.style.display = 'none';

    submitButton.classList.add('loading');
    buttonText.innerHTML = '<div class="loading-spinner"></div>Настройка...';
    submitButton.disabled = true;

    try {
        console.log('setup_server.js: Sending request to /api/add_server with:', { ips: ipTags, inbound_tag: inbound });
        const response = await fetchWithAuth('/api/add_server', { 
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ips: ipTags, inbound_tag: inbound })
        });
        if (!response.ok) {
            let errorMessage = `HTTP error! status: ${response.status}`;
            try {
                const errorData = await response.json();
                errorMessage = errorData.detail || errorMessage;
            } catch { /* No JSON response */ }
            console.error('setup_server.js: Error response:', errorMessage);
            throw new Error(errorMessage);
        }
        const data = await response.json();
        console.log('setup_server.js: Response from /api/add_server:', data);
        const results = data.results || [];
        let successCount = 0;
        let errorCount = 0;
        let errorMessages = [];
        results.forEach(result => {
            if (result.success) {
                successCount++;
            } else {
                console.error(`setup_server.js: Error setting up ${result.ip}: ${result.message}`);
                errorCount++;
                errorMessages.push(`${result.ip}: ${result.message}`);
            }
        });
        
        if (successCount > 0 && errorCount === 0) {
            showToast(`Успешно настроено ${successCount} серверов`, 'success');
            document.getElementById('inbound').value = ''; 
            const ipContainer = document.getElementById('ipTagsInputContainer');
            const tags = ipContainer.querySelectorAll('.ip-tag');
            tags.forEach(tag => tag.remove());
            ipTags = [];
            // updateIPInputUI() будет вызван в finally
        } else if (successCount > 0 && errorCount > 0) {
            showToast(`Настроено: ${successCount}, ошибок: ${errorCount}. (${errorMessages.join('; ')})`, 'warning', 6000);
        } else {
            showToast(`Ошибка настройки: ${errorCount} ошибок. (${errorMessages.join('; ')})` , 'error', 6000);
        }
    } catch (error) {
        console.error('setup_server.js: Error submitting form:', error);
        showToast('Ошибка при настройке серверов: ' + error.message, 'error');
    } finally {
        submitButton.classList.remove('loading');
        buttonText.textContent = originalText;
        updateIPInputUI(); // Теперь этот вызов будет работать
    }
}

// Export functions that need to be available globally
window.updateIPInputUI = updateIPInputUI;

})(); // Конец IIFE
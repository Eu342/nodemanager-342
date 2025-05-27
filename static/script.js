async function loadInbounds() {
    try {
        console.log('Fetching inbounds from /api/inbounds');
        const response = await fetch('/api/inbounds');
        if (!response.ok) throw new Error(`Failed to fetch inbounds: ${response.status}`);
        const data = await response.json();
        console.log('Inbounds response:', data);
        const inbounds = Array.isArray(data.inbounds) ? data.inbounds : [];
        console.log('Processed inbounds:', inbounds);
        const select = document.getElementById('inbound');
        if (!select) {
            console.error('Element #inbound not found');
            return;
        }
        if (!inbounds.length) {
            console.warn('No inbounds found');
            select.innerHTML = '<option value="">No inbounds available</option>';
            return;
        }
        select.innerHTML = inbounds.map(inbound => {
            const tag = typeof inbound === 'string' ? inbound : (inbound.tag || inbound.inbound_tag || 'Unknown');
            console.log('Processing inbound tag:', tag);
            return `<option value="${tag}">${tag}</option>`;
        }).join('');
    } catch (error) {
        console.error('Error loading inbounds:', error);
        const select = document.getElementById('inbound');
        if (select) {
            select.innerHTML = '<option value="">Error loading inbounds</option>';
        }
    }
}

async function handleSubmit(event) {
    event.preventDefault();
    try {
        console.log('Submitting setup form');
        const form = event.target;
        const response = await fetch('/api/add_server', {
            method: 'POST',
            body: new FormData(form)
        });
        const result = await response.json();
        const alert = document.getElementById('alert');
        if (!alert) {
            console.error('Element #alert not found');
            return;
        }
        alert.textContent = result.message || result.detail;
        alert.className = `alert ${response.ok ? 'alert-success' : 'alert-error'}`;
    } catch (error) {
        console.error('Error submitting setup form:', error);
        const alert = document.getElementById('alert');
        if (alert) {
            alert.textContent = 'Failed to setup server';
            alert.className = 'alert alert-error';
        }
    }
}

async function handleManualSubmit(event) {
    event.preventDefault();
    try {
        console.log('Submitting manual add form');
        const form = event.target;
        const response = await fetch('/api/add_server_manual', {
            method: 'POST',
            body: new FormData(form)
        });
        const result = await response.json();
        const alert = document.getElementById('alert');
        if (!alert) {
            console.error('Element #alert not found');
            return;
        }
        alert.textContent = result.message || result.detail;
        alert.className = `alert ${response.ok ? 'alert-success' : 'alert-error'}`;
    } catch (error) {
        console.error('Error submitting manual add form:', error);
        const alert = document.getElementById('alert');
        if (alert) {
            alert.textContent = 'Failed to add server';
            alert.className = 'alert alert-error';
        }
    }
}

let allServers = [];
let currentSort = { field: null, direction: 'asc' };

async function loadServers() {
    try {
        console.log('Fetching servers from /api/servers');
        const response = await fetch('/api/servers');
        if (!response.ok) throw new Error(`Failed to fetch servers: ${response.status}`);
        const data = await response.json();
        console.log('Raw servers response:', data);
        allServers = Array.isArray(data.servers) ? data.servers : [];
        console.log('Loaded servers:', allServers);
        renderServers(allServers);
        setupSearch();
    } catch (error) {
        console.error('Error loading servers:', error);
        const tbody = document.querySelector('tbody');
        if (tbody) {
            tbody.innerHTML = '<tr><td colspan="4" class="empty">Failed to load servers</td></tr>';
        }
    }
}

function renderServers(servers) {
    console.log('Rendering servers:', servers);
    const tbody = document.querySelector('tbody');
    if (!tbody) {
        console.error('Element tbody not found');
        return;
    }
    if (!servers || servers.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="empty">No servers found</td></tr>';
        return;
    }
    tbody.innerHTML = servers.map(server => {
        if (!server) return '';
        return `
            <tr>
                <td>${server.ip || 'N/A'}</td>
                <td>${server.inbound || 'N/A'}</td>
                <td>${server.install_date ? new Date(server.install_date).toLocaleString() : 'N/A'}</td>
                <td>
                    <button class="delete-button" onclick="showDeleteModal('${server.ip || ''}')">
                        <svg viewBox="0 0 20 20" fill="none" stroke="currentColor">
                            <path d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm4 0a1 1 0 112 0v6a1 1 0 11-2 0V8z"/>
                        </svg>
                    </button>
                </td>
            </tr>
        `;
    }).join('');
}

function filterServers(query) {
    console.log('Filtering servers with query:', query);
    if (!allServers) {
        console.error('allServers is undefined or null');
        return;
    }
    const filtered = allServers.filter(server => {
        if (!server) return false;
        const searchText = `${server.ip || ''} ${server.inbound || ''}`.toLowerCase();
        return searchText.includes(query.toLowerCase());
    });
    console.log('Filtered servers:', filtered);
    const sorted = sortServers(filtered, currentSort.field, currentSort.direction);
    renderServers(sorted);
}

function sortServers(servers, field, direction) {
    console.log('Sorting servers by:', field, direction);
    if (!field || !servers) return servers || [];
    const sorted = [...servers].sort((a, b) => {
        if (!a || !b) return 0;
        let valA = a[field];
        let valB = b[field];
        if (field === 'install_date') {
            valA = valA ? new Date(valA).getTime() : 0;
            valB = valB ? new Date(valB).getTime() : 0;
        }
        valA = valA || '';
        valB = valB || '';
        if (valA < valB) return direction === 'asc' ? -1 : 1;
        if (valA > valB) return direction === 'asc' ? 1 : -1;
        return 0;
    });
    return sorted;
}

function sortTable(field) {
    console.log('Sort table called for field:', field);
    const th = document.querySelector(`th[onclick="sortTable('${field}')"]`);
    if (!th) {
        console.error(`Header for field ${field} not found`);
        return;
    }
    const allTh = document.querySelectorAll('th');
    
    allTh.forEach(header => {
        header.classList.remove('active', 'asc', 'desc');
        const existingIcon = header.querySelector('.sort-icon');
        if (existingIcon) existingIcon.style.opacity = '0';
    });

    const isCurrent = currentSort.field === field;
    const newDirection = isCurrent && currentSort.direction === 'asc' ? 'desc' : 'asc';
    
    th.classList.add('active', newDirection);
    const sortIcon = th.querySelector('.sort-icon');
    if (sortIcon) sortIcon.style.opacity = '1';
    
    currentSort = { field, direction: newDirection };
    console.log('Sorting by:', field, newDirection);
    
    const query = document.querySelector('.search-input')?.value || '';
    filterServers(query);
}

function setupSearch() {
    console.log('Setting up search input listener');
    const searchInput = document.querySelector('.search-input');
    if (!searchInput) {
        console.error('Element .search-input not found');
        return;
    }
    searchInput.removeEventListener('input', handleSearch);
    searchInput.addEventListener('input', handleSearch);
}

function handleSearch(event) {
    console.log('Search input event triggered with value:', event.target.value);
    filterServers(event.target.value);
}

function showDeleteModal(ip) {
    console.log('Showing delete modal for IP:', ip);
    const modal = document.getElementById('modal');
    const modalText = document.getElementById('modal-text');
    if (!modal || !modalText) {
        console.error('Modal elements not found');
        return;
    }
    modalText.textContent = `Are you sure you want to delete server ${ip}?`;
    modal.style.display = 'flex';
    modal.dataset.ip = ip;
}

function closeModal() {
    console.log('Closing modal');
    const modal = document.getElementById('modal');
    if (modal) {
        modal.style.display = 'none';
        modal.dataset.ip = '';
    }
}

async function confirmDelete() {
    console.log('Confirm delete called');
    const modal = document.getElementById('modal');
    if (!modal) {
        console.error('Modal element not found');
        return;
    }
    const ip = modal.dataset.ip;
    console.log('Confirming delete for IP:', ip);
    try {
        const response = await fetch(`/api/delete_server?ip=${encodeURIComponent(ip)}`, {
            method: 'DELETE'
        });
        if (!response.ok) {
            const error = await response.json();
            console.error('Delete error:', error);
            alert(`Error: ${error.detail}`);
            return;
        }
        console.log('Server deleted:', ip);
        closeModal();
        loadServers();
    } catch (error) {
        console.error('Error deleting server:', error);
        alert(`Error: ${error.message}`);
    }
}

function toggleTheme() {
    const html = document.documentElement;
    const currentTheme = html.getAttribute('data-theme');
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    html.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme', newTheme);
}

function setupNav() {
    console.log('Setting up navigation');
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(item => {
        item.addEventListener('click', () => {
            const page = item.getAttribute('data-page');
            let url;
            switch (page) {
                case 'dashboard':
                    url = '/nodemanager';
                    break;
                case 'add':
                    url = '/nodemanager/add';
                    break;
                case 'install':
                    url = '/nodemanager/setup';
                    break;
                case 'list':
                    url = '/nodemanager/list';
                    break;
                default:
                    return;
            }
            console.log('Navigating to:', url);
            window.location.href = url;
        });
    });

    const currentPath = window.location.pathname;
    navItems.forEach(item => {
        const page = item.getAttribute('data-page');
        const isActive = (page === 'dashboard' && currentPath === '/nodemanager') ||
                         (page === 'add' && currentPath === '/nodemanager/add') ||
                         (page === 'install' && currentPath === '/nodemanager/setup') ||
                         (page === 'list' && currentPath === '/nodemanager/list');
        if (isActive) {
            item.classList.add('active');
        } else {
            item.classList.remove('active');
        }
    });
}

document.addEventListener('DOMContentLoaded', () => {
    console.log('DOM fully loaded');
    const savedTheme = localStorage.getItem('theme') || 'dark';
    document.documentElement.setAttribute('data-theme', savedTheme);
    setupNav();
});
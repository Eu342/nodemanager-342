// Authentication utilities for JWT handling

const AUTH_TOKEN_KEY = 'access_token';
const TOKEN_TYPE_KEY = 'token_type';

// Get stored token
function getAuthToken() {
    return localStorage.getItem(AUTH_TOKEN_KEY);
}

// Get token type
function getTokenType() {
    const stored = localStorage.getItem(TOKEN_TYPE_KEY);
    // Всегда возвращаем Bearer с большой буквы
    return 'Bearer';
}

// Set auth token
function setAuthToken(token, tokenType = 'bearer') {
    localStorage.setItem(AUTH_TOKEN_KEY, token);
    localStorage.setItem(TOKEN_TYPE_KEY, tokenType);
}

// Clear auth tokens
function clearAuthTokens() {
    localStorage.removeItem(AUTH_TOKEN_KEY);
    localStorage.removeItem(TOKEN_TYPE_KEY);
}

// Check if user is authenticated
function isAuthenticated() {
    const token = getAuthToken();
    if (!token) return false;
    
    // Try to decode JWT to check expiration
    try {
        const payload = parseJwt(token);
        if (payload.exp) {
            const expirationTime = payload.exp * 1000; // Convert to milliseconds
            return Date.now() < expirationTime;
        }
        return true;
    } catch (e) {
        return false;
    }
}

// Parse JWT token
function parseJwt(token) {
    try {
        const base64Url = token.split('.')[1];
        const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
        const jsonPayload = decodeURIComponent(atob(base64).split('').map(function(c) {
            return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2);
        }).join(''));
        return JSON.parse(jsonPayload);
    } catch (e) {
        console.error('Error parsing JWT:', e);
        return null;
    }
}

// Get auth headers for fetch requests
function getAuthHeaders() {
    const token = getAuthToken();
    
    if (!token) {
        console.warn('getAuthHeaders: No token found');
        return {};
    }
    
    const headers = {
        'Authorization': `Bearer ${token}`
    };
    
    console.log('getAuthHeaders returning:', {
        'Authorization': `Bearer ${token.substring(0, 10)}...`
    });
    
    return headers;
}

// Fetch with authentication
async function fetchWithAuth(url, options = {}) {
    const token = getAuthToken();
    
    console.log('fetchWithAuth:', {
        url,
        token: token ? `${token.substring(0, 10)}...` : 'NO TOKEN',
        hasToken: !!token
    });
    
    const authHeaders = getAuthHeaders();
    
    const fetchOptions = {
        ...options,
        headers: {
            ...authHeaders,
            ...(options.headers || {})
        }
    };
    
    console.log('Request headers:', fetchOptions.headers);
    
    try {
        const response = await fetch(url, fetchOptions);
        
        console.log(`Response from ${url}:`, response.status);
        
        // If unauthorized, redirect to login
        if (response.status === 401) {
            console.error('Got 401, clearing tokens and redirecting');
            clearAuthTokens();
            setTimeout(() => {
                window.location.href = '/login?return=' + encodeURIComponent(window.location.pathname);
            }, 100);
            return response; // Возвращаем response, а не null
        }
        
        // If rate limited
        if (response.status === 429) {
            const message = 'Слишком много запросов. Пожалуйста, подождите.';
            if (typeof showToast === 'function') {
                showToast(message, 'warning');
            } else {
                alert(message);
            }
            throw new Error('Rate limited');
        }
        
        return response;
    } catch (error) {
        console.error('Fetch error:', error);
        throw error;
    }
}

// Initialize auth check on page load
document.addEventListener('DOMContentLoaded', () => {
    console.log('auth_utils.js: DOMContentLoaded, path:', window.location.pathname);
    console.log('auth_utils.js: Token present:', !!getAuthToken());
    
    // Skip auth check for login page and static resources
    if (window.location.pathname === '/login' || window.location.pathname.startsWith('/static/')) {
        return;
    }
    
    // ВРЕМЕННО ОТКЛЮЧЕНО ДЛЯ ОТЛАДКИ
    /*
    // Check authentication
    if (!isAuthenticated()) {
        console.log('auth_utils.js: Not authenticated, redirecting to login');
        clearAuthTokens();
        window.location.href = '/login?return=' + encodeURIComponent(window.location.pathname);
    }
    */
    
    // Add logout handler to any logout buttons
    const logoutButtons = document.querySelectorAll('[data-action="logout"]');
    logoutButtons.forEach(button => {
        button.addEventListener('click', async (e) => {
            e.preventDefault();
            await logout();
        });
    });
});

// Logout function
async function logout() {
    try {
        await fetchWithAuth('/api/auth/logout', {
            method: 'POST'
        });
    } catch (e) {
        // Even if logout fails, clear local tokens
        console.error('Logout error:', e);
    } finally {
        clearAuthTokens();
        window.location.href = '/login';
    }
}

// Auto-refresh token before expiration
function setupTokenRefresh() {
    const token = getAuthToken();
    if (!token) return;
    
    const payload = parseJwt(token);
    if (!payload || !payload.exp) return;
    
    const expirationTime = payload.exp * 1000;
    const refreshTime = expirationTime - (5 * 60 * 1000); // Refresh 5 minutes before expiration
    const timeUntilRefresh = refreshTime - Date.now();
    
    if (timeUntilRefresh > 0) {
        setTimeout(async () => {
            try {
                const response = await fetch('/api/auth/refresh', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        refresh_token: localStorage.getItem('refresh_token')
                    })
                });
                
                if (response.ok) {
                    const data = await response.json();
                    setAuthToken(data.access_token, data.token_type);
                    setupTokenRefresh(); // Setup next refresh
                } else {
                    // If refresh fails, redirect to login
                    clearAuthTokens();
                    window.location.href = '/login?return=' + encodeURIComponent(window.location.pathname);
                }
            } catch (e) {
                console.error('Token refresh error:', e);
            }
        }, timeUntilRefresh);
    }
}

// Export functions for use in other scripts
window.authUtils = {
    getAuthToken,
    getTokenType,
    setAuthToken,
    clearAuthTokens,
    isAuthenticated,
    parseJwt,
    getAuthHeaders,
    fetchWithAuth,
    logout,
    setupTokenRefresh
};

console.log('auth_utils.js loaded, window.authUtils:', window.authUtils);
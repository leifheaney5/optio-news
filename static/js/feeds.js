// ==================== State Management ====================
let allActiveFeeds = [];
let allAvailableFeeds = {};
let currentTab = 'active';
let currentCategory = 'all';

// ==================== DOM Elements ====================
const elements = {
    tabBtns: document.querySelectorAll('.tab-btn'),
    activeTab: document.getElementById('activeTab'),
    availableTab: document.getElementById('availableTab'),
    activeFeedsGrid: document.getElementById('activeFeedsGrid'),
    availableFeedsGrid: document.getElementById('availableFeedsGrid'),
    searchActive: document.getElementById('searchActive'),
    searchAvailable: document.getElementById('searchAvailable'),
    activeCount: document.getElementById('activeCount'),
    availableCount: document.getElementById('availableCount'),
    loading: document.getElementById('loading'),
    themeToggle: document.getElementById('themeToggle'),
    availableCategories: document.getElementById('availableCategories')
};

// ==================== Theme Management ====================
function initTheme() {
    const savedTheme = localStorage.getItem('theme') || 'light';
    document.documentElement.setAttribute('data-theme', savedTheme);
    updateThemeIcon(savedTheme);
}

function toggleTheme() {
    const currentTheme = document.documentElement.getAttribute('data-theme');
    const newTheme = currentTheme === 'light' ? 'dark' : 'light';
    
    document.documentElement.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme', newTheme);
    updateThemeIcon(newTheme);
}

function updateThemeIcon(theme) {
    const icon = elements.themeToggle.querySelector('i');
    icon.className = theme === 'light' ? 'fas fa-moon' : 'fas fa-sun';
}

// ==================== API Functions ====================
async function loadActiveFeeds() {
    try {
        const response = await fetch('/api/feeds');
        const data = await response.json();
        allActiveFeeds = data.feeds || [];
        elements.activeCount.textContent = allActiveFeeds.filter(f => !f.hidden).length;
        renderActiveFeeds();
    } catch (error) {
        console.error('Error loading active feeds:', error);
        showToast('Failed to load active feeds', 'error');
    }
}

async function loadAvailableFeeds() {
    try {
        const response = await fetch('/api/feeds/available');
        const data = await response.json();
        allAvailableFeeds = data.feeds || {};
        elements.availableCount.textContent = data.total || 0;
        renderCategoryFilters();
        renderAvailableFeeds();
    } catch (error) {
        console.error('Error loading available feeds:', error);
        showToast('Failed to load available feeds', 'error');
    }
}

async function hideFeed(feedUrl) {
    try {
        const response = await fetch('/api/feeds/hide', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ url: feedUrl })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast('Feed hidden successfully', 'success');
            await loadActiveFeeds();
        } else {
            showToast('Failed to hide feed', 'error');
        }
    } catch (error) {
        console.error('Error hiding feed:', error);
        showToast('Failed to hide feed', 'error');
    }
}

async function unhideFeed(feedUrl) {
    try {
        const response = await fetch('/api/feeds/unhide', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ url: feedUrl })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast('Feed restored successfully', 'success');
            await loadActiveFeeds();
        } else {
            showToast('Failed to restore feed', 'error');
        }
    } catch (error) {
        console.error('Error unhiding feed:', error);
        showToast('Failed to restore feed', 'error');
    }
}

async function addFeed(feedUrl, category) {
    try {
        const response = await fetch('/api/feeds/add', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ url: feedUrl, category: category })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast(`Feed added to ${category}`, 'success');
            await loadActiveFeeds();
            await loadAvailableFeeds();
        } else {
            showToast(data.message || 'Failed to add feed', 'error');
        }
    } catch (error) {
        console.error('Error adding feed:', error);
        showToast('Failed to add feed', 'error');
    }
}

// ==================== Render Functions ====================
function renderActiveFeeds() {
    const searchTerm = elements.searchActive.value.toLowerCase();
    
    let filtered = allActiveFeeds.filter(feed => {
        const matchesSearch = !searchTerm || 
            feed.name.toLowerCase().includes(searchTerm) ||
            feed.url.toLowerCase().includes(searchTerm) ||
            feed.category.toLowerCase().includes(searchTerm);
        return matchesSearch;
    });
    
    // Sort: active first, then hidden
    filtered.sort((a, b) => {
        if (a.hidden === b.hidden) return 0;
        return a.hidden ? 1 : -1;
    });
    
    elements.activeFeedsGrid.innerHTML = '';
    
    if (filtered.length === 0) {
        elements.activeFeedsGrid.innerHTML = `
            <div style="grid-column: 1/-1; text-align: center; padding: 3rem;">
                <i class="fas fa-rss" style="font-size: 3rem; color: var(--text-tertiary); margin-bottom: 1rem;"></i>
                <h3>No feeds found</h3>
                <p style="color: var(--text-secondary);">Try adjusting your search</p>
            </div>
        `;
        return;
    }
    
    filtered.forEach(feed => {
        const card = createActiveFeedCard(feed);
        elements.activeFeedsGrid.appendChild(card);
    });
}

function createActiveFeedCard(feed) {
    const card = document.createElement('div');
    card.className = `feed-card ${feed.hidden ? 'hidden' : ''}`;
    
    card.innerHTML = `
        <div class="feed-header">
            <div class="feed-info">
                <div class="feed-name">${escapeHtml(feed.name)}</div>
                <div class="feed-url">${escapeHtml(feed.url)}</div>
            </div>
            <span class="feed-category">${escapeHtml(feed.category)}</span>
        </div>
        <div class="feed-status ${feed.hidden ? 'hidden' : 'active'}">
            <i class="fas fa-${feed.hidden ? 'eye-slash' : 'check-circle'}"></i>
            ${feed.hidden ? 'Hidden' : 'Active'}
        </div>
        <div class="feed-actions">
            ${feed.hidden ? 
                `<button class="btn-feed btn-unhide" onclick="unhideFeed('${escapeHtml(feed.url)}')">
                    <i class="fas fa-eye"></i>
                    Restore Feed
                </button>` :
                `<button class="btn-feed btn-hide" onclick="hideFeed('${escapeHtml(feed.url)}')">
                    <i class="fas fa-eye-slash"></i>
                    Hide Feed
                </button>`
            }
        </div>
    `;
    
    return card;
}

function renderCategoryFilters() {
    const categories = Object.keys(allAvailableFeeds);
    elements.availableCategories.innerHTML = `
        <button class="category-btn active" data-category="all">
            <i class="fas fa-globe"></i>
            All
        </button>
    `;
    
    categories.forEach(category => {
        const btn = document.createElement('button');
        btn.className = 'category-btn';
        btn.dataset.category = category;
        btn.innerHTML = `
            <i class="fas fa-${getCategoryIcon(category)}"></i>
            ${category}
        `;
        elements.availableCategories.appendChild(btn);
    });
}

function renderAvailableFeeds() {
    const searchTerm = elements.searchAvailable.value.toLowerCase();
    
    elements.availableFeedsGrid.innerHTML = '';
    
    let feedsToShow = [];
    
    if (currentCategory === 'all') {
        Object.entries(allAvailableFeeds).forEach(([category, feeds]) => {
            feeds.forEach(feed => {
                feedsToShow.push({ ...feed, category });
            });
        });
    } else {
        const feeds = allAvailableFeeds[currentCategory] || [];
        feeds.forEach(feed => {
            feedsToShow.push({ ...feed, category: currentCategory });
        });
    }
    
    // Filter by search
    if (searchTerm) {
        feedsToShow = feedsToShow.filter(feed =>
            feed.name.toLowerCase().includes(searchTerm) ||
            feed.url.toLowerCase().includes(searchTerm)
        );
    }
    
    if (feedsToShow.length === 0) {
        elements.availableFeedsGrid.innerHTML = `
            <div style="grid-column: 1/-1; text-align: center; padding: 3rem;">
                <i class="fas fa-search" style="font-size: 3rem; color: var(--text-tertiary); margin-bottom: 1rem;"></i>
                <h3>No feeds found</h3>
                <p style="color: var(--text-secondary);">Try adjusting your search or category</p>
            </div>
        `;
        return;
    }
    
    feedsToShow.forEach(feed => {
        const card = createAvailableFeedCard(feed);
        elements.availableFeedsGrid.appendChild(card);
    });
}

function createAvailableFeedCard(feed) {
    const card = document.createElement('div');
    card.className = 'feed-card';
    
    // Check if already added
    const isAdded = allActiveFeeds.some(f => f.url === feed.url);
    
    card.innerHTML = `
        <div class="feed-header">
            <div class="feed-info">
                <div class="feed-name">${escapeHtml(feed.name)}</div>
                <div class="feed-url">${escapeHtml(feed.url)}</div>
            </div>
            <span class="feed-category">${escapeHtml(feed.category)}</span>
        </div>
        <div class="feed-actions">
            <button class="btn-feed btn-add" onclick="addFeed('${escapeHtml(feed.url)}', '${escapeHtml(feed.category)}')" ${isAdded ? 'disabled' : ''}>
                <i class="fas fa-${isAdded ? 'check' : 'plus'}"></i>
                ${isAdded ? 'Already Added' : 'Add Feed'}
            </button>
        </div>
    `;
    
    return card;
}

// ==================== Utility Functions ====================
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function getCategoryIcon(category) {
    const icons = {
        'Technology': 'microchip',
        'Finance': 'chart-line',
        'General News': 'newspaper',
        'Sports': 'football-ball',
        'Science': 'flask',
        'Business': 'briefcase',
        'Entertainment': 'film',
        'Health': 'heartbeat'
    };
    return icons[category] || 'rss';
}

function showToast(message, type = 'success') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `
        <i class="fas fa-${type === 'success' ? 'check-circle' : 'exclamation-circle'}"></i>
        <div class="toast-message">${message}</div>
    `;
    
    document.body.appendChild(toast);
    
    setTimeout(() => {
        toast.style.animation = 'slideInRight 0.3s ease reverse';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// ==================== Event Listeners ====================
function initEventListeners() {
    // Theme toggle
    elements.themeToggle.addEventListener('click', toggleTheme);
    
    // Tab switching
    elements.tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const tab = btn.dataset.tab;
            
            // Update buttons
            elements.tabBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            
            // Update content
            if (tab === 'active') {
                elements.activeTab.classList.add('active');
                elements.availableTab.classList.remove('active');
            } else {
                elements.activeTab.classList.remove('active');
                elements.availableTab.classList.add('active');
            }
            
            currentTab = tab;
        });
    });
    
    // Search inputs
    elements.searchActive.addEventListener('input', () => {
        renderActiveFeeds();
    });
    
    elements.searchAvailable.addEventListener('input', () => {
        renderAvailableFeeds();
    });
    
    // Category filters (delegated)
    elements.availableCategories.addEventListener('click', (e) => {
        const btn = e.target.closest('.category-btn');
        if (btn) {
            const category = btn.dataset.category;
            
            // Update active button
            elements.availableCategories.querySelectorAll('.category-btn').forEach(b => {
                b.classList.remove('active');
            });
            btn.classList.add('active');
            
            currentCategory = category;
            renderAvailableFeeds();
        }
    });
}

// ==================== Initialization ====================
async function init() {
    // Initialize theme
    initTheme();
    
    // Setup event listeners
    initEventListeners();
    
    // Load feeds
    await Promise.all([
        loadActiveFeeds(),
        loadAvailableFeeds()
    ]);
}

// Start the application when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

// Make functions available globally for inline onclick handlers
window.hideFeed = hideFeed;
window.unhideFeed = unhideFeed;
window.addFeed = addFeed;

// ==================== State Management ====================
let allArticles = [];
let filteredArticles = [];
let currentCategory = 'all';
let currentSearch = '';

// ==================== DOM Elements ====================
const elements = {
    articlesGrid: document.getElementById('articlesGrid'),
    loading: document.getElementById('loading'),
    noResults: document.getElementById('noResults'),
    searchInput: document.getElementById('searchInput'),
    clearSearch: document.getElementById('clearSearch'),
    categoryFilters: document.getElementById('categoryFilters'),
    themeToggle: document.getElementById('themeToggle'),
    refreshBtn: document.getElementById('refreshBtn'),
    articleCount: document.getElementById('articleCount'),
    feedCount: document.getElementById('feedCount'),
    lastUpdated: document.getElementById('lastUpdated')
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
async function fetchArticles(forceRefresh = false) {
    try {
        showLoading();
        
        const endpoint = forceRefresh ? '/api/refresh' : '/api/articles';
        const response = await fetch(endpoint);
        
        if (!response.ok) {
            throw new Error('Failed to fetch articles');
        }
        
        const data = await response.json();
        
        if (forceRefresh) {
            // After refresh, fetch the articles
            return fetchArticles(false);
        }
        
        allArticles = data.articles || [];
        applyFilters();
        updateStats(data);
        
        hideLoading();
    } catch (error) {
        console.error('Error fetching articles:', error);
        showError('Failed to load articles. Please try again.');
        hideLoading();
    }
}

async function fetchTrendingTopics() {
    try {
        const sidebarLoading = document.getElementById('sidebarLoading');
        const trendingList = document.getElementById('trendingList');
        
        if (sidebarLoading) sidebarLoading.style.display = 'block';
        if (trendingList) trendingList.style.display = 'none';
        
        const response = await fetch('/api/trending');
        
        if (!response.ok) {
            throw new Error('Failed to fetch trending topics');
        }
        
        const data = await response.json();
        renderTrendingTopics(data.trending || []);
        
        if (sidebarLoading) sidebarLoading.style.display = 'none';
        if (trendingList) trendingList.style.display = 'block';
    } catch (error) {
        console.error('Error fetching trending topics:', error);
        const sidebarLoading = document.getElementById('sidebarLoading');
        if (sidebarLoading) {
            sidebarLoading.innerHTML = '<p style="color: var(--text-secondary); font-size: 0.875rem; padding: 1rem;">Unable to load trending topics</p>';
        }
    }
}

function renderTrendingTopics(topics) {
    const trendingList = document.getElementById('trendingList');
    
    if (!trendingList) return;
    
    if (topics.length === 0) {
        trendingList.innerHTML = '<p style="text-align: center; color: var(--text-secondary); padding: 2rem 1rem; font-size: 0.875rem;">No trending topics found in the last 24 hours</p>';
        return;
    }
    
    trendingList.innerHTML = topics.map((topic, index) => `
        <div class="trending-item" style="animation-delay: ${index * 0.05}s">
            <div class="trending-item-header">
                <div class="trending-item-name">${escapeHtml(topic.topic)}</div>
                <span class="trending-item-count">${topic.count}</span>
            </div>
            ${topic.articles && topic.articles.length > 0 ? `
                <div class="trending-item-articles">
                    ${topic.articles.slice(0, 2).map(article => `
                        <div class="trending-item-article">
                            <a href="${article.link}" target="_blank" rel="noopener noreferrer">
                                ${escapeHtml(article.title)}
                            </a>
                            <div class="trending-item-meta">
                                <span class="trending-item-site">${escapeHtml(article.site)}</span>
                                <span class="trending-item-category">${escapeHtml(article.category)}</span>
                            </div>
                        </div>
                    `).join('')}
                </div>
            ` : ''}
        </div>
    `).join('');
}

// ==================== Filter Functions ====================
function applyFilters() {
    filteredArticles = allArticles.filter(article => {
        // Category filter
        const categoryMatch = currentCategory === 'all' || article.category === currentCategory;
        
        // Search filter
        const searchMatch = !currentSearch || 
            article.title.toLowerCase().includes(currentSearch) ||
            article.summary.toLowerCase().includes(currentSearch);
        
        return categoryMatch && searchMatch;
    });
    
    renderArticles();
}

function setCategory(category) {
    currentCategory = category;
    
    // Update active button
    const buttons = elements.categoryFilters.querySelectorAll('.category-btn');
    buttons.forEach(btn => {
        if (btn.dataset.category === category) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });
    
    applyFilters();
}

function setSearch(query) {
    currentSearch = query.toLowerCase().trim();
    
    // Show/hide clear button
    if (currentSearch) {
        elements.clearSearch.classList.add('visible');
    } else {
        elements.clearSearch.classList.remove('visible');
    }
    
    applyFilters();
}

// ==================== Render Functions ====================
function renderArticles() {
    elements.articlesGrid.innerHTML = '';
    
    if (filteredArticles.length === 0) {
        showNoResults();
        return;
    }
    
    hideNoResults();
    
    filteredArticles.forEach((article, index) => {
        const card = createArticleCard(article, index);
        elements.articlesGrid.appendChild(card);
    });
    
    elements.articleCount.textContent = filteredArticles.length;
}

function createArticleCard(article, index) {
    const card = document.createElement('div');
    card.className = 'article-card';
    card.style.animationDelay = `${index * 0.05}s`;
    
    // Format category for class name
    const categoryClass = article.category.replace(/\s+/g, '.');
    
    // Strip HTML tags from summary and limit length
    const cleanSummary = stripHtmlTags(article.summary);
    const truncatedSummary = cleanSummary.length > 200 
        ? cleanSummary.substring(0, 200) + '...' 
        : cleanSummary;
    
    card.innerHTML = `
        <div class="article-header">
            <span class="category-badge ${categoryClass}">${escapeHtml(article.category)}</span>
            <div class="article-actions">
                <div class="article-time">
                    <i class="far fa-clock"></i>
                    ${formatTimeAgo(article.published)}
                </div>
            </div>
        </div>
        
        <h3 class="article-title">
            <a href="${escapeHtml(article.link)}" target="_blank" rel="noopener noreferrer">
                ${escapeHtml(article.title)}
            </a>
        </h3>
        
        <p class="article-summary">
            ${escapeHtml(truncatedSummary)}
        </p>
        
        <div class="article-footer">
            <div class="article-source">
                <i class="fas fa-globe"></i>
                ${escapeHtml(article.site)}
            </div>
            <a href="${escapeHtml(article.link)}" 
               target="_blank" 
               rel="noopener noreferrer" 
               class="article-link">
                Read More
                <i class="fas fa-arrow-right"></i>
            </a>
        </div>
    `;
    
    return card;
}

// ==================== Utility Functions ====================
function formatTimeAgo(dateString) {
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);
    
    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    
    return date.toLocaleDateString('en-US', { 
        month: 'short', 
        day: 'numeric',
        year: date.getFullYear() !== now.getFullYear() ? 'numeric' : undefined
    });
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function stripHtmlTags(html) {
    const div = document.createElement('div');
    div.innerHTML = html;
    return div.textContent || div.innerText || '';
}

function updateStats(data) {
    if (data.cached) {
        const cacheDate = new Date(data.cached);
        const timeAgo = formatTimeAgo(cacheDate);
        elements.lastUpdated.textContent = `Updated ${timeAgo}`;
    } else {
        elements.lastUpdated.textContent = 'Just updated';
    }
    
    // Update feed count
    if (data.feed_count !== undefined) {
        elements.feedCount.textContent = data.feed_count;
    }
}

function showLoading() {
    elements.loading.style.display = 'block';
    elements.articlesGrid.style.display = 'none';
    elements.noResults.style.display = 'none';
}

function hideLoading() {
    elements.loading.style.display = 'none';
    elements.articlesGrid.style.display = 'grid';
}

function showNoResults() {
    elements.noResults.style.display = 'block';
    elements.articlesGrid.style.display = 'none';
}

function hideNoResults() {
    elements.noResults.style.display = 'none';
}

function showError(message) {
    elements.articlesGrid.innerHTML = `
        <div style="grid-column: 1/-1; text-align: center; padding: 3rem;">
            <i class="fas fa-exclamation-triangle" style="font-size: 3rem; color: var(--danger); margin-bottom: 1rem;"></i>
            <h3 style="color: var(--text-primary); margin-bottom: 0.5rem;">Oops! Something went wrong</h3>
            <p style="color: var(--text-secondary);">${message}</p>
        </div>
    `;
}

// ==================== Event Listeners ====================
function initEventListeners() {
    // Theme toggle
    elements.themeToggle.addEventListener('click', toggleTheme);
    
    // Refresh button
    elements.refreshBtn.addEventListener('click', async () => {
        elements.refreshBtn.querySelector('i').style.animation = 'spin 0.6s ease';
        await fetchArticles(true);
        setTimeout(() => {
            elements.refreshBtn.querySelector('i').style.animation = '';
        }, 600);
    });
    
    // Category filters
    elements.categoryFilters.addEventListener('click', (e) => {
        const btn = e.target.closest('.category-btn');
        if (btn) {
            setCategory(btn.dataset.category);
        }
    });
    
    // Search input
    let searchTimeout;
    elements.searchInput.addEventListener('input', (e) => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            setSearch(e.target.value);
        }, 300);
    });
    
    // Clear search
    elements.clearSearch.addEventListener('click', () => {
        elements.searchInput.value = '';
        setSearch('');
    });
    
    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        // Ctrl/Cmd + K: Focus search
        if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
            e.preventDefault();
            elements.searchInput.focus();
        }
        
        // Escape: Clear search
        if (e.key === 'Escape' && document.activeElement === elements.searchInput) {
            elements.searchInput.value = '';
            setSearch('');
            elements.searchInput.blur();
        }
    });
}

// ==================== Auto-refresh ====================
function startAutoRefresh() {
    // Refresh articles every 30 minutes
    setInterval(() => {
        fetchArticles(true);
    }, 30 * 60 * 1000);
}

// ==================== Initialization ====================
async function init() {
    // Initialize theme
    initTheme();
    
    // Setup event listeners
    initEventListeners();
    
    // Load initial articles
    await fetchArticles();
    
    // Load trending topics
    await fetchTrendingTopics();
    
    // Start auto-refresh
    startAutoRefresh();
}

// Start the application when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

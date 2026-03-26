// ==================== State Management ====================
let allArticles = [];
let filteredArticles = [];
let currentCategory = 'all';
let currentSearch = '';
let viewMode = localStorage.getItem('viewMode') || 'grid'; // 'grid' | 'list'
let bookmarkedUrls = new Set(); // track already-bookmarked article URLs

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
    lastUpdated: document.getElementById('lastUpdated'),
    viewToggle: document.getElementById('viewToggle'),
    suggestionsStrip: document.getElementById('suggestionsStrip'),
    suggestionsCards: document.getElementById('suggestionsCards'),
    suggestionsCategoryLabel: document.getElementById('suggestionsCategoryLabel'),
    suggestionsDismiss: document.getElementById('suggestionsDismiss'),
    topStories: document.getElementById('topStories'),
    topStoriesCards: document.getElementById('topStoriesCards')
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

async function initTicker() {
    const track = document.getElementById('tickerTrack');
    if (!track) return;
    // Re-use already-loaded articles rather than a second fetch
    const articles = (allArticles || []).slice(0, 20);
    if (!articles.length) return;

    const makeItems = () => articles.map(a => {
        const frag = document.createDocumentFragment();
        const item = document.createElement('span');
        item.className = 'ticker-item';
        item.textContent = a.title;
        item.addEventListener('click', () => window.open(a.link, '_blank', 'noopener'));
        const sep = document.createElement('span');
        sep.className = 'ticker-sep';
        sep.textContent = ' ◆ ';
        frag.appendChild(item);
        frag.appendChild(sep);
        return frag;
    });

    makeItems().forEach(f => track.appendChild(f));
    makeItems().forEach(f => track.appendChild(f)); // duplicate for seamless loop
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
                <span class="trending-item-count">${topic.count}x</span>
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

// ==================== View Mode ====================
function applyViewMode() {
    const grid = elements.articlesGrid;
    if (viewMode === 'list') {
        grid.classList.add('articles-list');
        grid.classList.remove('articles-grid');
        if (elements.viewToggle) {
            elements.viewToggle.querySelector('i').className = 'fas fa-th-large';
            elements.viewToggle.title = 'Switch to grid view';
        }
    } else {
        grid.classList.remove('articles-list');
        grid.classList.add('articles-grid');
        if (elements.viewToggle) {
            elements.viewToggle.querySelector('i').className = 'fas fa-list';
            elements.viewToggle.title = 'Switch to list view';
        }
    }
}

function toggleViewMode() {
    viewMode = viewMode === 'grid' ? 'list' : 'grid';
    localStorage.setItem('viewMode', viewMode);
    applyViewMode();
    renderArticles();
}

// ==================== Suggestions Strip ====================
async function fetchSuggestions(category) {
    if (!elements.suggestionsStrip) return;
    if (category === 'all') {
        elements.suggestionsStrip.style.display = 'none';
        return;
    }
    try {
        const res = await fetch(`/api/feeds/suggestions?category=${encodeURIComponent(category)}`);
        if (!res.ok) return;
        const data = await res.json();
        if (!data.suggestions || data.suggestions.length === 0) {
            elements.suggestionsStrip.style.display = 'none';
            return;
        }
        if (elements.suggestionsCategoryLabel) elements.suggestionsCategoryLabel.textContent = category;
        elements.suggestionsCards.innerHTML = data.suggestions.map(s => `
            <div class="suggestion-card">
                <div class="suggestion-info">
                    <span class="suggestion-name">${escapeHtml(s.name || s.url)}</span>
                    <a href="${escapeHtml(s.url)}" target="_blank" rel="noopener noreferrer" class="suggestion-url">${escapeHtml(s.url.replace(/^https?:\/\//, '').split('/')[0])}</a>
                </div>
                <button class="suggestion-add-btn" onclick="addSuggestedFeed('${escapeHtml(s.url)}', '${escapeHtml(category)}', this)">
                    <i class="fas fa-plus"></i> Follow
                </button>
            </div>
        `).join('');
        elements.suggestionsStrip.style.display = 'block';
    } catch (e) {
        // silently fail
    }
}

async function addSuggestedFeed(url, category, btn) {
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>'; }
    try {
        await fetch('/api/feeds/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url, category })
        });
        if (btn) { btn.innerHTML = '<i class="fas fa-check"></i> Added'; btn.style.background = '#22c55e'; }
    } catch {
        if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-plus"></i> Follow'; }
    }
}

// ==================== Top Stories ====================
function renderTopStories(articles) {
    if (!elements.topStories || !articles.length) return;
    // Take most recent article from each of the first 4 unique categories
    const seen = new Set();
    const picks = [];
    [...articles].sort((a, b) => new Date(b.published) - new Date(a.published));
    for (const art of articles) {
        if (!seen.has(art.category)) {
            seen.add(art.category);
            picks.push(art);
        }
        if (picks.length >= 4) break;
    }
    if (picks.length === 0) return;
    elements.topStoriesCards.innerHTML = picks.map(art => `
        <a class="featured-card" href="${escapeHtml(art.link)}" target="_blank" rel="noopener noreferrer">
            <span class="featured-category">${escapeHtml(art.category)}</span>
            <h4 class="featured-title">${escapeHtml(art.title)}</h4>
            <span class="featured-meta"><i class="far fa-clock"></i> ${formatTimeAgo(art.published)} &middot; ${escapeHtml(art.site)}</span>
        </a>
    `).join('');
    elements.topStories.style.display = 'block';
}

// ==================== Toast ====================
function showToast(message, type = 'success') {
    let el = document.getElementById('appToast');
    if (!el) {
        el = document.createElement('div');
        el.id = 'appToast';
        el.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);padding:10px 20px;border-radius:8px;font-size:.9rem;font-weight:500;z-index:9999;opacity:0;transition:opacity .25s;pointer-events:none;';
        document.body.appendChild(el);
    }
    el.textContent = message;
    el.style.background = type === 'error' ? '#d9534f' : '#28a745';
    el.style.color = '#fff';
    el.style.opacity = '1';
    clearTimeout(el._t);
    el._t = setTimeout(() => { el.style.opacity = '0'; }, 2500);
}

// ==================== Bookmark Button ====================
async function loadBookmarkedUrls() {
    try {
        const res = await fetch('/api/bookmarks');
        if (!res.ok) return;
        const data = await res.json();
        (data.bookmarks || []).forEach(b => bookmarkedUrls.add(b.url));
    } catch { /* non-critical */ }
}

async function bookmarkArticle(article, btn) {
    if (btn) { btn.disabled = true; }
    try {
        const payload = {
            url: article.link,
            title: article.title,
            description: article.summary ? article.summary.replace(/<[^>]*>/g, '').substring(0, 200) : '',
            tags: [article.category]
        };
        const res = await fetch('/api/bookmarks', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        if (res.ok) {
            const data = await res.json();
            if (data.id) {
                bookmarkedUrls.add(article.link);
                if (btn) { btn.classList.add('bookmarked'); btn.title = 'Bookmarked'; btn.disabled = false; }
                showToast('Bookmark saved');
            } else {
                throw new Error('Unexpected response');
            }
        } else {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.error || `Error ${res.status}`);
        }
    } catch (e) {
        if (btn) { btn.disabled = false; }
        showToast(e.message || 'Could not save bookmark', 'error');
    }
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

    // Show suggestions / hide top stories when a category is selected
    if (category !== 'all') {
        fetchSuggestions(category);
        if (elements.topStories) elements.topStories.style.display = 'none';
    } else {
        if (elements.suggestionsStrip) elements.suggestionsStrip.style.display = 'none';
        renderTopStories(allArticles);
    }
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
    applyViewMode();
    
    if (viewMode === 'list') {
        filteredArticles.forEach((article, index) => {
            const row = createArticleRow(article, index);
            elements.articlesGrid.appendChild(row);
        });
    } else {
        filteredArticles.forEach((article, index) => {
            const card = createArticleCard(article, index);
            elements.articlesGrid.appendChild(card);
        });
    }
    
    elements.articleCount.textContent = filteredArticles.length;
}

function createArticleRow(article, index) {
    const row = document.createElement('div');
    row.className = 'article-row';
    row.style.animationDelay = `${index * 0.03}s`;
    const isBookmarked = bookmarkedUrls.has(article.link);
    row.innerHTML = `
        <span class="category-badge ${article.category.replace(/\s+/g, '.')}">${escapeHtml(article.category)}</span>
        <div class="article-row-main">
            <a class="article-row-title" href="${escapeHtml(article.link)}" target="_blank" rel="noopener noreferrer">${escapeHtml(article.title)}</a>
            <span class="article-row-meta">${escapeHtml(article.site)} &middot; ${formatTimeAgo(article.published)}</span>
        </div>
        <button class="bookmark-btn ${isBookmarked ? 'bookmarked' : ''}" title="${isBookmarked ? 'Bookmarked' : 'Bookmark'}" data-link="${escapeHtml(article.link)}">
            <i class="${isBookmarked ? 'fas' : 'far'} fa-bookmark"></i>
        </button>
    `;
    row.querySelector('.bookmark-btn').addEventListener('click', function() {
        bookmarkArticle(article, this);
    });
    return row;
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
    
    const isBookmarked = bookmarkedUrls.has(article.link);
    card.innerHTML = `
        <div class="article-header">
            <span class="category-badge ${categoryClass}">${escapeHtml(article.category)}</span>
            <div class="article-actions">
                <button class="bookmark-btn ${isBookmarked ? 'bookmarked' : ''}" title="${isBookmarked ? 'Bookmarked' : 'Bookmark'}">
                    <i class="${isBookmarked ? 'fas' : 'far'} fa-bookmark"></i>
                </button>
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
    
    card.querySelector('.bookmark-btn').addEventListener('click', function() {
        bookmarkArticle(article, this);
    });
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
    elements.articlesGrid.style.display = viewMode === 'list' ? 'flex' : 'grid';
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
    
    // View toggle
    if (elements.viewToggle) {
        elements.viewToggle.addEventListener('click', toggleViewMode);
    }

    // Suggestions dismiss
    if (elements.suggestionsDismiss) {
        elements.suggestionsDismiss.addEventListener('click', () => {
            if (elements.suggestionsStrip) elements.suggestionsStrip.style.display = 'none';
        });
    }

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
    
    // Apply saved view mode
    applyViewMode();

    // Load initial articles
    await fetchArticles();

    // Render top stories (all-category default)
    renderTopStories(allArticles);
    
    // Load trending topics
    await fetchTrendingTopics();

    // Pre-load bookmarked URLs so buttons reflect saved state
    await loadBookmarkedUrls();

    // Populate breaking news ticker
    await initTicker();
    
    // Start auto-refresh
    startAutoRefresh();
}

// Start the application when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

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
    topStoriesCards: document.getElementById('topStoriesCards'),
    header: document.getElementById('siteHeader')
};

// ==================== Theme Management ====================
function initTheme() {
    // Dark is the Optio.News brand default; light is the calm reading variant
    const savedTheme = localStorage.getItem('theme') || 'dark';
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

// ==================== Image helpers ====================
// RSS feeds ship plenty of junk "images": tracking pixels, feed badges, svg logos.
// Only trust a URL that looks like real article photography.
function usableImage(article) {
    const url = (article.image_url || '').trim();
    if (!/^https?:\/\//i.test(url)) return '';
    const lower = url.toLowerCase();
    const junk = ['pixel', 'doubleclick', 'feedburner', 'feedads', 'share-buttons',
                  'gravatar', 'favicon', '1x1', 'spacer', 'blank.'];
    if (junk.some(j => lower.includes(j))) return '';
    if (lower.endsWith('.svg')) return '';
    return url;
}

// Watch a card's image: portrait photos get a portrait frame, broken
// images demote the card to the headline-first treatment.
function attachImageBehavior(img, card, mediaWrap) {
    img.addEventListener('load', () => {
        const w = img.naturalWidth, h = img.naturalHeight;
        if (!w || !h) return;
        if (w < 120 || h < 90) {
            // too small to be a real photo — demote
            demoteToText(card, mediaWrap);
        } else if (h > w * 1.1 && card.classList.contains('news-card')) {
            card.classList.add('news-card--portrait');
        }
    });
    img.addEventListener('error', () => demoteToText(card, mediaWrap));
}

function demoteToText(card, mediaWrap) {
    if (!mediaWrap) return;
    // move the floating controls back into the body before dropping the media
    const badge = mediaWrap.querySelector('.category-badge');
    const bmBtn = mediaWrap.querySelector('.bookmark-btn');
    const body = card.querySelector('.news-card-body');
    if (badge && body) {
        let topline = body.querySelector('.card-topline');
        if (!topline) {
            topline = document.createElement('div');
            topline.className = 'card-topline';
            body.prepend(topline);
        }
        topline.appendChild(badge);
        if (bmBtn) topline.appendChild(bmBtn);
    }
    mediaWrap.remove();
    card.classList.remove('news-card--wide', 'news-card--portrait');
    card.classList.add('news-card--text');
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

        // Server is still doing its first crawl of the feeds — keep the
        // skeletons up and check back in a few seconds.
        if (data.warming && (!data.articles || data.articles.length === 0)) {
            elements.lastUpdated.textContent = 'Warming up your feeds…';
            setTimeout(() => fetchArticles(false), 4000);
            return;
        }

        allArticles = data.articles || [];
        applyFilters();
        updateStats(data);

        hideLoading();

        // If the first paint happened while the server was still warming,
        // the hero, ticker and trending rendered empty — fill them in now.
        if (allArticles.length) {
            if (currentCategory === 'all') renderTopStories(allArticles);
            const track = document.getElementById('tickerTrack');
            if (track && track.children.length === 0) initTicker();
            const trendingList = document.getElementById('trendingList');
            if (trendingList && !trendingList.querySelector('.trending-item')) fetchTrendingTopics();
        }
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
            <span class="trending-rank" aria-hidden="true">${index + 1}</span>
            <div class="trending-item-content">
                <div class="trending-item-header">
                    <div class="trending-item-name">${escapeHtml(topic.topic)}</div>
                    <span class="trending-item-count" title="Mentioned in ${topic.count} articles">${topic.count}x</span>
                </div>
                ${topic.articles && topic.articles.length > 0 ? `
                    <div class="trending-item-articles">
                        ${topic.articles.slice(0, 2).map(article => `
                            <div class="trending-item-article">
                                <a href="${escapeHtml(article.link)}" target="_blank" rel="noopener noreferrer">
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
                    <i class="fas fa-plus" aria-hidden="true"></i> Follow
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
        if (btn) { btn.innerHTML = '<i class="fas fa-check"></i> Added'; btn.style.background = '#34D399'; }
    } catch {
        if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-plus"></i> Follow'; }
    }
}

// ==================== Lead Stories hero mosaic ====================
// Composition (desktop, 4-col × 3-row grid — a perfect rectangle):
//   lead 2×2 | tall 1×2 | two singles stacked | wide 2×1 + two singles
// Slot classes are assigned by position; WHICH article lands in a visual
// slot is content-aware: stories with real photography fill the image
// slots, text-only stories get the gradient headline tile.
const HERO_SLOTS = [
    'hero-card--lead',   // 2×2
    'hero-card--tall',   // 1×2
    '',                  // 1×1
    '',                  // 1×1
    'hero-card--wide',   // 2×1 (row 3)
    '',                  // 1×1
    ''                   // 1×1
];

function renderTopStories(articles) {
    if (!elements.topStories || !articles.length) return;
    const HERO_COUNT = HERO_SLOTS.length;

    // Most recent story per unique category first, then fill with next-recent.
    const sorted = [...articles].sort((a, b) => new Date(b.published) - new Date(a.published));
    const seen = new Set();
    let picks = [];
    for (const art of sorted) {
        if (!seen.has(art.category)) {
            seen.add(art.category);
            picks.push(art);
        }
        if (picks.length >= HERO_COUNT) break;
    }
    if (picks.length < HERO_COUNT) {
        const pickedLinks = new Set(picks.map(a => a.link));
        for (const art of sorted) {
            if (!pickedLinks.has(art.link)) {
                picks.push(art);
                pickedLinks.add(art.link);
            }
            if (picks.length >= HERO_COUNT) break;
        }
    }
    if (picks.length === 0) return;

    // Image-led stories take the big visual slots (lead, tall, wide first).
    picks.sort((a, b) => (usableImage(b) ? 1 : 0) - (usableImage(a) ? 1 : 0));

    elements.topStoriesCards.innerHTML = '';
    picks.forEach((art, i) => {
        const slot = HERO_SLOTS[i] || '';
        const img = usableImage(art);
        const card = document.createElement('a');
        card.className = `hero-card ${slot} ${img ? '' : 'hero-card--text'}`.trim();
        card.href = art.link;
        card.target = '_blank';
        card.rel = 'noopener noreferrer';
        card.style.animationDelay = `${i * 0.07}s`;

        const isLead = slot === 'hero-card--lead';
        const summary = isLead ? cleanSummaryText(art.summary).substring(0, 180) : '';

        card.innerHTML = `
            ${img ? `<img src="${escapeHtml(img)}" alt="" ${i === 0 ? 'fetchpriority="high"' : 'loading="lazy"'}>` : ''}
            <div class="hero-card-body">
                <span class="hero-kicker">${escapeHtml(art.category)}</span>
                <h3 class="hero-title">${escapeHtml(art.title)}</h3>
                ${summary ? `<p class="hero-summary">${escapeHtml(summary)}</p>` : ''}
                <span class="hero-meta"><i class="far fa-clock" aria-hidden="true"></i> ${formatTimeAgo(art.published)} &middot; ${escapeHtml(art.site)}</span>
            </div>
        `;
        const imgEl = card.querySelector('img');
        if (imgEl) {
            imgEl.addEventListener('error', () => {
                imgEl.remove();
                card.classList.add('hero-card--text');
            });
        }
        elements.topStoriesCards.appendChild(card);
    });
    elements.topStories.style.display = 'block';
}

// ==================== Toast ====================
function showToast(message, type = 'success') {
    let el = document.getElementById('appToast');
    if (!el) {
        el = document.createElement('div');
        el.id = 'appToast';
        el.setAttribute('role', 'status');
        el.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);padding:11px 22px;border-radius:999px;font-size:.9rem;font-weight:600;z-index:9999;opacity:0;transition:opacity .25s;pointer-events:none;color:#fff;box-shadow:0 8px 24px rgba(2,4,18,.45);';
        document.body.appendChild(el);
    }
    el.textContent = message;
    el.style.background = type === 'error'
        ? '#dc2f4b'
        : 'linear-gradient(115deg,#4EA1FF,#7C5CFF 52%,#A855F7)';
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
            image_url: usableImage(article),
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
                if (btn) {
                    btn.classList.add('bookmarked');
                    btn.title = 'Bookmarked';
                    btn.disabled = false;
                    const icon = btn.querySelector('i');
                    if (icon) icon.className = 'fas fa-bookmark';
                }
                showToast('Saved to bookmarks');
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
    row.style.animationDelay = `${Math.min(index, 20) * 0.02}s`;
    const isBookmarked = bookmarkedUrls.has(article.link);
    const img = usableImage(article);
    row.innerHTML = `
        ${img ? `<img class="article-row-thumb" src="${escapeHtml(img)}" alt="" loading="lazy">` : ''}
        <span class="category-badge ${article.category.replace(/\s+/g, '.')}">${escapeHtml(article.category)}</span>
        <div class="article-row-main">
            <a class="article-row-title" href="${escapeHtml(article.link)}" target="_blank" rel="noopener noreferrer">${escapeHtml(article.title)}</a>
            <span class="article-row-meta">${escapeHtml(article.site)} &middot; ${formatTimeAgo(article.published)}</span>
        </div>
        <button class="bookmark-btn ${isBookmarked ? 'bookmarked' : ''}" title="${isBookmarked ? 'Bookmarked' : 'Bookmark'}" aria-label="Bookmark this article" data-link="${escapeHtml(article.link)}">
            <i class="${isBookmarked ? 'fas' : 'far'} fa-bookmark" aria-hidden="true"></i>
        </button>
    `;
    const thumb = row.querySelector('.article-row-thumb');
    if (thumb) thumb.addEventListener('error', () => thumb.remove());
    row.querySelector('.bookmark-btn').addEventListener('click', function() {
        bookmarkArticle(article, this);
    });
    return row;
}

// Content-aware card variant selection.
// - no usable image                       → headline-first text card
// - image + meaty summary, every ~5th     → wide cinematic (spans 2 columns)
// - portrait photography (detected onload)→ portrait frame
// - everything else                       → standard visual card
function pickCardVariant(article, index) {
    const img = usableImage(article);
    if (!img) return 'text';
    const summaryLen = cleanSummaryText(article.summary).length;
    if (summaryLen > 140 && index % 5 === 2) return 'wide';
    return 'visual';
}

function createArticleCard(article, index) {
    const card = document.createElement('article');
    const variant = pickCardVariant(article, index);
    card.className = `news-card${variant === 'text' ? ' news-card--text' : ''}${variant === 'wide' ? ' news-card--wide' : ''}`;
    card.style.animationDelay = `${Math.min(index, 16) * 0.04}s`;

    // Format category for class name
    const categoryClass = article.category.replace(/\s+/g, '.');

    // Strip HTML tags from summary and limit length
    const cleanSummary = cleanSummaryText(article.summary);
    const truncatedSummary = cleanSummary.length > 220
        ? cleanSummary.substring(0, 220) + '…'
        : cleanSummary;

    const isBookmarked = bookmarkedUrls.has(article.link);
    const img = variant === 'text' ? '' : usableImage(article);
    const bookmarkBtn = `
        <button class="bookmark-btn ${isBookmarked ? 'bookmarked' : ''}" title="${isBookmarked ? 'Bookmarked' : 'Bookmark'}" aria-label="Bookmark this article">
            <i class="${isBookmarked ? 'fas' : 'far'} fa-bookmark" aria-hidden="true"></i>
        </button>`;

    card.innerHTML = `
        ${img ? `
        <div class="news-card-media">
            <img src="${escapeHtml(img)}" alt="" ${index < 3 ? '' : 'loading="lazy"'}>
            <span class="category-badge ${categoryClass}">${escapeHtml(article.category)}</span>
            ${bookmarkBtn}
        </div>` : ''}
        <div class="news-card-body">
            ${img ? '' : `
            <div class="card-topline">
                <span class="category-badge ${categoryClass}">${escapeHtml(article.category)}</span>
                ${bookmarkBtn}
            </div>`}
            <h3 class="article-title">
                <a href="${escapeHtml(article.link)}" target="_blank" rel="noopener noreferrer">
                    ${escapeHtml(article.title)}
                </a>
            </h3>
            ${truncatedSummary ? `<p class="article-summary">${escapeHtml(truncatedSummary)}</p>` : ''}
            <div class="article-footer">
                <div class="article-source">
                    <i class="fas fa-globe" aria-hidden="true"></i>
                    ${escapeHtml(article.site)}
                </div>
                <div class="article-time">
                    <i class="far fa-clock" aria-hidden="true"></i>
                    ${formatTimeAgo(article.published)}
                </div>
            </div>
        </div>
    `;

    const mediaWrap = card.querySelector('.news-card-media');
    const imgEl = mediaWrap ? mediaWrap.querySelector('img') : null;
    if (imgEl) attachImageBehavior(imgEl, card, mediaWrap);

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

// Some feeds ship junk summaries ("null", "No summary available", one word).
// Treat those as no summary so cards fall back to headline-led layouts.
function cleanSummaryText(raw) {
    const text = stripHtmlTags(raw || '').trim();
    if (!text || text.length < 8) return '';
    if (/^(null|undefined|no summary available\.?)$/i.test(text)) return '';
    return text;
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
    const skGrid = elements.loading.querySelector('.skeleton-grid');
    if (skGrid && !skGrid.children.length) {
        skGrid.innerHTML = Array.from({ length: 6 }, () => `
            <div class="sk-card">
                <div class="sk-img"></div>
                <div class="sk-line"></div>
                <div class="sk-line"></div>
            </div>
        `).join('');
    }
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
            <h3 style="color: var(--text-primary); margin-bottom: 0.5rem;">Couldn't load the news</h3>
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

    // Header condenses after scrolling
    if (elements.header) {
        let scrollTick = false;
        window.addEventListener('scroll', () => {
            if (scrollTick) return;
            scrollTick = true;
            requestAnimationFrame(() => {
                elements.header.classList.toggle('scrolled', window.scrollY > 40);
                scrollTick = false;
            });
        }, { passive: true });
    }
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

    // Render lead-stories hero (all-category default)
    renderTopStories(allArticles);

    // Load trending topics
    await fetchTrendingTopics();

    // Pre-load bookmarked URLs so buttons reflect saved state
    await loadBookmarkedUrls();

    // Populate latest-headlines ticker
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

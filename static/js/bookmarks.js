// ==================== State ====================
let bookmarks = [];
let activeTagFilter = null;
let editingId = null;

// ==================== DOM ====================
const bmGrid = document.getElementById('bmGrid');
const bmSearch = document.getElementById('bmSearch');
const tagFilters = document.getElementById('tagFilters');
const addBookmarkBtn = document.getElementById('addBookmarkBtn');
const exportBtn = document.getElementById('exportBtn');
const modal = document.getElementById('bmModal');
const modalTitle = document.getElementById('modalTitle');
const modalForm = document.getElementById('modalForm');
const urlInput = document.getElementById('bmUrl');
const titleInput = document.getElementById('bmTitle');
const descInput = document.getElementById('bmDesc');
const tagsInput = document.getElementById('bmTags');
const imageInput = document.getElementById('bmImage');
const autoFillBtn = document.getElementById('autoFillBtn');
const cancelBtn = document.getElementById('cancelModal');
const toastContainer = document.getElementById('toastContainer');
const emptyState = document.getElementById('bmEmpty');
const bmCount = document.getElementById('bmCount');

// ==================== Toast ====================
function showToast(message, type = 'success') {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
        <i class="fas fa-${type === 'success' ? 'check-circle' : 'exclamation-circle'}"></i>
        <span>${escapeHtml(message)}</span>
    `;
    toastContainer.appendChild(toast);
    setTimeout(() => toast.classList.add('show'), 10);
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

function escapeHtml(text) {
    const d = document.createElement('div');
    d.textContent = String(text);
    return d.innerHTML;
}

// ==================== API ====================
async function loadBookmarks() {
    try {
        const res = await fetch('/api/bookmarks');
        if (!res.ok) throw new Error('Failed to load');
        const data = await res.json();
        bookmarks = data.bookmarks || [];
        renderAll();
    } catch (e) {
        showToast('Could not load bookmarks', 'error');
    }
}

async function saveBookmark() {
    const url = urlInput.value.trim();
    const title = titleInput.value.trim();
    if (!url || !title) {
        showToast('URL and title are required', 'error');
        return;
    }

    const payload = {
        url,
        title,
        description: descInput.value.trim(),
        image_url: imageInput.value.trim(),
        tags: tagsInput.value.split(',').map(t => t.trim()).filter(Boolean)
    };

    try {
        let res;
        if (editingId) {
            res = await fetch(`/api/bookmarks/${editingId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
        } else {
            res = await fetch('/api/bookmarks', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
        }
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.error || 'Save failed');
        }
        closeModal();
        showToast(editingId ? 'Bookmark updated' : 'Bookmark saved');
        await loadBookmarks();
    } catch (e) {
        showToast(e.message, 'error');
    }
}

async function deleteBookmark(id) {
    if (!confirm('Delete this bookmark?')) return;
    try {
        const res = await fetch(`/api/bookmarks/${id}`, { method: 'DELETE' });
        if (!res.ok) throw new Error('Delete failed');
        showToast('Bookmark deleted');
        await loadBookmarks();
    } catch (e) {
        showToast(e.message, 'error');
    }
}

async function autoFill() {
    const url = urlInput.value.trim();
    if (!url) { showToast('Enter a URL first', 'error'); return; }
    autoFillBtn.disabled = true;
    autoFillBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
    try {
        const res = await fetch(`/api/preview?url=${encodeURIComponent(url)}`);
        if (!res.ok) throw new Error();
        const data = await res.json();
        if (data.title && !titleInput.value) titleInput.value = data.title;
        if (data.description && !descInput.value) descInput.value = data.description;
        if (data.image && !imageInput.value) imageInput.value = data.image;
        showToast('Details filled in');
    } catch {
        showToast('Could not fetch page details', 'error');
    } finally {
        autoFillBtn.disabled = false;
        autoFillBtn.innerHTML = '<i class="fas fa-magic"></i> Auto-fill';
    }
}

// ==================== Render ====================
function getAllTags() {
    const all = new Set();
    bookmarks.forEach(b => (b.tags || []).forEach(t => all.add(t)));
    return [...all].sort();
}

function renderTagFilters() {
    const tags = getAllTags();
    tagFilters.innerHTML = `<button class="tag-filter-btn ${!activeTagFilter ? 'active' : ''}" data-tag="">All</button>`;
    tags.forEach(t => {
        tagFilters.innerHTML += `<button class="tag-filter-btn ${activeTagFilter === t ? 'active' : ''}" data-tag="${escapeHtml(t)}">${escapeHtml(t)}</button>`;
    });
}

function getFilteredBookmarks() {
    const q = bmSearch ? bmSearch.value.toLowerCase().trim() : '';
    return bookmarks.filter(b => {
        const matchTag = !activeTagFilter || (b.tags || []).includes(activeTagFilter);
        const matchSearch = !q ||
            b.title.toLowerCase().includes(q) ||
            (b.description || '').toLowerCase().includes(q) ||
            b.url.toLowerCase().includes(q);
        return matchTag && matchSearch;
    });
}

function renderAll() {
    renderTagFilters();
    const filtered = getFilteredBookmarks();
    if (bmCount) bmCount.textContent = filtered.length;

    if (filtered.length === 0) {
        bmGrid.innerHTML = '';
        if (emptyState) emptyState.style.display = 'block';
        return;
    }
    if (emptyState) emptyState.style.display = 'none';

    bmGrid.innerHTML = filtered.map(b => createBookmarkCard(b)).join('');
}

function createBookmarkCard(b) {
    const tags = (b.tags || []).map(t => `<span class="bm-tag">${escapeHtml(t)}</span>`).join('');
    const img = b.image_url
        ? `<div class="bm-image"><img src="${escapeHtml(b.image_url)}" alt="" loading="lazy" onerror="this.parentElement.style.display='none'"></div>`
        : '';
    const desc = b.description
        ? `<p class="bm-desc">${escapeHtml(b.description.substring(0, 160))}${b.description.length > 160 ? '…' : ''}</p>`
        : '';
    const host = (() => { try { return new URL(b.url).hostname.replace('www.', ''); } catch { return b.url; } })();

    return `
    <div class="bm-card" data-id="${b.id}">
        ${img}
        <div class="bm-body">
            <h3 class="bm-title">
                <a href="${escapeHtml(b.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(b.title)}</a>
            </h3>
            ${desc}
            <div class="bm-meta">
                <span class="bm-host"><i class="fas fa-globe"></i> ${escapeHtml(host)}</span>
                <span class="bm-date">${formatDate(b.created_at)}</span>
            </div>
            ${tags ? `<div class="bm-tags">${tags}</div>` : ''}
        </div>
        <div class="bm-actions">
            <button class="bm-action-btn" onclick="openEditModal(${b.id})" title="Edit"><i class="fas fa-pencil-alt"></i></button>
            <button class="bm-action-btn bm-delete-btn" onclick="deleteBookmark(${b.id})" title="Delete"><i class="fas fa-trash"></i></button>
        </div>
    </div>`;
}

function formatDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

// ==================== Modal ====================
function openAddModal() {
    editingId = null;
    modalTitle.textContent = 'Add Bookmark';
    modalForm.reset();
    modal.classList.add('open');
    urlInput.focus();
}

function openEditModal(id) {
    const b = bookmarks.find(x => x.id === id);
    if (!b) return;
    editingId = id;
    modalTitle.textContent = 'Edit Bookmark';
    urlInput.value = b.url;
    titleInput.value = b.title;
    descInput.value = b.description || '';
    tagsInput.value = (b.tags || []).join(', ');
    imageInput.value = b.image_url || '';
    modal.classList.add('open');
    titleInput.focus();
}

function closeModal() {
    modal.classList.remove('open');
    editingId = null;
}

// ==================== Export ====================
function exportMarkdown() {
    const filtered = getFilteredBookmarks();
    if (filtered.length === 0) { showToast('No bookmarks to export', 'error'); return; }

    const lines = ['# Bookmarks\n'];
    filtered.forEach(b => {
        lines.push(`## [${b.title}](${b.url})`);
        if (b.description) lines.push(`\n${b.description}\n`);
        if (b.tags && b.tags.length) lines.push(`**Tags:** ${b.tags.join(', ')}\n`);
        lines.push('---\n');
    });

    const blob = new Blob([lines.join('\n')], { type: 'text/markdown' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'bookmarks.md';
    a.click();
    URL.revokeObjectURL(a.href);
    showToast(`Exported ${filtered.length} bookmarks`);
}

// ==================== Event Listeners ====================
addBookmarkBtn.addEventListener('click', openAddModal);
cancelBtn.addEventListener('click', closeModal);
exportBtn.addEventListener('click', exportMarkdown);

modal.addEventListener('click', e => {
    if (e.target === modal) closeModal();
});

document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && modal.classList.contains('open')) closeModal();
});

modalForm.addEventListener('submit', e => {
    e.preventDefault();
    saveBookmark();
});

autoFillBtn.addEventListener('click', autoFill);

if (bmSearch) {
    let searchTimer;
    bmSearch.addEventListener('input', () => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(renderAll, 250);
    });
}

tagFilters.addEventListener('click', e => {
    const btn = e.target.closest('.tag-filter-btn');
    if (!btn) return;
    activeTagFilter = btn.dataset.tag || null;
    renderAll();
});

// ==================== Init ====================
// Apply saved theme
const saved = localStorage.getItem('theme') || 'light';
document.documentElement.setAttribute('data-theme', saved);

loadBookmarks();

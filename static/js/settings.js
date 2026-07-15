// ==================== Settings dropdown (shared across pages) ====================
(function () {
    const btn = document.getElementById('settingsBtn');
    const menu = document.getElementById('settingsMenu');
    if (!btn || !menu) return;

    function openMenu() {
        menu.hidden = false;
        btn.setAttribute('aria-expanded', 'true');
    }
    function closeMenu() {
        menu.hidden = true;
        btn.setAttribute('aria-expanded', 'false');
    }

    btn.addEventListener('click', (e) => {
        e.stopPropagation();
        if (menu.hidden) {
            openMenu();
            loadHiddenFeeds();
        } else {
            closeMenu();
        }
    });
    document.addEventListener('click', (e) => {
        if (!menu.hidden && !menu.contains(e.target) && e.target !== btn) closeMenu();
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !menu.hidden) { closeMenu(); btn.focus(); }
    });

    // --- Show/hide headline ticker (persisted) ---
    const tickerCheck = document.getElementById('settingsTicker');
    const tickerBar = document.querySelector('.ticker-bar');
    function applyTickerPref() {
        const show = localStorage.getItem('showTicker') !== 'false';
        if (tickerCheck) tickerCheck.checked = show;
        if (tickerBar) tickerBar.style.display = show ? '' : 'none';
    }
    if (tickerCheck) {
        tickerCheck.addEventListener('change', () => {
            localStorage.setItem('showTicker', String(tickerCheck.checked));
            applyTickerPref();
        });
    }
    applyTickerPref();

    // --- Default news view (grid | list) ---
    const viewSelect = document.getElementById('settingsViewMode');
    if (viewSelect) {
        viewSelect.value = localStorage.getItem('viewMode') || 'grid';
        viewSelect.addEventListener('change', () => {
            localStorage.setItem('viewMode', viewSelect.value);
            // Re-render live if the news page is open
            if (typeof window.optioSetViewMode === 'function') {
                window.optioSetViewMode(viewSelect.value);
            }
        });
    }

    // --- Article density (comfortable | compact) ---
    const densitySelect = document.getElementById('settingsDensity');
    function applyDensity() {
        const d = localStorage.getItem('density') || 'comfortable';
        document.documentElement.setAttribute('data-density', d);
        if (densitySelect) densitySelect.value = d;
    }
    if (densitySelect) {
        densitySelect.addEventListener('change', () => {
            localStorage.setItem('density', densitySelect.value);
            applyDensity();
        });
    }
    applyDensity();

    // --- Auto-refresh interval ---
    const refreshSelect = document.getElementById('settingsRefresh');
    if (refreshSelect) {
        refreshSelect.value = localStorage.getItem('refreshMins') || '30';
        refreshSelect.addEventListener('change', () => {
            localStorage.setItem('refreshMins', refreshSelect.value);
            if (typeof window.optioRestartAutoRefresh === 'function') {
                window.optioRestartAutoRefresh();
            }
        });
    }

    // --- Hidden feeds: list + one-click restore ---
    const hiddenFeedsBox = document.getElementById('settingsHiddenFeeds');
    async function loadHiddenFeeds() {
        if (!hiddenFeedsBox) return;
        try {
            const res = await fetch('/api/feeds');
            if (!res.ok) throw new Error();
            const data = await res.json();
            const hidden = (data.feeds || []).filter(f => f.hidden);
            if (!hidden.length) {
                hiddenFeedsBox.innerHTML = '<p class="settings-feeds-empty">No hidden feeds</p>';
                return;
            }
            hiddenFeedsBox.innerHTML = '';
            hidden.forEach(f => {
                const row = document.createElement('div');
                row.className = 'settings-feed-row';
                const name = document.createElement('span');
                name.className = 'settings-feed-name';
                name.textContent = f.name;
                name.title = f.url;
                const restore = document.createElement('button');
                restore.type = 'button';
                restore.className = 'settings-feed-restore';
                restore.textContent = 'Restore';
                restore.addEventListener('click', async () => {
                    restore.disabled = true;
                    try {
                        const r = await fetch('/api/feeds/unhide', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ url: f.url })
                        });
                        if (!r.ok) throw new Error();
                        row.remove();
                        if (!hiddenFeedsBox.querySelector('.settings-feed-row')) {
                            hiddenFeedsBox.innerHTML = '<p class="settings-feeds-empty">No hidden feeds</p>';
                        }
                    } catch {
                        restore.disabled = false;
                    }
                });
                row.appendChild(name);
                row.appendChild(restore);
                hiddenFeedsBox.appendChild(row);
            });
        } catch {
            hiddenFeedsBox.innerHTML = '<p class="settings-feeds-empty">Couldn\'t load feeds</p>';
        }
    }

    // --- Export bookmarks as Markdown ---
    const exportBtn = document.getElementById('settingsExport');
    if (exportBtn) {
        exportBtn.addEventListener('click', async () => {
            exportBtn.disabled = true;
            try {
                const res = await fetch('/api/bookmarks');
                if (!res.ok) throw new Error();
                const data = await res.json();
                const items = data.bookmarks || [];
                if (!items.length) {
                    alert('No bookmarks to export yet.');
                    return;
                }
                const lines = ['# Bookmarks\n'];
                items.forEach(b => {
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
            } catch {
                alert("Couldn't export bookmarks. Please try again.");
            } finally {
                exportBtn.disabled = false;
                closeMenu();
            }
        });
    }

    // --- Delete account ---
    const deleteBtn = document.getElementById('settingsDeleteAccount');
    if (deleteBtn) {
        deleteBtn.addEventListener('click', async () => {
            const sure = confirm('Delete your account? This permanently removes your account, bookmarks, and feed preferences.');
            if (!sure) return;
            try {
                const res = await fetch('/api/account', { method: 'DELETE' });
                if (!res.ok) throw new Error();
                window.location.href = '/login';
            } catch {
                alert("Couldn't delete the account. Please try again.");
            }
        });
    }
})();

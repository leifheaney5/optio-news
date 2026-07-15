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
        menu.hidden ? openMenu() : closeMenu();
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

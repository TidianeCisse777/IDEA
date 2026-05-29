// ui-shell.js — sidebar toggle, mode switcher, sidebar-bottom sync

// ── Sidebar toggle ──
const sidebar = document.getElementById('sidebar');
const sidebarToggle = document.getElementById('sidebarToggle');
const sidebarOpenBtn = document.getElementById('sidebarOpenBtn');
const mobileOverlay = document.getElementById('mobileOverlay');

const SIDEBAR_KEY = 'idea-sidebar-collapsed';
if (localStorage.getItem(SIDEBAR_KEY) === 'true') sidebar.classList.add('collapsed');

sidebarToggle.addEventListener('click', () => {
    if (window.innerWidth <= 900) {
        // Mobile: close the slide-over instead of collapsing to icon-strip
        sidebar.classList.remove('mobile-open');
        mobileOverlay.classList.remove('active');
    } else {
        sidebar.classList.toggle('collapsed');
        localStorage.setItem(SIDEBAR_KEY, sidebar.classList.contains('collapsed'));
    }
});
sidebarOpenBtn.addEventListener('click', () => {
    sidebar.classList.add('mobile-open');
    mobileOverlay.classList.add('active');
});
mobileOverlay.addEventListener('click', () => {
    sidebar.classList.remove('mobile-open');
    mobileOverlay.classList.remove('active');
});

// ── Mode switcher ──
const MODE_KEY = 'idea-mode';
const modeButtons = document.querySelectorAll('.mode-btn');

const MODE_PLACEHOLDERS = {
    analyse: "Posez votre question sur les copépodes, chargez des données ou décrivez votre analyse…",
    contexte: "Décrivez votre question de recherche ou hypothèse, puis comment les données s'inscrivent dans votre démarche…"
};

function applyMode(mode) {
    modeButtons.forEach(btn => btn.classList.toggle('active', btn.dataset.mode === mode));
    document.body.dataset.mode = mode;
    localStorage.setItem(MODE_KEY, mode);

    const input = document.getElementById('messageInput');
    if (input) input.placeholder = MODE_PLACEHOLDERS[mode] || MODE_PLACEHOLDERS.analyse;

    if (window.refreshWelcome) window.refreshWelcome();
}

applyMode(localStorage.getItem(MODE_KEY) || 'analyse');

modeButtons.forEach(btn => {
    btn.addEventListener('click', () => applyMode(btn.dataset.mode));
});

// ── Sync sidebar-bottom height with main footer ──
function syncSidebarBottom() {
    const chatFooter = document.querySelector('.chat-footer');
    const sidebarBottom = document.querySelector('.sidebar-bottom');
    if (!chatFooter || !sidebarBottom) return;
    sidebarBottom.style.minHeight = chatFooter.getBoundingClientRect().height + 'px';
}

requestAnimationFrame(() => {
    syncSidebarBottom();
    window.addEventListener('resize', syncSidebarBottom);
});

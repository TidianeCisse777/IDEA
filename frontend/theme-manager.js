// theme-manager.js — gestion du thème clair/sombre

const THEME_STORAGE_KEY = 'idea-theme';
const themeToggleInputs = document.querySelectorAll('[data-theme-toggle]');

function applyTheme(theme = 'dark') {
    document.body.classList.remove('theme-light', 'theme-dark');
    document.body.classList.add(`theme-${theme}`);
    themeToggleInputs.forEach((input) => { input.checked = (theme === 'dark'); });
    const iconDark = document.querySelector('.theme-icon-dark');
    const iconLight = document.querySelector('.theme-icon-light');
    if (iconDark) iconDark.style.display = theme === 'dark' ? 'inline' : 'none';
    if (iconLight) iconLight.style.display = theme === 'light' ? 'inline' : 'none';
}

function initializeTheme() {
    try {
        const saved = localStorage.getItem(THEME_STORAGE_KEY) || 'dark';
        localStorage.setItem(THEME_STORAGE_KEY, saved);
        applyTheme(saved);
    } catch (error) {
        applyTheme('dark');
    }
}

initializeTheme();

document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('themeToggleButton');
    if (btn) {
        btn.addEventListener('click', () => {
            const current = document.body.classList.contains('theme-dark') ? 'dark' : 'light';
            const next = current === 'dark' ? 'light' : 'dark';
            localStorage.setItem(THEME_STORAGE_KEY, next);
            applyTheme(next);
        });
    }
});

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { applyTheme, initializeTheme, THEME_STORAGE_KEY };
}

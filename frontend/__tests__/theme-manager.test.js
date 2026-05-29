/**
 * @jest-environment jsdom
 *
 * theme-manager — applyTheme + initializeTheme localStorage round-trip.
 */

const { applyTheme, initializeTheme, THEME_STORAGE_KEY } = require('../theme-manager.js');

beforeEach(() => {
    window.localStorage.clear();
    document.body.className = '';
    document.head.innerHTML = '';
});

describe('applyTheme', () => {
    test('applies theme-dark class to body', () => {
        applyTheme('dark');
        expect(document.body.classList.contains('theme-dark')).toBe(true);
        expect(document.body.classList.contains('theme-light')).toBe(false);
    });

    test('applies theme-light class to body', () => {
        applyTheme('light');
        expect(document.body.classList.contains('theme-light')).toBe(true);
        expect(document.body.classList.contains('theme-dark')).toBe(false);
    });

    test('switches from dark to light cleanly', () => {
        applyTheme('dark');
        applyTheme('light');
        expect(document.body.classList.contains('theme-light')).toBe(true);
        expect(document.body.classList.contains('theme-dark')).toBe(false);
    });

    test('shows/hides theme icons based on theme', () => {
        document.body.innerHTML = '<i class="theme-icon-dark"></i><i class="theme-icon-light"></i>';
        applyTheme('dark');
        expect(document.querySelector('.theme-icon-dark').style.display).toBe('inline');
        expect(document.querySelector('.theme-icon-light').style.display).toBe('none');

        applyTheme('light');
        expect(document.querySelector('.theme-icon-dark').style.display).toBe('none');
        expect(document.querySelector('.theme-icon-light').style.display).toBe('inline');
    });
});

describe('initializeTheme', () => {
    test('defaults to dark when no value in localStorage', () => {
        initializeTheme();
        expect(document.body.classList.contains('theme-dark')).toBe(true);
        expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark');
    });

    test('applies saved theme from localStorage', () => {
        window.localStorage.setItem(THEME_STORAGE_KEY, 'light');
        initializeTheme();
        expect(document.body.classList.contains('theme-light')).toBe(true);
        expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('light');
    });
});

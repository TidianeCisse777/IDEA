// modal-utils.js — utilitaires partagés pour l'ouverture/fermeture des modales

const ModalUtils = (function () {
    const CLOSE_ANIMATION_MS = 170;

    function open(el) {
        if (!el) return;
        el.classList.remove('is-closing');
        el.style.display = 'block';
        document.body.style.overflow = 'hidden';
        requestAnimationFrame(() => {
            el.classList.add('is-open');
        });
    }

    function close(el) {
        if (!el) return;
        el.classList.remove('is-open');
        el.classList.add('is-closing');
        window.setTimeout(() => {
            if (!el.classList.contains('is-closing')) return;
            el.classList.remove('is-closing');
            el.style.display = 'none';
        }, CLOSE_ANIMATION_MS);
        document.body.style.overflow = '';
    }

    // Attache les comportements standard : clic extérieur + Échap → fermeture
    function bindDismiss(el, closeFn) {
        window.addEventListener('click', (e) => {
            if (e.target === el) closeFn();
        });
        document.addEventListener('keydown', (e) => {
            if (
                e.key === 'Escape'
                && el
                && (el.classList.contains('is-open') || el.style.display === 'block')
            ) {
                closeFn();
            }
        });
    }

    return { open, close, bindDismiss };
})();

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { ModalUtils };
}

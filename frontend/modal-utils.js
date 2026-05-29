// modal-utils.js — utilitaires partagés pour l'ouverture/fermeture des modales

const ModalUtils = (function () {
    function open(el) {
        if (!el) return;
        el.style.display = 'block';
        document.body.style.overflow = 'hidden';
    }

    function close(el) {
        if (!el) return;
        el.style.display = 'none';
        document.body.style.overflow = '';
    }

    // Attache les comportements standard : clic extérieur + Échap → fermeture
    function bindDismiss(el, closeFn) {
        window.addEventListener('click', (e) => {
            if (e.target === el) closeFn();
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && el && el.style.display === 'block') closeFn();
        });
    }

    return { open, close, bindDismiss };
})();

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { ModalUtils };
}

/**
 * @jest-environment jsdom
 *
 * ModalUtils — open/close/bindDismiss for shared modal behaviour.
 */

const { ModalUtils } = require('../modal-utils.js');

function makeModal() {
    document.body.innerHTML = '<div id="m" class="modal" style="display:none"></div>';
    return document.getElementById('m');
}

beforeEach(() => {
    document.body.innerHTML = '';
    document.body.style.overflow = '';
});

describe('ModalUtils.open', () => {
    test('sets display=block and locks body scroll', () => {
        const m = makeModal();
        ModalUtils.open(m);
        expect(m.style.display).toBe('block');
        expect(document.body.style.overflow).toBe('hidden');
    });

    test('does not crash on null element', () => {
        expect(() => ModalUtils.open(null)).not.toThrow();
        expect(document.body.style.overflow).toBe('');
    });
});

describe('ModalUtils.close', () => {
    test('sets display=none and restores body scroll', () => {
        const m = makeModal();
        ModalUtils.open(m);
        ModalUtils.close(m);
        expect(m.style.display).toBe('none');
        expect(document.body.style.overflow).toBe('');
    });

    test('does not crash on null element', () => {
        expect(() => ModalUtils.close(null)).not.toThrow();
    });
});

describe('ModalUtils.bindDismiss', () => {
    test('clicking on the modal backdrop triggers closeFn', () => {
        const m = makeModal();
        const closeFn = jest.fn();
        ModalUtils.bindDismiss(m, closeFn);

        // simulate click whose target is the modal element itself (backdrop)
        const event = new window.MouseEvent('click', { bubbles: true });
        m.dispatchEvent(event);

        expect(closeFn).toHaveBeenCalledTimes(1);
    });

    test('Escape key triggers closeFn when modal is visible', () => {
        const m = makeModal();
        m.style.display = 'block';
        const closeFn = jest.fn();
        ModalUtils.bindDismiss(m, closeFn);

        document.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape' }));
        expect(closeFn).toHaveBeenCalledTimes(1);
    });

    test('Escape key does not trigger closeFn when modal hidden', () => {
        const m = makeModal();
        m.style.display = 'none';
        const closeFn = jest.fn();
        ModalUtils.bindDismiss(m, closeFn);

        document.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape' }));
        expect(closeFn).not.toHaveBeenCalled();
    });
});

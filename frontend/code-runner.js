// code-runner.js — suivi STDOUT/STDERR, panneaux de sortie, state des chunks de code

const STD_STREAM_RECIPIENTS = ['stdout', 'stderr'];

function resetStdoutState() {
    codeConsoleMap.clear();
    lastExecutableCodeId = null;
    pendingConsoleParentId = null;
    activeMessageIds.clear();
    activeLineCodeId = null;
    isActiveLineRunning = false;
    removeActiveLineSpinner();
}
window.resetStdoutState = resetStdoutState;

function normalizeStdStreamMessage(message) {
    if (!message) return message;
    if (!message.type && message.message_type) {
        message.type = message.message_type;
    }
    if (!message.format && message.message_format) {
        message.format = message.message_format;
    }
    if (!message.recipient && message.message_recipient) {
        message.recipient = message.message_recipient;
    }

    const recipient = (message.recipient || '').toLowerCase();
    if ((message.type === 'message' || message.type === 'text') && STD_STREAM_RECIPIENTS.includes(recipient)) {
        message.type = 'console';
        message.format = message.format || recipient;
    } else if (message.type === 'console' && !message.format && STD_STREAM_RECIPIENTS.includes(recipient)) {
        message.format = recipient;
    }
    return message;
}

function normalizeIncomingChunk(chunk) {
    if (!chunk) return chunk;
    if (chunk.recipient) {
        chunk.recipient = chunk.recipient.toLowerCase();
    }
    if ((chunk.type === 'message' || chunk.type === 'text') &&
        STD_STREAM_RECIPIENTS.includes(chunk.recipient || '')) {
        chunk.type = 'console';
        chunk.format = chunk.format || chunk.recipient;
    } else if (chunk.type === 'console' && !chunk.format && STD_STREAM_RECIPIENTS.includes(chunk.recipient || '')) {
        chunk.format = chunk.recipient;
    }
    if (chunk.type === 'console' && !chunk.format) {
        chunk.format = 'output';
    }
    return chunk;
}

function getChunkKey(chunk) {
    const role = chunk.role || '';
    const type = chunk.type || '';
    return `${role}:${type}`;
}

function getFormatKey(chunk) {
    if (!chunk) return '__default__';
    return chunk.format || chunk.recipient || '__default__';
}

function getFormatStore(baseKey) {
    if (!activeMessageIds.has(baseKey)) {
        activeMessageIds.set(baseKey, { map: new Map(), lastKey: null });
    }
    return activeMessageIds.get(baseKey);
}

function setActiveMessageId(chunk, messageId) {
    const baseKey = getChunkKey(chunk);
    const formatKey = getFormatKey(chunk);
    const store = getFormatStore(baseKey);
    store.map.set(formatKey, messageId);
    store.lastKey = formatKey;
}

function getActiveMessageId(chunk) {
    const baseKey = getChunkKey(chunk);
    const store = activeMessageIds.get(baseKey);
    if (!store) return null;
    const formatKey = getFormatKey(chunk);
    if (store.map.has(formatKey)) {
        return store.map.get(formatKey);
    }
    if (store.lastKey && store.map.has(store.lastKey)) {
        return store.map.get(store.lastKey);
    }
    const iterator = store.map.values().next();
    return iterator.value || null;
}

function getCodeMessageElement(codeId) {
    if (!codeId) return null;
    return chatDisplay.querySelector(`.message[data-id="${codeId}"]`);
}

function renderActiveLineSpinner() {
    if (!activeLineCodeId || !isActiveLineRunning) return;
    const messageElement = getCodeMessageElement(activeLineCodeId);
    if (!messageElement) return;
    const pre = messageElement.querySelector('pre');
    if (!pre) return;
    let spinner = pre.querySelector('.code-spinner');
    if (!spinner) {
        spinner = document.createElement('div');
        spinner.className = 'code-spinner';
        pre.appendChild(spinner);
    }
}

function removeActiveLineSpinner() {
    if (!activeLineCodeId) return;
    const messageElement = getCodeMessageElement(activeLineCodeId);
    if (!messageElement) return;
    const spinner = messageElement.querySelector('pre .code-spinner');
    if (spinner) {
        spinner.remove();
    }
}

function clearActiveMessageId(chunk) {
    const baseKey = getChunkKey(chunk);
    const store = activeMessageIds.get(baseKey);
    if (!store) return;
    const formatKey = getFormatKey(chunk);
    store.map.delete(formatKey);
    if (store.lastKey === formatKey) {
        const nextKey = store.map.keys().next();
        store.lastKey = nextKey.value || null;
    }
    if (store.map.size === 0) {
        activeMessageIds.delete(baseKey);
    }
}

function isShellCodeMessage(message) {
    if (!message || message.type !== 'code') return false;
    const format = (message.format || '').toLowerCase();
    return ['shell', 'bash', 'sh', 'zsh', 'powershell', 'pwsh', 'cmd'].includes(format);
}

function hasInterruptionNotice(codeId) {
    if (!codeId) return false;
    const outputs = getConsoleMessagesForCode(codeId);
    return outputs.some(msg => {
        const text = typeof msg?.content === 'string' ? msg.content : '';
        return /interrupt|interrupted|keyboardinterrupt|stopped before completion/i.test(text);
    });
}

function appendPrematureStopNotice(codeId, reason = 'Execution stopped before completion.') {
    if (!codeId || hasInterruptionNotice(codeId)) return;
    const messageId = generateId('msg');
    const noticeMessage = {
        id: messageId,
        role: 'computer',
        type: 'console',
        format: 'output',
        content: reason,
        associatedCodeId: codeId
    };
    messages.push(noticeMessage);
    appendMessage(noticeMessage);
    addConsoleMapping(codeId, messageId);
    refreshStdoutPanel(codeId, { autoScroll: true });
}

function shouldTrackCodeMessage(message) {
    return Boolean(
        message &&
        message.type === 'code' &&
        message.role !== 'user' &&
        message.format !== 'html'
    );
}

function isConsoleOutputMessage(message) {
    if (!message) return false;
    const type = message.type || message.message_type;
    const format = message.format || message.message_format;
    const recipient = (message.recipient || message.message_recipient || '').toLowerCase();
    const isConsoleType = type === 'console' && format !== 'active_line' && !isTelemetryConsoleMessage(message);
    const isStdStream = (type === 'message' || type === 'text') && STD_STREAM_RECIPIENTS.includes(recipient);
    return isConsoleType || isStdStream;
}

function isTelemetryConsoleMessage(message) {
    const type = message?.type || message?.message_type;
    if (type !== 'console') return false;
    if (message.format === 'active_line') return true;
    const content = typeof message.content === 'string' ? message.content.trim() : '';
    if (message.format === 'execution' && /^\d+(?:\/\d+)?$/.test(content)) {
        return true;
    }
    if (/^line\s+\d+$/i.test(content)) {
        return true;
    }
    return false;
}

function markCodeMessageForStdout(message) {
    if (!message) return;
    if (activeLineCodeId && activeLineCodeId !== message.id) {
        removeActiveLineSpinner();
    }
    lastExecutableCodeId = message.id;
    pendingConsoleParentId = message.id;
    activeLineCodeId = message.id;
    isActiveLineRunning = false;
    if (!codeConsoleMap.has(message.id)) {
        codeConsoleMap.set(message.id, []);
    }
    ensureStdoutElements(message.id);
}

function addConsoleMapping(codeId, consoleId) {
    if (!codeId || !consoleId) return;
    if (!codeConsoleMap.has(codeId)) {
        codeConsoleMap.set(codeId, []);
    }
    const entries = codeConsoleMap.get(codeId);
    if (!entries.includes(consoleId)) {
        entries.push(consoleId);
    }
    updateStdoutAvailability(codeId);
}

function registerConsoleMessage(message) {
    if (!isConsoleOutputMessage(message)) return;
    let codeId = message.associatedCodeId || pendingConsoleParentId || lastExecutableCodeId;
    if (!codeId) {
        codeId = findPreviousExecutableCodeId(message.id);
    }
    if (!codeId) return;
    message.associatedCodeId = codeId;
    addConsoleMapping(codeId, message.id);
    pendingConsoleParentId = codeId;
    lastExecutableCodeId = codeId;
    refreshStdoutPanel(codeId, { autoScroll: true });
}

function handleStdoutTrackingOnMessageStart(message) {
    if (!message || message.__stdoutHandled) return;
    if (shouldTrackCodeMessage(message)) {
        markCodeMessageForStdout(message);
    } else if (isConsoleOutputMessage(message)) {
        registerConsoleMessage(message);
    } else if (isTelemetryConsoleMessage(message)) {
        // ignore telemetry chunks
    } else if (message.role === 'user') {
        pendingConsoleParentId = null;
        lastExecutableCodeId = null;
    }
    message.__stdoutHandled = true;
}

function ensureStdoutElements(codeId) {
    const messageElement = chatDisplay.querySelector(`.message[data-id="${codeId}"]`);
    if (!messageElement) return {};
    const contentElement = messageElement.querySelector('.content');
    if (!contentElement) return {};

    let controls = messageElement.querySelector('.stdout-controls');
    let button = controls ? controls.querySelector('.stdout-button') : null;
    let panel = messageElement.querySelector('.stdout-panel');

    if (!controls) {
        controls = document.createElement('div');
        controls.className = 'stdout-controls stdout-hidden';
        button = document.createElement('button');
        button.type = 'button';
        button.className = 'stdout-button';
        button.textContent = 'Show Output';
        button.setAttribute('aria-expanded', 'false');
        button.disabled = true;
        button.addEventListener('click', () => toggleStdoutPanel(codeId));
        controls.appendChild(button);
        contentElement.appendChild(controls);
    }

    if (!panel) {
        panel = document.createElement('div');
        panel.className = 'stdout-panel';
        panel.setAttribute('role', 'region');
        panel.setAttribute('aria-label', 'STDOUT and STDERR output');
        panel.setAttribute('aria-hidden', 'true');
        contentElement.appendChild(panel);
    }

    return { messageElement, contentElement, controls, button, panel };
}

function updateStdoutAvailability(codeId) {
    const { controls, button, panel } = ensureStdoutElements(codeId);
    if (!controls || !button) {
        return;
    }
    const hasOutput = (codeConsoleMap.get(codeId) || []).length > 0;
    controls.classList.toggle('stdout-hidden', !hasOutput);
    button.disabled = !hasOutput;
    if (!hasOutput) {
        button.textContent = 'Show Output';
        button.setAttribute('aria-expanded', 'false');
        if (panel) {
            panel.classList.remove('open');
            panel.setAttribute('aria-hidden', 'true');
        }
    }
}

function getConsoleMessagesForCode(codeId) {
    const ids = codeConsoleMap.get(codeId) || [];
    return ids
        .map(id => messages.find(msg => msg.id === id))
        .filter(msg => Boolean(msg));
}

function findPreviousExecutableCodeId(referenceMessageId) {
    if (!referenceMessageId) return null;
    const index = messages.findIndex(msg => msg.id === referenceMessageId);
    if (index === -1) return null;
    for (let i = index - 1; i >= 0; i--) {
        const candidate = messages[i];
        if (shouldTrackCodeMessage(candidate)) {
            return candidate.id;
        }
    }
    return null;
}

function captureStdoutPanelState(codeId) {
    const messageElement = chatDisplay.querySelector(`.message[data-id="${codeId}"]`);
    if (!messageElement) return null;
    const panel = messageElement.querySelector('.stdout-panel');
    const button = messageElement.querySelector('.stdout-button');
    if (!panel || !button) return null;
    return {
        isOpen: panel.classList.contains('open')
    };
}

function restoreStdoutPanelState(codeId, state) {
    if (!state || !state.isOpen) return;
    const { panel, button } = ensureStdoutElements(codeId);
    if (!panel || !button || button.disabled) return;
    panel.classList.add('open');
    panel.setAttribute('aria-hidden', 'false');
    button.textContent = 'Hide Output';
    button.setAttribute('aria-expanded', 'true');
    renderStdoutPanel(codeId);
}

function renderStdoutPanel(codeId) {
    const { panel } = ensureStdoutElements(codeId);
    if (!panel) return;
    panel.innerHTML = '';
    const outputs = getConsoleMessagesForCode(codeId).filter(msg => {
        const text = typeof msg?.content === 'string' ? msg.content : '';
        return text.trim().length > 0;
    });
    outputs.forEach(msg => {
        const entry = document.createElement('div');
        entry.className = 'stdout-entry';
        const pre = document.createElement('pre');
        pre.classList.add('stdout-pre');
        const code = document.createElement('code');
        code.classList.add('stdout-code');
        code.textContent = msg.content || '';
        pre.appendChild(code);
        entry.appendChild(pre);
        panel.appendChild(entry);
    });
    if (outputs.length > 0) {
        addCopyButtons(panel);
    }
    if (outputs.length === 0) {
        const emptyState = document.createElement('div');
        emptyState.className = 'stdout-empty';
        emptyState.textContent = 'No console output captured.';
        panel.appendChild(emptyState);
    }
}

function autoScrollStdoutPanel(panel) {
    if (!panel) return;
    panel.scrollTop = panel.scrollHeight;
    panel.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

function toggleStdoutPanel(codeId) {
    const { button, panel } = ensureStdoutElements(codeId);
    if (!button || !panel || button.disabled) return;
    const isOpen = panel.classList.toggle('open');
    if (isOpen) {
        panel.setAttribute('aria-hidden', 'false');
        button.textContent = 'Hide Output';
        renderStdoutPanel(codeId);
        autoScrollStdoutPanel(panel);
    } else {
        panel.setAttribute('aria-hidden', 'true');
        button.textContent = 'Show Output';
    }
    button.setAttribute('aria-expanded', String(isOpen));
}

function refreshStdoutPanel(codeId, { autoScroll = false } = {}) {
    const { panel } = ensureStdoutElements(codeId);
    updateStdoutAvailability(codeId);
    if (!panel || !panel.classList.contains('open')) return;
    renderStdoutPanel(codeId);
    if (autoScroll) {
        autoScrollStdoutPanel(panel);
    }
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        normalizeStdStreamMessage,
        normalizeIncomingChunk,
        getChunkKey,
        getFormatKey,
        isShellCodeMessage,
        isTelemetryConsoleMessage,
        isConsoleOutputMessage,
        shouldTrackCodeMessage,
    };
}

// assistant.js — orchestrateur principal (state, sendRequest, processChunk, init)

// PREVENT DEFAULT BROWSER BEHAVIOR (drag and drop)
document.addEventListener('drop', (e) => e.preventDefault());

// Constants and State Management
const INITIAL_TEXTAREA_HEIGHT = '38px';
// MESSAGE_TYPES is imported from conversation_manager.js

// Global State
let messages = [];
let currentMessageIndex = 0;
let isGenerating = false;
let controller = null;
let promptIdeasVisible = false;
const activeMessageIds = new Map();
let workingIndicatorId = null;
let pendingUploads = [];
let lastExecutableCodeId = null;
let pendingConsoleParentId = null;
const codeConsoleMap = new Map();
let activeLineCodeId = null;
let isActiveLineRunning = false;
let stopRequested = false;
let stopRequestedCodeId = null;
let userProfilePromise = null;
let welcomeRenderPromise = null;
let welcomeRendered = false;

// Session mode for copepod agent (plan | analyse)
let sessionMode = 'plan';
const AGENT_TYPE = 'copepod';

// Conversation manager instance
let conversationManager;

// Authentication state
let currentUserFirstName = null;

// Authentication — delegates to auth.js
function checkAuthentication() { return Auth.checkAuthentication(); }
function redirectToLogin() { Auth.redirectToLogin(); }
function getAuthHeaders() { return Auth.getAuthHeaders(); }
function logout() { Auth.logout(); }

// Session Management — sessionId persists in localStorage so F5 preserves history and session mode
let sessionId = localStorage.getItem('sessionId') || (() => {
    const newId = generateId('session');
    localStorage.setItem('sessionId', newId);
    return newId;
})();
let threadId = localStorage.getItem('threadId') || (() => {
    const newThreadId = generateId('thread');
    localStorage.setItem('threadId', newThreadId);
    return newThreadId;
})();

function updateSessionIdentityBadge() {
    if (typeof window.updateSessionIdentityBadge === 'function') {
        window.updateSessionIdentityBadge(sessionId);
    }
}

// DOM Elements
const chatDisplay = document.getElementById('chatDisplay');
const sendButton = document.getElementById('sendButton');
const stopButton = document.getElementById('stopButton');
const newMessagesButton = document.getElementById('newMessagesButton');
const messageInput = document.getElementById('messageInput');
const progressBar = document.getElementById('uploadProgress');
const progressElement = progressBar ? progressBar.querySelector('.progress') : null;
const generationDurationValue = document.getElementById('generationDurationValue');
const generationStatusValue = document.getElementById('generationStatusValue');
const generationTokensValue = document.getElementById('generationTokensValue');
const generationCostValue = document.getElementById('generationCostValue');
const generationRateValue = document.getElementById('generationRateValue');

const MODEL_PRICING = {
    'openrouter/openai/gpt-5.4-mini': {
        inputPerMillion: 0.75,
        outputPerMillion: 4.50,
        label: 'GPT-5.4 mini',
    },
    'openai/gpt-5.4-mini': {
        inputPerMillion: 0.75,
        outputPerMillion: 4.50,
        label: 'GPT-5.4 mini',
    },
    'gpt-5.4-mini': {
        inputPerMillion: 0.75,
        outputPerMillion: 4.50,
        label: 'GPT-5.4 mini',
    },
};

let generationTimerStart = null;
let generationSummaryFinalized = false;
let activeGenerationModel = null;

showPromptIdeas();
updateSessionIdentityBadge();

function resetTextareaHeight() {
    const messageInput = document.getElementById('messageInput');
    messageInput.style.height = '38px'; // Reset to initial height
}

// Event listeners
sendButton.addEventListener('click', () => {
    if (messageInput.value.trim() === '' && pendingUploads.length === 0) return;
    sendRequest();
    hidePromptIdeas();
    resetTextareaHeight();
});

messageInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendButton.click();
    }
    // Automatically adjust height based on content
    // this.style.height = 'auto';
    // this.style.height = this.scrollHeight + 'px';
});

stopButton.addEventListener('click', () => {
    if (isGenerating && controller) {
        stopRequested = true;
        stopRequestedCodeId = activeLineCodeId || lastExecutableCodeId || pendingConsoleParentId;
        isGenerating = false;
        controller.abort();
        appendSystemMessage("Generation stopped by user.");
    }
});

newMessagesButton.addEventListener('click', () => {
    clearChatHistory();
    resetTextareaHeight();
    
    // Start a new conversation
    if (conversationManager) {
        conversationManager.startNewConversation();
    }
});

// Logout button event listeners (both desktop and mobile)
function handleLogout() {
    return async () => {
        try {
            await fetch(config.getEndpoints().logout, {
                method: 'POST',
                headers: {
                    ...getAuthHeaders()
                }
            });
        } catch (error) {
            console.error('Logout error:', error);
        } finally {
            logout();
        }
    };
}

const logoutButton = document.getElementById('logoutButton');
const logoutButtonMobile = document.getElementById('logoutButtonMobile');

if (logoutButton) {
    logoutButton.addEventListener('click', handleLogout());
}

if (logoutButtonMobile) {
    logoutButtonMobile.addEventListener('click', handleLogout());
}

// Error handling utility
function handleError(error, customMessage = 'An error occurred') {
    console.error(error);
    appendSystemMessage(`${customMessage}: ${error.message || 'Unknown error'}`);
}

// Safe DOM manipulation utility
function safeGetElement(id) {
    const element = document.getElementById(id);
    if (!element) {
        console.warn(`Element with id '${id}' not found`);
    }
    return element;
}

function getModelPricing(model) {
    if (!model) return null;
    return MODEL_PRICING[model] || MODEL_PRICING[model.split('/').pop()] || null;
}

function formatTokenCount(value) {
    if (!Number.isFinite(value)) {
        return null;
    }
    return new Intl.NumberFormat('fr-FR').format(Math.max(0, Math.round(value)));
}

function formatCurrency(amount) {
    if (!Number.isFinite(amount)) {
        return null;
    }
    if (amount === 0) {
        return '0,00 $';
    }
    const digits = amount >= 1 ? 2 : 4;
    return `${amount.toLocaleString('fr-FR', {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
    })} $`;
}

function formatDurationMs(ms) {
    if (!Number.isFinite(ms) || ms < 0) {
        return null;
    }
    if (ms < 1000) {
        return `${Math.max(0.1, ms / 1000).toFixed(1)} s`;
    }
    const seconds = ms / 1000;
    if (seconds < 60) {
        return `${seconds.toFixed(1)} s`;
    }
    const minutes = Math.floor(seconds / 60);
    const remaining = Math.round(seconds % 60);
    return `${minutes} min ${String(remaining).padStart(2, '0')} s`;
}

function extractUsageCount(usage, keys) {
    if (!usage || typeof usage !== 'object') return null;
    for (const key of keys) {
        const value = usage[key];
        if (Number.isFinite(value)) {
            return value;
        }
    }
    return null;
}

function estimateGenerationCost(usage, model) {
    const pricing = getModelPricing(model);
    if (!pricing || !usage || typeof usage !== 'object') {
        return null;
    }
    if (Number.isFinite(usage.cost)) {
        return usage.cost;
    }
    if (Number.isFinite(usage.cost_usd)) {
        return usage.cost_usd;
    }
    const promptTokens = extractUsageCount(usage, ['prompt_tokens', 'input_tokens']);
    const completionTokens = extractUsageCount(usage, ['completion_tokens', 'output_tokens']);
    if (!Number.isFinite(promptTokens) && !Number.isFinite(completionTokens)) {
        return null;
    }
    const inputCost = Number.isFinite(promptTokens) ? (promptTokens / 1_000_000) * pricing.inputPerMillion : 0;
    const outputCost = Number.isFinite(completionTokens) ? (completionTokens / 1_000_000) * pricing.outputPerMillion : 0;
    return inputCost + outputCost;
}

function updateGenerationMetrics({
    elapsedMs = null,
    usage = null,
    model = null,
    finalized = false,
} = {}) {
    const resolvedModel = model || activeGenerationModel;
    if (resolvedModel) {
        activeGenerationModel = resolvedModel;
    }

    const durationText = formatDurationMs(elapsedMs);
    if (generationDurationValue && durationText) {
        generationDurationValue.textContent = durationText;
    }
    if (generationStatusValue) {
        generationStatusValue.textContent = finalized ? 'Dernière génération' : 'Génération en cours…';
    }

    const promptTokens = extractUsageCount(usage, ['prompt_tokens', 'input_tokens']);
    const completionTokens = extractUsageCount(usage, ['completion_tokens', 'output_tokens']);
    const totalTokens = extractUsageCount(usage, ['total_tokens']);
    if (generationTokensValue) {
        if (Number.isFinite(promptTokens) || Number.isFinite(completionTokens) || Number.isFinite(totalTokens)) {
            const promptLabel = formatTokenCount(promptTokens);
            const completionLabel = formatTokenCount(completionTokens);
            const totalLabel = formatTokenCount(totalTokens);
            const segments = [];
            if (promptLabel !== null) segments.push(`${promptLabel} in`);
            if (completionLabel !== null) segments.push(`${completionLabel} out`);
            if (totalLabel !== null) segments.push(`${totalLabel} total`);
            generationTokensValue.textContent = segments.join(' · ');
        } else if (finalized) {
            generationTokensValue.textContent = '—';
        }
    }

    const cost = estimateGenerationCost(usage, resolvedModel);
    if (generationCostValue) {
        if (Number.isFinite(cost)) {
            generationCostValue.textContent = formatCurrency(cost) || '—';
        } else if (finalized) {
            generationCostValue.textContent = '—';
        } else {
            generationCostValue.textContent = 'Calcul en cours…';
        }
    }

    if (generationRateValue) {
        const pricing = getModelPricing(resolvedModel);
        if (pricing) {
            generationRateValue.textContent = `Tarif ${pricing.label}: ${pricing.inputPerMillion.toFixed(2)} $/M entrée · ${pricing.outputPerMillion.toFixed(2)} $/M sortie`;
        } else if (resolvedModel) {
            generationRateValue.textContent = `Tarif du modèle: ${resolvedModel}`;
        } else {
            generationRateValue.textContent = 'Tarif du modèle: —';
        }
    }

    if (finalized) {
        generationSummaryFinalized = true;
        generationTimerStart = null;
    }
}

function startGenerationMetrics(model = null) {
    activeGenerationModel = model || activeGenerationModel;
    generationTimerStart = performance.now();
    generationSummaryFinalized = false;
    if (generationDurationValue) generationDurationValue.textContent = '—';
    if (generationStatusValue) generationStatusValue.textContent = 'Génération en cours…';
    if (generationTokensValue) generationTokensValue.textContent = '—';
    if (generationCostValue) generationCostValue.textContent = 'Calcul en cours…';
    if (generationRateValue) {
        const pricing = getModelPricing(activeGenerationModel);
        generationRateValue.textContent = pricing
            ? `Tarif ${pricing.label}: ${pricing.inputPerMillion.toFixed(2)} $/M entrée · ${pricing.outputPerMillion.toFixed(2)} $/M sortie`
            : 'Tarif du modèle: —';
    }
}

function finalizeGenerationMetrics(payload = {}) {
    const elapsedMs = Number.isFinite(payload.elapsedMs)
        ? payload.elapsedMs
        : Number.isFinite(generationTimerStart)
            ? performance.now() - generationTimerStart
            : null;
    updateGenerationMetrics({
        elapsedMs,
        usage: payload.usage || null,
        model: payload.model || null,
        finalized: true,
    });
}

function resetGenerationMetricsView() {
    generationTimerStart = null;
    generationSummaryFinalized = false;
    activeGenerationModel = null;
    if (generationDurationValue) generationDurationValue.textContent = '—';
    if (generationStatusValue) generationStatusValue.textContent = 'En attente d’une génération';
    if (generationTokensValue) generationTokensValue.textContent = '—';
    if (generationCostValue) generationCostValue.textContent = '—';
    if (generationRateValue) generationRateValue.textContent = 'Tarif du modèle: —';
}

function getMessageById(messageId) {
    return messages.find(msg => msg.id === messageId) || null;
}

function serializeMessagesForRequest(messageList = []) {
    return messageList.map(msg => {
        const { llmContent, attachments, userText, storageContent, ...rest } = msg;
        const serialized = { ...rest };
        if (llmContent) {
            serialized.content = llmContent;
        }
        return serialized;
    });
}

// Modify sendRequest to use better error handling
async function sendRequest(msgOverride=null) {
    const attachmentsToSend = pendingUploads.map(att => ({ ...att }));
    const rawInput = msgOverride !== null ? msgOverride : messageInput.value;
    const trimmedInput = rawInput ? rawInput.trim() : '';
    if (!trimmedInput && attachmentsToSend.length === 0) return;

    const attachmentSummaries = attachmentsToSend.map(att => ({
        name: att.name,
        path: att.path,
        size: att.size,
        mimeType: att.mimeType
    }));

    const llmInstruction = buildAttachmentInstruction(attachmentsToSend);
    const llmContentParts = [];
    if (trimmedInput) {
        llmContentParts.push(trimmedInput);
    }
    if (llmInstruction) {
        llmContentParts.push(llmInstruction);
    }
    const llmContent = llmContentParts.join('\n\n');

    const displaySegments = [];
    if (trimmedInput) {
        displaySegments.push(trimmedInput);
    }
    if (attachmentSummaries.length) {
        const attachmentLabel = formatAttachmentLabel(attachmentSummaries.length);
        const fileNames = attachmentSummaries.map(att => att.name).join(', ');
        displaySegments.push(`**${attachmentLabel}:** ${fileNames}`);
    }
    const displayContent = displaySegments.join('\n\n');

    try {
        // Input validation

        sendButton.disabled = true;
        sendButton.classList.add('is-generating');
        stopButton.disabled = false;

        const userMessage = {
            id: generateId('msg'),
            role: 'user',
            type: 'message',
            content: displayContent || trimmedInput,
            userText: trimmedInput,
            attachments: attachmentSummaries,
            llmContent: llmContent || trimmedInput
        };
        messages.push(userMessage);
        appendMessage(userMessage);
        scrollToBottom();
        messageInput.value = '';
        pendingUploads = [];
        renderPendingUploads();

        showWorkingIndicator();
        startGenerationMetrics(activeGenerationModel);

        // Define parameters for the POST request
        const params = {
            messages: serializeMessagesForRequest(messages)
        };

        // Initialize AbortController to handle cancellation
        controller = new AbortController();
        const { signal } = controller;

        // Send the POST request to the Python server endpoint with session ID header
        const interpreterCall = await fetch(config.getEndpoints().chat, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Session-Id": sessionId,
                "X-Agent-Type": AGENT_TYPE,
                ...getAuthHeaders()
            },
            body: JSON.stringify(params),
            signal,
        });

        // Throw an error if the request was not successful
        if (!interpreterCall.ok) {
            console.error("Interpreter didn't respond with 200 OK");
            if (interpreterCall.statusText) {
                appendSystemMessage(interpreterCall.statusText);
            } else {
                appendSystemMessage("Error: Unable to communicate with the server.");
            }
            resetButtons();
            return;
        }

        // Initialize a reader for the response body
        const reader = interpreterCall.body.getReader();
        const decoder = new TextDecoder("utf-8");

        isGenerating = true;

        let partialData = ''; // Buffer for partial data

        resetExecBlockState();

        while (isGenerating) {
            const { value, done } = await reader.read();

            if (done) {
                flushPendingAssistantMessages();
                break;
            }

            const text = decoder.decode(value, { stream: true });
            partialData += text;

            // Split the received text by newlines
            const lines = partialData.split("\n");

            // Keep the last line (it might be incomplete)
            partialData = lines.pop();

            for (const line of lines) {
                if (line.startsWith("data: ")) {
                    // console.log("Received line:", line);
                    const data = line.replace("data: ", "").trim();
                    // console.log("Received data:", data);
                    try {
                        const chunk = JSON.parse(data);
                        await processChunk(chunk);
                    } catch (e) {
                        console.error("Failed to parse chunk:", e);
                    }
                }
            }
        }

        resetButtons();
    } catch (error) {
        if (error.name === 'AbortError') {
            console.log("Request was aborted");
        } else {
            handleError(error, 'Failed to send request');
        }
    } finally {
        resetButtons();
    }
}

// Function to reset send and stop buttons
function resetButtons() {
    removeWorkingIndicator();
    sendButton.disabled = false;
    sendButton.classList.remove('is-generating');
    stopButton.disabled = true;
    controller = null;
    isGenerating = false;
    if (stopRequested || isActiveLineRunning) {
        const codeId = stopRequestedCodeId || activeLineCodeId || lastExecutableCodeId || pendingConsoleParentId;
        if (codeId && !hasInterruptionNotice(codeId)) {
            const codeMessage = getMessageById(codeId);
            if (isShellCodeMessage(codeMessage) || stopRequested || isActiveLineRunning) {
                appendPrematureStopNotice(codeId);
            }
        }
    }
    stopRequested = false;
    stopRequestedCodeId = null;
    isActiveLineRunning = false;
    removeActiveLineSpinner();
    activeLineCodeId = null;
    if (!generationSummaryFinalized && generationTimerStart !== null) {
        finalizeGenerationMetrics();
    }
}

function shouldStartNewBase64Image(message, chunk) {
    if (!message || message.type !== 'image') return false;
    const hasExistingContent = typeof message.content === 'string' && message.content.length > 0;
    if (!hasExistingContent) return false;

    const formatHint = chunk.format || message.format || '';
    if (!formatHint.startsWith('base64.')) return false;
    if (chunk.start) return false;

    const chunkContent = (chunk.content || '').trimStart();
    if (!chunkContent) return false;

    const pngHeader = 'iVBORw0KGgo';
    const jpegHeader = '/9j/';
    return chunkContent.startsWith(pngHeader) || chunkContent.startsWith(jpegHeader);
}

function saveCompletedAssistantMessage(message) {
    if (!conversationManager || !(message.role === 'assistant' || message.role === 'computer')) {
        return;
    }
    // Drop raw OI code-block messages (both to=execute and {"language":} formats)
    if (message.role === 'assistant' && message.type === 'message' &&
        typeof message.content === 'string') {
        const c = message.content.trimStart();
        if ((c.includes('to=execute') && c.includes('code=')) || c.startsWith('{"language":')) {
            return;
        }
    }
    if (message.type === 'console') {
        if (message.format === 'active_line') {
            return;
        }
        const text = typeof message.content === 'string' ? message.content.trim() : '';
        if (!text) {
            return;
        }
        message.format = message.format || 'output';
    }
    // Do not persist transient tool-status lines
    if (message.format === 'tool_status') {
        return;
    }
    const validTypes = ['message', 'code', 'image', 'console', 'file', 'confirmation'];
    const messageType = validTypes.includes(message.type) ? message.type : 'message';

    const frontendId = message.id;
    conversationManager.addMessage(
        message.role,
        message.content,
        messageType,
        message.format,
        message.recipient
    ).then(saved => {
        // Reconcile the DOM element's data-id to the stable backend UUID
        if (frontendId && saved && saved.id && frontendId !== saved.id) {
            const el = document.querySelector(`[data-id="${frontendId}"]`);
            if (el) el.setAttribute('data-id', saved.id);
            message.id = saved.id;
        }
    }).catch(() => {
        // Persistence error is handled by ConversationManager's retry queue
    });
}

function createImageMessageFromChunk(chunk, fallbackMessage) {
    return {
        id: generateId('msg'),
        role: chunk.role || (fallbackMessage && fallbackMessage.role) || 'assistant',
        type: chunk.type || (fallbackMessage && fallbackMessage.type) || 'image',
        content: '',
        format: chunk.format || (fallbackMessage && fallbackMessage.format) || undefined,
        recipient: chunk.recipient || (fallbackMessage && fallbackMessage.recipient) || undefined,
        created_at: new Date().toISOString(),
        isComplete: false,
    };
}

// Function to process each chunk of the stream and create messages
function processChunk(chunk) {
    // Drop raw LLM tool_call chunks that leaked through without execution
    if (chunk && chunk.tool_calls && !chunk.type) return Promise.resolve();
    if (
        chunk &&
        typeof chunk === 'object' &&
        (chunk.type === 'generation_summary' ||
            (chunk.usage && !chunk.content && !chunk.start && !chunk.end))
    ) {
        finalizeGenerationMetrics({
            elapsedMs: Number.isFinite(chunk.elapsed_ms) ? chunk.elapsed_ms : chunk.elapsedMs,
            usage: chunk.usage || null,
            model: chunk.model || null,
        });
        return Promise.resolve();
    }
    // Drop raw OI code-block text chunks (both to=execute and {"language":} formats)
    if (chunk && chunk.role === 'assistant' && chunk.type === 'message') {
        const c = (chunk.content || '').trimStart();
        if ((c.includes('to=execute') && c.includes('code=')) || c.startsWith('{"language":')) {
            return Promise.resolve();
        }
    }
    chunk = normalizeIncomingChunk(chunk);
    return new Promise((resolve) => {
        removeWorkingIndicator();
        if (chunk.type === 'console' && chunk.format === 'active_line') {
            handleActiveLineChunk(chunk.content);
            resolve();
            return;
        }

        if (chunk.type === 'action_button' && chunk.action === 'validate_plan') {
            handleActionButtonChunk(chunk);
            resolve();
            return;
        }

        if (chunk.type === 'strip_tail' && chunk.text) {
            const lastMsg = messages[messages.length - 1];
            if (lastMsg && typeof lastMsg.content === 'string' && lastMsg.content.includes(chunk.text)) {
                lastMsg.content = lastMsg.content.replace(chunk.text, '').trimEnd();
                updateMessageContent(lastMsg.id, lastMsg.content);
            }
            resolve();
            return;
        }

        let message = null;

        if (chunk.start) {
            const newMessage = normalizeStdStreamMessage({
                id: generateId('msg'),
                role: chunk.role,
                type: chunk.type,
                content: chunk.content || '',
                format: chunk.format || undefined,
                recipient: chunk.recipient || undefined,
                created_at: new Date().toISOString(),
                isComplete: false,
            });
            messages.push(newMessage);
            appendMessage(newMessage);
            setActiveMessageId(chunk, newMessage.id);
            if (chunk.type === 'code') {
                lastExecutableCodeId = newMessage.id;
            }
            message = newMessage;
        } else if (chunk.error) {
            const errorMessage = chunk.error.message || chunk.error;
            appendSystemMessage(errorMessage);
            return;
        }

        if (!message) {
            const targetId = getActiveMessageId(chunk);
            if (targetId) {
                message = messages.find(msg => msg.id === targetId);
            }
        }

        if (message) {
            if (shouldStartNewBase64Image(message, chunk)) {
                message.isComplete = true;
                updateMessageContent(message.id, message.content);
                saveCompletedAssistantMessage(message);

                const newMessage = createImageMessageFromChunk(chunk, message);
                messages.push(newMessage);
                appendMessage(newMessage);
                setActiveMessageId(chunk, newMessage.id);
                message = newMessage;
            }

            message.format = chunk.format || message.format || undefined;
            message.recipient = chunk.recipient || message.recipient || undefined;
            // Only append for non-start chunks: start chunk content is already set in newMessage
            if (!chunk.start) {
                message.content += chunk.content || '';
            }

            if (chunk.end) {
                chunk.format = chunk.format || message.format || chunk.recipient || 'output';
                message.isComplete = true;
                clearActiveMessageId(chunk);
                if (shouldTriggerInspectionIndicator(chunk, message) &&
                    typeof showInspectionIndicator === 'function') {
                    showInspectionIndicator('Inspection des fichiers en cours…');
                }
                // Remove empty assistant message bubbles (OI emits these before every code block)
                if (message.type === 'message' && !(message.content || '').trim()) {
                    const el = chatDisplay.querySelector(`.message[data-id="${message.id}"]`);
                    if (el) el.remove();
                    const idx = messages.findIndex(m => m.id === message.id);
                    if (idx !== -1) messages.splice(idx, 1);
                    resolve();
                    return;
                }
                // Save AFTER content is fully assembled
                saveCompletedAssistantMessage(message);
            }

            updateMessageContent(message.id, message.content);
        }

        resolve();
    });
}


// ── Session mode (plan ↔ analyse) ────────────────────────────────────────────

function handleActionButtonChunk(chunk, { persist = true } = {}) {
    const label = chunk.label || 'Passer en Mode Analyse';

    const wrapper = document.createElement('div');
    wrapper.className = 'action-button-chunk';

    const btn = document.createElement('button');
    btn.className = 'action-btn-valider';
    btn.textContent = label;
    btn.addEventListener('click', async () => {
        btn.disabled = true;
        const switched = await switchToAnalyseMode();
        if (!switched) {
            btn.disabled = false;
        }
    });

    wrapper.appendChild(btn);
    chatDisplay.appendChild(wrapper);
    chatDisplay.scrollTop = chatDisplay.scrollHeight;

    if (persist && conversationManager) {
        conversationManager.addMessage(
            'computer',
            JSON.stringify({ action: chunk.action || 'validate_plan', label }),
            'action_button',
            null,
            null
        ).catch(err => console.error('Failed to save action_button:', err));
    }
}

async function switchToAnalyseMode() {
    try {
        const endpoint = config.getEndpoints().sessionMode;
        const resp = await fetch(endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Session-Id': sessionId,
                'X-Agent-Type': AGENT_TYPE,
                ...getAuthHeaders(),
            },
            body: JSON.stringify({ mode: 'analyse' }),
        });
        if (!resp.ok) {
            const errorData = await resp.json().catch(() => ({}));
            if (resp.status === 409) {
                throw new Error(errorData.detail || 'Le contexte validé est incomplet pour passer en Mode Analyse.');
            }
            throw new Error(errorData.detail || `HTTP ${resp.status}`);
        }
        sessionMode = 'analyse';
        updateSessionModeBadge('analyse');
        appendSessionModeBandeau();
        return true;
    } catch (err) {
        console.error('Failed to switch to Analyse mode:', err);
        appendSystemMessage(`Erreur : impossible de passer en Mode Analyse. ${err.message}`);
        return false;
    }
}

function updateSessionModeBadge(mode) {
    const badge = document.getElementById('sessionModeBadge');
    const label = document.getElementById('sessionModeLabel');
    const icon = badge ? badge.querySelector('.session-mode-icon') : null;
    if (!badge || !label) return;

    badge.style.display = 'flex';
    if (mode === 'analyse') {
        badge.classList.remove('session-mode-plan');
        badge.classList.add('session-mode-analyse');
        label.textContent = 'Mode Analyse';
        if (icon) icon.textContent = 'analytics';
        chatDisplay.classList.add('mode-analyse');
    } else {
        badge.classList.remove('session-mode-analyse');
        badge.classList.add('session-mode-plan');
        label.textContent = 'Mode Plan';
        if (icon) icon.textContent = 'edit_note';
        chatDisplay.classList.remove('mode-analyse');
    }
}

function appendSessionModeBandeau() {
    const bandeau = document.createElement('div');
    bandeau.className = 'session-mode-bandeau';
    bandeau.textContent = '──── Mode Analyse activé ────';
    chatDisplay.appendChild(bandeau);
    chatDisplay.scrollTop = chatDisplay.scrollHeight;
}

async function initSessionMode() {
    try {
        const endpoint = config.getEndpoints().sessionMode;
        const resp = await fetch(endpoint, {
            headers: {
                'X-Session-Id': sessionId,
                'X-Agent-Type': AGENT_TYPE,
                ...getAuthHeaders(),
            },
        });
        if (!resp.ok) return;
        const data = await resp.json();
        sessionMode = data.mode || 'plan';
        updateSessionModeBadge(sessionMode);
    } catch (err) {
        console.warn('Could not fetch session mode:', err);
    }
}

// Function to append confirmation chunks
function appendConfirmationChunk(chunk) {
    // Example: Show a prompt to the user to confirm code execution
    if (chunk.type === 'confirmation' && chunk.content) {
        const confirmation = chunk.content;
        const userConfirmed = confirm(`Execution Confirmation:\n\nType: ${confirmation.type}\nFormat: ${confirmation.format}\nContent:\n${confirmation.content}\n\nDo you want to proceed?`);

        if (userConfirmed) {
            // User confirmed, proceed with execution
            appendSystemMessage("Code execution confirmed.");
            // Optionally, send a confirmation back to the server if required
        } else {
            // User canceled, abort the generation
            isGenerating = false;
            if (controller) {
                controller.abort();
            }
            appendSystemMessage("Code execution canceled by user.");
        }
    }
}

// Function to clear chat history
async function clearChatHistory() {
    try {
        removeWorkingIndicator();
        // Clear chat history
        const response = await fetch(config.getEndpoints().clear, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Session-Id": sessionId,
                ...getAuthHeaders()
            },
        });

        if (!response.ok) {
            throw new Error("Failed to clear chat history");
        }

        // Clear uploaded files
        const fileResponse = await fetch(config.getEndpoints().files, {
            method: "DELETE",
            headers: {
                "X-Session-Id": sessionId,
                ...getAuthHeaders()
            },
        });

        if (!fileResponse.ok) {
            throw new Error("Failed to clear uploaded files");
        }

        // Rotate sessionId so the new session is fully isolated
        sessionId = generateId('session');
        localStorage.setItem('sessionId', sessionId);
        localStorage.removeItem('activeConversationId');
        updateSessionIdentityBadge();

        // Reset session mode to plan
        sessionMode = 'plan';
        updateSessionModeBadge('plan');

        // Clear frontend messages array
        messages = [];
        // Clear chat display
        isGenerating = false;
        controller = null;
        chatDisplay.innerHTML = '';
        promptIdeasVisible = false;
        resetStdoutState();

        // Clear uploaded files list in UI
        pendingUploads = [];
        renderPendingUploads();
        resetGenerationMetricsView();

        showPromptIdeas();
        resetTextareaHeight();

    } catch (error) {
        console.error("An error occurred while clearing history:", error);
        appendSystemMessage("Error: Unable to clear history completely.");
    }
}

function resetSessionForConversationLoad() {
    sessionId = generateId('session');
    localStorage.setItem('sessionId', sessionId);
    sessionMode = 'plan';
    updateSessionModeBadge('plan');
    updateSessionIdentityBadge();
}
window.resetSessionForConversationLoad = resetSessionForConversationLoad;

// Fetch and display chat history on load
window.addEventListener('DOMContentLoaded', async () => {
    // Check authentication before doing anything else
    const isAuthenticated = await checkAuthentication();
    if (!isAuthenticated) {
        return; // Will redirect to login
    }

    if (!micStream) await warmUpMicrophone(); // Ensure microphone is warmed up (sppeds up first use)

    // Initialize conversation manager
    resetStdoutState();
    conversationManager = new ConversationManager();
    window.dispatchEvent(new CustomEvent('app:ready'));

    // Show a non-blocking warning when messages fail to persist, recover silently on retry
    conversationManager.addEventListener('persistence_error', ({ queued }) => {
        if (queued === 1) showNotification('Connexion lente — sauvegarde en cours…', 'warning');
    });
    conversationManager.addEventListener('persistence_recovered', () => {
        showNotification('Messages sauvegardés', 'success');
    });
    conversationManager.addEventListener('persistence_failed', ({ count }) => {
        showNotification(
            `${count} message(s) n'ont pas pu être sauvegardés — rechargez pour vérifier`,
            'error'
        );
    });

    loadCurrentUserProfile();
    await initSessionMode();

    const activeConversationId = localStorage.getItem('activeConversationId');
    if (activeConversationId) {
        try {
            const response = await fetch(`${window.API_BASE_URL}/conversations/${activeConversationId}`, {
                headers: { 'Content-Type': 'application/json', ...getAuthHeaders() }
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const conversation = await response.json();
            const msgs = conversation.messages || [];
            // Sync manager so new messages append to THIS conversation, not a fresh one
            if (conversationManager) {
                conversationManager.currentConversationId = activeConversationId;
                conversationManager.currentMessages = msgs;
            }
            if (msgs.length > 0) {
                hydrateChatWithMessages(msgs, { persist: false });
                // Reset the backend interpreter to this conversation's context
                // so new messages don't run in a stale Redis session
                try {
                    await window.loadConversationIntoInterpreter(msgs);
                } catch (_) { /* non-blocking — interpreter context is best-effort */ }
            } else {
                showPromptIdeas();
            }
        } catch (error) {
            // Conversation no longer exists (deleted from another tab, or stale localStorage)
            console.warn('Stale activeConversationId, clearing:', error);
            localStorage.removeItem('activeConversationId');
            showPromptIdeas();
        }
    } else {
        showPromptIdeas();
    }
});

// This function sets all links to open in a new tab
function setLinksToNewTab() {
    document.querySelectorAll('a').forEach(link => {
      link.setAttribute('target', '_blank');
    });
  }
  
  // Call this function initially to set existing links
  setLinksToNewTab();
  
  // For dynamically created links, use a MutationObserver
  const observer = new MutationObserver(() => {
    setLinksToNewTab();
  });
  
  // Observe changes in the document body to catch dynamically added links
  observer.observe(document.body, { childList: true, subtree: true });


  window.onload = async function() {
    const urlParams = new URLSearchParams(window.location.search);
    const prompt = urlParams.get('prompt');
    
    if (prompt) {
        // Wait for select2 to be initialized
        await waitForSelect2();
        
        const inputField = document.getElementById('messageInput');
        if (inputField) {
            inputField.value = prompt;
            sendButton.click();
        }
    }
};

async function waitForSelect2(timeout = 5000) {
    return new Promise((resolve, reject) => {
        const startTime = Date.now();
        
        const checkSelect2 = () => {
            const select2Value = $('#myselect2').val();
            if (select2Value) {
                resolve();
            } else if (Date.now() - startTime > timeout) {
                reject(new Error('Timeout waiting for select2'));
            } else {
                setTimeout(checkSelect2, 100);
            }
        };
        
        checkSelect2();
    });
}

// Mobile navigation functionality
function initializeMobileNavigation() {
    const navbarToggle = document.getElementById('navbarToggle');
    const navbarMobileMenu = document.getElementById('navbarMobileMenu');
    const mobileOverlay = document.getElementById('mobileOverlay');
    
    // Mobile menu buttons
    const downloadButtonMobile = document.getElementById('downloadButtonMobile');
    const newMessagesButtonMobile = document.getElementById('newMessagesButtonMobile');

    function toggleMobileMenu() {
        navbarToggle.classList.toggle('active');
        navbarMobileMenu.classList.toggle('active');
        mobileOverlay.classList.toggle('active');
        
        // Prevent body scroll when menu is open
        if (navbarMobileMenu.classList.contains('active')) {
            document.body.style.overflow = 'hidden';
        } else {
            document.body.style.overflow = '';
        }
    }

    function closeMobileMenu() {
        if (navbarToggle) navbarToggle.classList.remove('active');
        if (navbarMobileMenu) navbarMobileMenu.classList.remove('active');
        if (mobileOverlay) mobileOverlay.classList.remove('active');
        document.body.style.overflow = '';
    }

    // Toggle menu on hamburger click
    if (navbarToggle) {
        navbarToggle.addEventListener('click', toggleMobileMenu);
    }

    // Close menu on overlay click
    if (mobileOverlay) {
        mobileOverlay.addEventListener('click', closeMobileMenu);
    }

    // Handle mobile button clicks
    if (downloadButtonMobile) {
        downloadButtonMobile.addEventListener('click', () => {
            downloadConversation();
            closeMobileMenu();
        });
    }

    if (newMessagesButtonMobile) {
        newMessagesButtonMobile.addEventListener('click', () => {
            clearChatHistory();
            resetTextareaHeight();
            closeMobileMenu();
            
            // Start a new conversation
            if (conversationManager) {
                conversationManager.startNewConversation();
            }
        });
    }

    // Close menu on window resize if it gets too wide
    window.addEventListener('resize', () => {
        if (window.innerWidth > 768) {
            closeMobileMenu();
        }
    });

    // Close menu on escape key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && navbarMobileMenu?.classList.contains('active')) {
            closeMobileMenu();
        }
    });
}

async function downloadConversation() {
    try {
        // Create a complete, self-contained HTML document
        const htmlContent = await createSelfContainedHTML();
        
        // Create blob and download
        const blob = new Blob([htmlContent], { type: 'text/html;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        
        const a = document.createElement('a');
        a.href = url;
        a.download = `IDEA-conversation-${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.html`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        appendSystemMessage("Conversation downloaded");
    } catch (err) {
        console.error("Download failed:", err);
        appendSystemMessage("Failed to download conversation. Please try again.");
    }
}

function shouldIncludeMessageInExport(message) {
    if (!message) return false;
    const msgType = message.type || message.message_type;
    if (msgType === 'console') {
        if (isTelemetryConsoleMessage(message)) {
            return false;
        }
        const text = typeof message.content === 'string' ? message.content.trim() : '';
        return text.length > 0;
    }
    return true;
}

function renderMessageContentForExport(message) {
    const msgType = message.type || message.message_type || 'message';
    const format = message.format || message.message_format || '';
    if (msgType === 'message') {
        const baseSource = message.content || message.userText || '';
        const { text: shielded, store } = protectMath(baseSource);
        let rendered;
        if (!hasBalancedMath(baseSource)) {
            rendered = `<pre>${escapeHtml(baseSource)}</pre>`;
        } else {
            const parsedMarkdown = marked ? marked.parse(shielded) : shielded;
            rendered = restoreMath(parsedMarkdown, store);
        }
        if (Array.isArray(message.attachments) && message.attachments.length > 0) {
            const alreadyPresent = /<strong>(?:file|files):<\/strong>/i.test(rendered);
            const attachmentList = message.attachments
                .map(att => escapeHtml(att.name))
                .join(', ');
            const label = formatAttachmentLabel(message.attachments.length);
            const prefix = alreadyPresent ? '' : `<p><strong>${label}:</strong> ${attachmentList}</p>`;
            return `${prefix}${rendered}`;
        }
        return rendered;
    }
    if (msgType === 'image') {
        if (format === 'base64.png') {
            return `<img src="data:image/png;base64,${message.content}" alt="Image">`;
        }
        return `<img src="${message.content}" alt="Image">`;
    }
    if (msgType === 'code') {
        if (format === 'html') {
            return message.content || '';
        }
        return `<pre><code class="language-${format || ''}">${escapeHtml(message.content || '')}</code></pre>`;
    }
    if (msgType === 'console') {
        return `<pre>${escapeHtml(message.content || '')}</pre>`;
    }
    if (msgType === 'file') {
        return `<a href="${message.content}" download>Download File</a>`;
    }
    return message.content || '';
}

function isExportCodeMessage(message) {
    if (!message) return false;
    const msgType = message.type || message.message_type;
    const format = message.format || message.message_format;
    return msgType === 'code' && format !== 'html' && message.role !== 'user';
}

function isExportConsoleOutput(message) {
    if (!message) return false;
    const msgType = message.type || message.message_type;
    const format = message.format || message.message_format;
    return msgType === 'console' && format !== 'active_line' && !isTelemetryConsoleMessage(message);
}

function buildStdoutAssociationsForExport(messageElements) {
    const elementIds = new Set(
        messageElements.map(element => element.getAttribute('data-id')).filter(Boolean)
    );

    const fromRuntimeState = new Map();
    if (codeConsoleMap && codeConsoleMap.size > 0) {
        codeConsoleMap.forEach((consoleIds = [], codeId) => {
            if (!elementIds.has(codeId)) {
                return;
            }
            const outputs = consoleIds
                .map(id => getMessageDataForExport(id))
                .filter(msg => msg && isExportConsoleOutput(msg))
                .map(msg => ({
                    id: msg.id,
                    content: msg.content || ''
                }));
            if (outputs.length > 0) {
                fromRuntimeState.set(codeId, outputs);
            }
        });
    }

    if (fromRuntimeState.size > 0) {
        return fromRuntimeState;
    }

    const fallbackMap = new Map();
    let lastCodeId = null;
    messageElements.forEach(element => {
        const messageId = element.getAttribute('data-id');
        const messageData = getMessageDataForExport(messageId);
        if (!messageData) {
            return;
        }
        if (isExportCodeMessage(messageData)) {
            lastCodeId = messageId;
        } else if (isExportConsoleOutput(messageData)) {
            if (lastCodeId) {
                if (!fallbackMap.has(lastCodeId)) {
                    fallbackMap.set(lastCodeId, []);
                }
                fallbackMap.get(lastCodeId).push({
                    id: messageId,
                    content: messageData.content || ''
                });
            }
        } else if ((messageData.type || messageData.message_type) !== 'console') {
            lastCodeId = null;
        }
    });
    return fallbackMap;
}

function attachStdoutControlsForExport(contentElement, codeId, outputs) {
    if (!contentElement || !outputs || outputs.length === 0) return;
    const controls = document.createElement('div');
    controls.className = 'stdout-controls';
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'stdout-button';
    button.textContent = 'Show Output';
    button.setAttribute('data-stdout-target', codeId);
    button.setAttribute('aria-expanded', 'false');
    controls.appendChild(button);
    contentElement.appendChild(controls);

    const panel = document.createElement('div');
    panel.className = 'stdout-panel';
    panel.setAttribute('data-stdout-target', codeId);
    panel.setAttribute('aria-hidden', 'true');
    panel.innerHTML = outputs.map(item => `
        <div class="stdout-entry">
            <pre class="stdout-pre"><code class="stdout-code">${escapeHtml(item.content || '')}</code></pre>
        </div>
    `).join('');
    contentElement.appendChild(panel);
}

function getMessageDataForExport(messageId) {
    if (!messageId) return null;
    
    if (Array.isArray(messages)) {
        const inSession = messages.find(msg => msg.id === messageId);
        if (inSession) {
            return inSession;
        }
    }
    
    if (conversationManager && Array.isArray(conversationManager.currentMessages)) {
        const fromConversation = conversationManager.currentMessages.find(msg => msg.id === messageId);
        if (fromConversation) {
            return fromConversation;
        }
    }
    
    return null;
}

function prepareChatCloneForExport() {
    const chatClone = chatDisplay.cloneNode(true);
    const messageElements = Array.from(chatClone.querySelectorAll('.message'));
    const stdoutAssociations = buildStdoutAssociationsForExport(messageElements);
    
    messageElements.forEach(element => {
        const messageId = element.getAttribute('data-id');
        const messageData = getMessageDataForExport(messageId);
        if (!messageData) {
            return;
        }
        
        if (!shouldIncludeMessageInExport(messageData)) {
            element.remove();
            return;
        }
        
        const contentEl = element.querySelector('.content');
        if (!contentEl) {
            return;
        }
        
        contentEl.setAttribute('data-type', messageData.type || messageData.message_type || 'message');
        contentEl.innerHTML = renderMessageContentForExport(messageData);
        
        if (isExportConsoleOutput(messageData)) {
            element.classList.add('console-output-message');
        }

        const outputs = stdoutAssociations.get(messageId);
        if (outputs && outputs.length && isExportCodeMessage(messageData)) {
            attachStdoutControlsForExport(contentEl, messageId, outputs);
        }
    });
    
    if (window.Prism && Prism.highlightAllUnder) {
        Prism.highlightAllUnder(chatClone);
    }
    
    return chatClone;
}

async function createSelfContainedHTML() {
    // Get all CSS from the current page
    const allCSS = await extractAllCSS();
    
    // Prepare export chat content
    const exportChat = prepareChatCloneForExport();
    await processImagesInElement(exportChat);
    
    const generatedOn = new Date();
    const generatedDate = generatedOn.toLocaleDateString();
    const generatedTimestamp = generatedOn.toLocaleString();
    const downloadedDisplay = generatedOn.toLocaleString(undefined, {
        year: 'numeric',
        month: 'numeric',
        day: 'numeric',
        hour: 'numeric',
        minute: 'numeric',
        hour12: true,
        timeZoneName: 'short'
    });
    
    // Create the complete HTML document
    const htmlTemplate = `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>IDEA Conversation - ${generatedDate}</title>
    <style>
        ${allCSS}
        
        body.export-view {
            background: var(--body-gradient);
            min-height: 100vh;
            padding: clamp(16px, 5vw, 40px);
            overflow-y: auto !important;
            overflow-x: hidden;
        }

        .export-view .chat-container {
            height: auto;
            max-height: none;
            overflow: visible;
        }

        .export-view .chat-display {
            max-height: none;
            overflow: visible;
        }

        .export-chat-panel {
            flex: 1;
            display: flex;
            flex-direction: column;
            padding: clamp(18px, 4vw, 32px);
            background: var(--surface-alt);
            border-top: 1px solid var(--border);
            border-bottom: 1px solid var(--border);
        }

        .export-chat-panel .chat-display {
            width: 100%;
            min-width: 0;
            flex: 1;
        }

        .export-view .disclaimer-text {
            position: static;
            margin: 0 auto;
            width: min(1200px, 100%);
        }

        .export-header .header-content {
            justify-content: space-between;
            align-items: flex-start;
            gap: clamp(12px, 3vw, 24px);
        }

        .export-view .message .content pre {
            background: rgba(1, 4, 5, 0.9);
            color: #e2e8f0;
            padding: 14px;
            border-radius: 12px;
            overflow-x: auto;
            position: relative;
        }

        body.theme-light.export-view .message .content pre {
            background: #0f172a;
        }

        .export-view .message .content code {
            font-family: 'JetBrains Mono', 'SFMono-Regular', Menlo, Consolas, monospace;
            font-size: 0.92em;
        }

        .export-meta {
            display: flex;
            flex-direction: column;
            gap: 4px;
            text-align: right;
            color: rgba(255, 255, 255, 0.72);
        }

        .export-title {
            font-size: 0.95rem;
        }

        .export-meta-text {
            font-size: 0.9rem;
            color: rgba(255, 255, 255, 0.7);
        }

        .export-brand-link {
            color: rgba(255, 255, 255, 0.72);
            text-decoration: underline;
        }

        .export-brand-link:visited {
            color: rgba(255, 255, 255, 0.72);
        }

        .export-footer {
            margin-top: 18px;
            text-align: center;
            color: var(--text-muted);
            font-size: 0.9rem;
        }

        .export-footer p {
            margin: 0.25rem 0;
        }

        @media print {
            body.export-view {
                padding: 0;
            }

            .chat-container {
                box-shadow: none !important;
            }

            .export-chat-panel {
                padding: 18px 24px;
            }

            .export-footer {
                display: block !important;
                margin-top: 16px;
                font-size: 0.85rem;
                color: #444;
            }
        }
    </style>
</head>
<body class="main-app theme-light export-view">
    <div class="app">
        <div class="chat-container export-chat-container">
            <header class="chat-header export-header">
                <div class="header-content">
                    <div class="header-brand">
                        <span class="brand-abbrev">IDEA</span>
                        <a class="brand-name export-brand-link" href="https://uhslc.soest.hawaii.edu/research/IDEA" target="_blank" rel="noreferrer noopener">Intelligent Data Exploring Assistant</a>
                    </div>
                    <div class="export-meta">
                        <span class="export-title">Downloaded conversation</span>
                        <span class="export-meta-text">${downloadedDisplay}</span>
                        <span class="export-meta-text">(Equation rendering requires internet.)</span>
                    </div>
                </div>
            </header>
            
            <div class="export-chat-panel">
                <div class="chat-display">
                    ${exportChat.innerHTML}
                </div>
            </div>
        </div>
        <div class="export-footer">
            <p>
                IDEA can make mistakes — check important results.
                <a href="https://github.com/uhsealevelcenter/IDEA" target="_blank" rel="noreferrer noopener">[More info on GitHub]</a>
            </p>
        </div>
    </div>
    
    <script>
        window.MathJax = {
            tex: {
                inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
                displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']],
                processEscapes: true,
                processEnvironments: true
            },
            options: {
                skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code']
            },
            svg: { fontCache: 'global' }
        };
    </script>
    <script id="MathJax-script" defer src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js"></script>
    <script>
        // Add some interactivity for the exported file
        document.addEventListener('DOMContentLoaded', function() {
            // Make all links open in new tab
            document.querySelectorAll('a').forEach(link => {
                if (!link.getAttribute('target')) {
                    link.setAttribute('target', '_blank');
                }
            });
            
            const attachCopyButtons = (root = document) => {
                root.querySelectorAll('pre code').forEach(codeBlock => {
                    const pre = codeBlock.parentElement;
                    if (!pre) return;
                    if (pre.querySelector('.copy-button')) return;
                    const copyBtn = document.createElement('button');
                    copyBtn.className = 'copy-button';
                    copyBtn.type = 'button';
                    copyBtn.textContent = 'Copy';
                    pre.appendChild(copyBtn);
                    copyBtn.addEventListener('click', function() {
                        navigator.clipboard.writeText(codeBlock.textContent).then(function() {
                            copyBtn.textContent = 'Copied!';
                            setTimeout(function() {
                                copyBtn.textContent = 'Copy';
                            }, 2000);
                        }).catch(function() {
                            copyBtn.textContent = 'Error';
                            setTimeout(function() {
                                copyBtn.textContent = 'Copy';
                            }, 2000);
                        });
                    });
                });
            };
            attachCopyButtons();

            document.querySelectorAll('.stdout-button').forEach(function(button) {
                button.addEventListener('click', function() {
                    const targetId = button.getAttribute('data-stdout-target');
                    if (!targetId) return;
                    const selector = '.stdout-panel[data-stdout-target="' + targetId + '"]';
                    const panel = document.querySelector(selector);
                    if (!panel) return;
                    const isOpen = panel.classList.toggle('open');
                    panel.setAttribute('aria-hidden', isOpen ? 'false' : 'true');
                    button.textContent = isOpen ? 'Hide Output' : 'Show Output';
                    button.setAttribute('aria-expanded', String(isOpen));
                    if (isOpen) {
                        panel.scrollTop = panel.scrollHeight;
                        panel.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
                        attachCopyButtons(panel);
                    }
                });
            });

            const typesetMath = () => {
                if (window.MathJax && MathJax.typesetPromise) {
                    MathJax.typesetPromise().catch(err => console.warn('MathJax typeset error:', err));
                } else if (!(window.MathJax && MathJax.typesetPromise)) {
                    setTimeout(typesetMath, 150);
                }
            };
            typesetMath();
        });
    </script>
</body>
</html>`;
    
    return htmlTemplate;
}

async function extractAllCSS() {
    let allCSS = '';
    
    // Extract CSS from style tags
    document.querySelectorAll('style').forEach(style => {
        allCSS += style.textContent + '\n';
    });
    
    // Extract CSS from external stylesheets
    const styleSheets = Array.from(document.styleSheets);
    for (const sheet of styleSheets) {
        try {
            if (sheet.href && sheet.href.startsWith(window.location.origin)) {
                // Only process same-origin stylesheets
                const cssRules = Array.from(sheet.cssRules || sheet.rules || []);
                cssRules.forEach(rule => {
                    allCSS += rule.cssText + '\n';
                });
            }
        } catch (e) {
            // Cross-origin stylesheets can't be read, skip them
            console.warn('Could not read stylesheet:', sheet.href);
        }
    }
    
    return allCSS;
}

async function processImagesInElement(element) {
    const images = element.querySelectorAll('img');
    
    for (const img of images) {
        try {
            // Only process images that are not already data URLs
            if (!img.src.startsWith('data:')) {
                const dataURL = await convertImageToDataURL(img);
                if (dataURL) {
                    img.src = dataURL;
                }
            }
        } catch (e) {
            console.warn('Could not convert image to data URL:', img.src);
        }
    }
}

function convertImageToDataURL(img) {
    return new Promise((resolve) => {
        try {
            const canvas = document.createElement('canvas');
            const ctx = canvas.getContext('2d');
            
            // Create a new image to handle cross-origin issues
            const newImg = new Image();
            newImg.crossOrigin = 'anonymous';
            
            newImg.onload = function() {
                canvas.width = newImg.naturalWidth;
                canvas.height = newImg.naturalHeight;
                ctx.drawImage(newImg, 0, 0);
                
                try {
                    const dataURL = canvas.toDataURL('image/png');
                    resolve(dataURL);
                } catch (e) {
                    console.warn('Could not convert image to data URL:', e);
                    resolve(null);
                }
            };
            
            newImg.onerror = function() {
                console.warn('Could not load image for conversion');
                resolve(null);
            };
            
            newImg.src = img.src;
        } catch (e) {
            console.warn('Error in convertImageToDataURL:', e);
            resolve(null);
        }
    });
}

document.addEventListener('DOMContentLoaded', () => {
    initializeFileUpload();
    initializeMobileNavigation();

    initializeMicrophone();

    // Drag overlay logic
    const dropOverlay = document.getElementById('dropOverlay');
    if (!dropOverlay) {
        console.warn('⚠️ dropOverlay element not found in DOM.');
        return;
    }

    let dragTimer;

    document.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropOverlay.classList.add('show');
        clearTimeout(dragTimer);
        dragTimer = setTimeout(() => {
            dropOverlay.classList.remove('show');
        }, 150);
    });

    document.addEventListener('dragleave', () => {
        dropOverlay.classList.remove('show');
    });

    document.addEventListener('drop', async (e) => {
        e.preventDefault();
        dropOverlay.classList.remove('show');

        // Check if drop is happening within knowledge base modal
        const knowledgeBaseModal = document.getElementById('knowledgeBaseModal');
        if (knowledgeBaseModal && knowledgeBaseModal.style.display === 'block') {
            const modalRect = knowledgeBaseModal.getBoundingClientRect();
            if (e.clientX >= modalRect.left && e.clientX <= modalRect.right &&
                e.clientY >= modalRect.top && e.clientY <= modalRect.bottom) {
                // Drop is within knowledge base modal, let it handle the event
                return;
            }
        }

        if (e.dataTransfer?.files?.length > 0) {
            await handleFiles(e.dataTransfer.files);
        }
    });

    // Add download button event listener
    const downloadButton = document.getElementById('downloadButton');
    if (downloadButton) {
        downloadButton.addEventListener('click', downloadConversation);
    }
});

messageInput.addEventListener('input', function() {
    // Reset height to auto to get correct scrollHeight
    this.style.height = 'auto';
    // Set new height based on content
    this.style.height = Math.min(this.scrollHeight, 200) + 'px';
});

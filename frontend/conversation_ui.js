/**
 * Conversation UI Management
 * Handles the UI for conversation history, loading, and management
 */

let isShowingFavorites = false;
// conversationManager is declared in assistant.js

// Bind DOM event listeners at DOMContentLoaded (no conversationManager needed yet)
document.addEventListener('DOMContentLoaded', function() {
    setupConversationEventListeners();
});

// Wire conversationManager listeners once assistant.js has created the instance
window.addEventListener('app:ready', function() {
    setupConversationManagerListeners();
});

function setupConversationEventListeners() {
    // Open conversations modal
    document.getElementById('conversationsButton').addEventListener('click', openConversationsModal);
    document.getElementById('conversationsButtonMobile')?.addEventListener('click', openConversationsModal);
    
    // Close conversations modal
    document.getElementById('closeConversationsModal').addEventListener('click', closeConversationsModal);
    
    // Search conversations
    document.getElementById('conversationSearch').addEventListener('input', debounce(searchConversations, 300));
    
    // Filter buttons
    document.getElementById('showAllConversations').addEventListener('click', () => {
        isShowingFavorites = false;
        updateFilterButtons();
        displayConversations();
    });
    
    document.getElementById('showFavoriteConversations').addEventListener('click', () => {
        isShowingFavorites = true;
        updateFilterButtons();
        displayConversations();
    });
    
    // Refresh conversations
    document.getElementById('refreshConversations').addEventListener('click', async () => {
        await conversationManager.loadConversations({ reset: true });
        displayConversations();
    });

    // Load more conversations
    document.getElementById('loadMoreConversations').addEventListener('click', async () => {
        await conversationManager.loadMoreConversations();
        displayConversations();
    });

    // Delete all conversations
    document.getElementById('deleteAllConversations')?.addEventListener('click', async () => {
        const confirmed = confirm('Supprimer toutes les conversations ? Cette action est irréversible.');
        if (!confirmed) return;
        try {
            await conversationManager.deleteAllConversations();
            showNotification('Toutes les conversations ont été supprimées', 'success');
        } catch (e) {
            showNotification('Échec de la suppression', 'error');
        }
    });

    const csvSidebar = document.getElementById('conversationCsvSidebar');
    const csvToggle = document.getElementById('conversationCsvToggle');
    const csvTitleButton = document.getElementById('conversationCsvTitleButton');
    const csvFloatingButton = document.getElementById('conversationCsvFloatingButton');

    function setCsvSidebarCollapsed(collapsed) {
        if (!csvSidebar) return;
        csvSidebar.classList.toggle('collapsed', collapsed);
        csvSidebar.classList.toggle('open', !collapsed);
        csvSidebar.setAttribute('aria-hidden', String(collapsed));
        csvToggle?.setAttribute('aria-expanded', String(!collapsed));
        csvTitleButton?.setAttribute('aria-expanded', String(!collapsed));
        if (csvFloatingButton) {
            csvFloatingButton.hidden = !collapsed;
            csvFloatingButton.setAttribute('aria-expanded', String(!collapsed));
        }
        localStorage.setItem(CONVERSATION_CSV_SIDEBAR_KEY, String(collapsed));
    }

    if (csvSidebar) {
        setCsvSidebarCollapsed(true);
    }

    csvToggle?.addEventListener('click', () => {
        if (!csvSidebar) return;
        setCsvSidebarCollapsed(true);
    });

    csvTitleButton?.addEventListener('click', () => {
        if (!csvSidebar || !csvSidebar.classList.contains('collapsed')) return;
        setCsvSidebarCollapsed(false);
        refreshConversationCsvSidebar();
    });

    csvFloatingButton?.addEventListener('click', () => {
        if (!csvSidebar) return;
        setCsvSidebarCollapsed(false);
        refreshConversationCsvSidebar();
    });

    _initCsvResizeHandle();
}

const CONVERSATION_CSV_WIDTH_KEY = 'idea-conversation-csv-width';

function _initCsvResizeHandle() {
    const handle = document.getElementById('csvResizeHandle');
    const sidebar = document.getElementById('conversationCsvSidebar');
    if (!handle || !sidebar) return;

    // Restore saved width
    const savedWidth = parseInt(localStorage.getItem(CONVERSATION_CSV_WIDTH_KEY), 10);
    if (savedWidth && savedWidth >= 300) {
        const restoredWidth = Math.min(Math.max(savedWidth, 300), 360);
        sidebar.style.flexBasis = restoredWidth + 'px';
        sidebar.style.width = restoredWidth + 'px';
    }

    let startX = 0;
    let startWidth = 0;

    handle.addEventListener('mousedown', (e) => {
        e.preventDefault();
        startX = e.clientX;
        startWidth = sidebar.getBoundingClientRect().width;
        sidebar.classList.add('resizing');

        function onMouseMove(e) {
            const delta = startX - e.clientX;
            const newWidth = Math.min(
                Math.max(startWidth + delta, 300),
                Math.min(380, window.innerWidth - 88),
            );
            sidebar.style.flexBasis = newWidth + 'px';
            sidebar.style.width = newWidth + 'px';
        }

        function onMouseUp() {
            sidebar.classList.remove('resizing');
            const finalWidth = parseInt(sidebar.style.width, 10);
            if (finalWidth) localStorage.setItem(CONVERSATION_CSV_WIDTH_KEY, String(finalWidth));
            document.removeEventListener('mousemove', onMouseMove);
            document.removeEventListener('mouseup', onMouseUp);
        }

        document.addEventListener('mousemove', onMouseMove);
        document.addEventListener('mouseup', onMouseUp);
    });
}

function setupConversationManagerListeners() {
    // Listen for conversation manager events
    conversationManager.addEventListener('conversations_loaded', displayConversations);
    conversationManager.addEventListener('conversation_created', () => {
        // Refresh the conversation list when a new conversation is created
        displayConversations();
    });
    conversationManager.addEventListener('conversation_updated', displayConversations);
    conversationManager.addEventListener('conversation_deleted', displayConversations);
    conversationManager.addEventListener('conversation_loaded', refreshConversationCsvSidebar);
    conversationManager.addEventListener('messages_updated', refreshConversationCsvSidebar);
}

const CONVERSATION_CSV_SIDEBAR_KEY = 'idea-conversation-csv-collapsed';
const CONVERSATION_CSV_SELECTION_KEY_PREFIX = 'idea-conversation-csv-last-viewed:';
let _currentConversationCsvPath = null;
let _currentConversationCsvConversationId = null;

function _csvSidebarElements() {
    return {
        sidebar: document.getElementById('conversationCsvSidebar'),
        toggle: document.getElementById('conversationCsvToggle'),
        list: document.getElementById('conversationCsvList'),
        viewer: document.getElementById('conversationCsvViewer'),
    };
}

function _conversationCsvSelectionKey(conversationId) {
    return `${CONVERSATION_CSV_SELECTION_KEY_PREFIX}${conversationId || 'global'}`;
}

function _normalizeMessageType(message) {
    return String(message?.message_type || message?.type || '').toLowerCase();
}

function _normalizeMessageFormat(message) {
    return String(message?.message_format || message?.format || '').toLowerCase();
}

function _basename(path) {
    if (typeof path !== 'string') return '';
    return path.split('/').filter(Boolean).pop() || '';
}

function _extractCsvArtifactFromMessage(message) {
    if (!message || typeof message !== 'object') return null;

    const messageType = _normalizeMessageType(message);
    const messageFormat = _normalizeMessageFormat(message);

    if (messageType === 'file') {
        const rawPath = String(message.content || message.file_url || '').trim();
        if (!rawPath || !rawPath.toLowerCase().includes('.csv')) {
            return null;
        }

        return {
            id: message.id || rawPath,
            name: message.filename || message.name || _basename(rawPath) || 'fichier.csv',
            path: rawPath,
            source: messageFormat === 'csv-download' ? 'created' : 'loaded',
        };
    }

    if (messageType === 'deliverable') {
        let payload = null;
        try {
            payload = typeof message.content === 'string' ? JSON.parse(message.content) : null;
        } catch (_) {
            payload = null;
        }

        const rawPath = String(
            payload?.file_url || payload?.file || message.file_url || message.file || ''
        ).trim();
        if (!rawPath || !rawPath.toLowerCase().includes('.csv')) {
            return null;
        }

        return {
            id: message.id || rawPath,
            name: payload?.filename || message.filename || _basename(rawPath) || 'fichier.csv',
            path: rawPath,
            source: 'created',
            title: payload?.title || message.title || null,
        };
    }

    return null;
}

function _collectConversationCsvArtifacts(messages) {
    if (!Array.isArray(messages)) return [];

    const seen = new Set();
    const artifacts = [];
    messages.forEach((message) => {
        const artifact = _extractCsvArtifactFromMessage(message);
        if (!artifact) return;
        const key = artifact.path || artifact.id;
        if (seen.has(key)) return;
        seen.add(key);
        artifacts.push(artifact);
    });
    return artifacts;
}

function _collectPendingConversationCsvArtifacts() {
    const pending = typeof window.getPendingUploads === 'function'
        ? window.getPendingUploads()
        : (Array.isArray(window.pendingUploads) ? window.pendingUploads : []);

    if (!Array.isArray(pending) || pending.length === 0) {
        return [];
    }

    const artifacts = [];
    pending.forEach((attachment) => {
        const path = String(attachment?.path || attachment?.storedName || '').trim();
        if (!path || !path.toLowerCase().includes('.csv')) {
            return;
        }
        artifacts.push({
            id: attachment.id || path,
            name: attachment.name || _basename(path) || 'fichier.csv',
            path,
            source: 'loaded',
        });
    });
    return artifacts;
}

function _collectFrontendConversationCsvArtifacts() {
    const messages = typeof window.getFrontendMessages === 'function'
        ? window.getFrontendMessages()
        : [];

    if (!Array.isArray(messages) || messages.length === 0) {
        return [];
    }

    const artifacts = [];
    messages.forEach((message) => {
        const attachments = Array.isArray(message?.attachments) ? message.attachments : [];
        attachments.forEach((attachment) => {
            const path = String(attachment?.url || attachment?.path || attachment?.file_url || attachment?.storedName || '').trim();
            const name = String(attachment?.name || attachment?.filename || _basename(path) || '').trim();
            if (!path || !path.toLowerCase().includes('.csv')) {
                return;
            }
            artifacts.push({
                id: attachment.id || `${message.id || 'message'}:${path}`,
                name: name || _basename(path) || 'fichier.csv',
                path,
                source: 'loaded',
            });
        });
    });

    return artifacts;
}

function _dedupeCsvArtifacts(artifacts) {
    const seen = new Set();
    return artifacts.filter((artifact) => {
        const key = artifact.path || artifact.id;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
    });
}

function _renderConversationCsvSidebarItem(artifact, isActive = false) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `conversation-csv-item${isActive ? ' active' : ''}`;
    button.dataset.csvPath = artifact.path;

    const badge = document.createElement('span');
    badge.className = `conversation-csv-badge conversation-csv-badge-${artifact.source}`;
    badge.textContent = artifact.source === 'created' ? 'créé' : 'chargé';

    const label = document.createElement('span');
    label.className = 'conversation-csv-label';
    label.textContent = artifact.name;

    button.addEventListener('click', () => {
        selectConversationCsvArtifact(artifact.path, artifact.name).catch((error) => {
            console.error('Failed to preview CSV:', error);
        });
    });

    button.appendChild(badge);
    button.appendChild(label);
    return button;
}

function _resolveConversationCsvUrl(url) {
    const input = String(url || '').trim();
    if (!input) return input;

    const staticHost = `${window.location.protocol}//${window.location.hostname}`;
    if (input.startsWith('/static/')) {
        return `${staticHost}${input}`;
    }

    try {
        const parsed = new URL(input, window.location.href);
        const currentHost = window.location.hostname;
        const localHosts = new Set(['localhost', '127.0.0.1']);
        const isCurrentHost = parsed.hostname === currentHost;
        const isLocalStaticHost = localHosts.has(parsed.hostname) && localHosts.has(currentHost);

        if (parsed.pathname.startsWith('/static/') && (isCurrentHost || isLocalStaticHost)) {
            return `${staticHost}${parsed.pathname}${parsed.search}${parsed.hash}`;
        }
    } catch (_) {
        return input;
    }

    return input;
}

function _splitCsvLine(line) {
    const cells = [];
    let cell = '';
    let inQuotes = false;

    for (let i = 0; i < line.length; i += 1) {
        const ch = line[i];
        if (inQuotes) {
            if (ch === '"' && line[i + 1] === '"') {
                cell += '"';
                i += 1;
            } else if (ch === '"') {
                inQuotes = false;
            } else {
                cell += ch;
            }
        } else if (ch === '"') {
            inQuotes = true;
        } else if (ch === ',') {
            cells.push(cell);
            cell = '';
        } else if (ch !== '\r') {
            cell += ch;
        }
    }

    cells.push(cell);
    return cells;
}

function _parseCsvPreviewRows(text, maxRows = 25) {
    const normalized = String(text || '').replace(/\r\n/g, '\n').trim();
    if (!normalized) {
        return [];
    }
    return normalized
        .split('\n')
        .slice(0, maxRows)
        .map((line) => _splitCsvLine(line));
}

function _renderCsvPreviewTable(text) {
    const rows = _parseCsvPreviewRows(text);
    const table = document.createElement('table');
    table.className = 'conversation-csv-preview-table';

    if (rows.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'conversation-csv-viewer-empty';
        empty.textContent = 'CSV vide';
        return empty;
    }

    const [header, ...bodyRows] = rows;
    const thead = document.createElement('thead');
    const headRow = document.createElement('tr');
    header.forEach((cell) => {
        const th = document.createElement('th');
        th.textContent = cell;
        headRow.appendChild(th);
    });
    thead.appendChild(headRow);
    table.appendChild(thead);

    const tbody = document.createElement('tbody');
    bodyRows.forEach((row) => {
        const tr = document.createElement('tr');
        header.forEach((_, index) => {
            const td = document.createElement('td');
            td.textContent = row[index] || '';
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    return table;
}

function _markConversationCsvActive(path) {
    const { list } = _csvSidebarElements();
    if (!list) return;
    list.querySelectorAll('.conversation-csv-item').forEach((item) => {
        item.classList.toggle('active', item.dataset.csvPath === path);
    });
}

async function selectConversationCsvArtifact(path, name = '') {
    const { viewer } = _csvSidebarElements();
    if (!viewer) return;

    _currentConversationCsvPath = path;
    const currentConversationId = typeof conversationManager?.getCurrentConversationId === 'function'
        ? conversationManager.getCurrentConversationId()
        : null;
    if (currentConversationId) {
        localStorage.setItem(_conversationCsvSelectionKey(currentConversationId), path);
    }
    _currentConversationCsvConversationId = currentConversationId;

    viewer.innerHTML = '';
    const loading = document.createElement('div');
    loading.className = 'conversation-csv-viewer-empty';
    loading.textContent = 'Chargement…';
    viewer.appendChild(loading);

    const response = await fetch(_resolveConversationCsvUrl(path), { credentials: 'same-origin' });
    if (!response.ok) {
        throw new Error(`CSV preview failed with status ${response.status}`);
    }

    const text = await response.text();
    viewer.innerHTML = '';

    const title = document.createElement('div');
    title.className = 'conversation-csv-viewer-title';
    title.textContent = name || _basename(path) || 'CSV';
    viewer.appendChild(title);
    viewer.appendChild(_renderCsvPreviewTable(text));
    viewer.dataset.csvPath = path;
    _markConversationCsvActive(path);
}

function refreshConversationCsvSidebar() {
    const { sidebar, list, viewer, toggle } = _csvSidebarElements();
    if (!sidebar || !list || !viewer) return [];

    const currentConversationId = typeof conversationManager?.getCurrentConversationId === 'function'
        ? conversationManager.getCurrentConversationId()
        : null;
    const storedSelectionPath = currentConversationId
        ? localStorage.getItem(_conversationCsvSelectionKey(currentConversationId))
        : null;
    const sameConversationSelection = (
        _currentConversationCsvConversationId === currentConversationId
            ? _currentConversationCsvPath
            : null
    );

    const messages = typeof conversationManager?.getCurrentMessages === 'function'
        ? conversationManager.getCurrentMessages()
        : [];
    const artifacts = _dedupeCsvArtifacts([
        ..._collectConversationCsvArtifacts(messages),
        ..._collectFrontendConversationCsvArtifacts(),
        ..._collectPendingConversationCsvArtifacts(),
    ]);
    const selectedPath = artifacts.some((artifact) => artifact.path === storedSelectionPath)
        ? storedSelectionPath
        : (artifacts.some((artifact) => artifact.path === sameConversationSelection)
            ? sameConversationSelection
            : null);

    list.innerHTML = '';
    if (artifacts.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'conversation-csv-empty';
        empty.textContent = 'Aucun CSV dans cette conversation';
        list.appendChild(empty);
        _currentConversationCsvPath = null;
        _currentConversationCsvConversationId = currentConversationId;
        viewer.dataset.csvPath = '';
        viewer.innerHTML = '';
        if (currentConversationId) {
            localStorage.removeItem(_conversationCsvSelectionKey(currentConversationId));
        }
    } else {
        artifacts.forEach((artifact, index) => {
            const isActive = selectedPath
                ? artifact.path === selectedPath
                : false;
            list.appendChild(_renderConversationCsvSidebarItem(artifact, isActive));
        });
    }

    const isCollapsed = sidebar.classList.contains('collapsed');
    sidebar.classList.toggle('open', !isCollapsed);
    sidebar.setAttribute('aria-hidden', String(isCollapsed));
    if (toggle) {
        toggle.setAttribute('aria-expanded', String(!isCollapsed));
    }
    document.getElementById('conversationCsvTitleButton')?.setAttribute('aria-expanded', String(!isCollapsed));
    const floatingButton = document.getElementById('conversationCsvFloatingButton');
    if (floatingButton) {
        floatingButton.hidden = !isCollapsed;
        floatingButton.setAttribute('aria-expanded', String(!isCollapsed));
    }

    if (!isCollapsed && selectedPath && viewer.dataset.csvPath !== selectedPath) {
        const selectedArtifact = artifacts.find((artifact) => artifact.path === selectedPath);
        if (selectedArtifact) {
            selectConversationCsvArtifact(selectedArtifact.path, selectedArtifact.name).catch((error) => {
                console.error('Failed to restore CSV preview:', error);
            });
        }
        _currentConversationCsvConversationId = currentConversationId;
    } else if (!isCollapsed && !viewer.querySelector('table')) {
        viewer.innerHTML = '';
        if (artifacts.length > 0) {
            const placeholder = document.createElement('div');
            placeholder.className = 'conversation-csv-viewer-empty';
            placeholder.textContent = 'Aperçu CSV à afficher au clic';
            viewer.appendChild(placeholder);
        }
    }

    return artifacts;
}

function openConversationsModal() {
    ModalUtils.open(document.getElementById('conversationsModal'));
    // Load conversations when modal opens
    displayConversations();
}

function closeConversationsModal() {
    ModalUtils.close(document.getElementById('conversationsModal'));
}

function updateFilterButtons() {
    const allBtn = document.getElementById('showAllConversations');
    const favBtn = document.getElementById('showFavoriteConversations');
    
    if (isShowingFavorites) {
        allBtn.classList.remove('active');
        favBtn.classList.add('active');
    } else {
        allBtn.classList.add('active');
        favBtn.classList.remove('active');
    }
}

function displayConversations() {
    const conversationsList = document.getElementById('conversationsList');
    const conversations = conversationManager.getAllConversations();
    const searchTerm = document.getElementById('conversationSearch').value.toLowerCase();

    let filteredConversations = conversations;
    if (isShowingFavorites) filteredConversations = conversations.filter(c => c.is_favorite);
    if (searchTerm) filteredConversations = filteredConversations.filter(c => c.title && c.title.toLowerCase().includes(searchTerm));

    if (filteredConversations.length === 0) {
        conversationsList.innerHTML = `
            <div class="empty-state">
                <span class="material-icons">chat_bubble_outline</span>
                <p>${isShowingFavorites ? 'No favorite conversations found' : 'No conversations found'}</p>
                <p class="empty-state-subtitle">Start a new conversation to see it here</p>
            </div>
        `;
        updateLoadMoreState(0);
        return;
    }

    // Remove stale placeholders if the list now has items
    conversationsList.querySelector('.empty-state')?.remove();
    conversationsList.querySelector('.loading')?.remove();

    const currentConvId = conversationManager.getCurrentConversationId();
    const filteredIds = new Set(filteredConversations.map(c => c.id));

    // Remove items no longer in the filtered list
    conversationsList.querySelectorAll('.conversation-item').forEach(el => {
        if (!filteredIds.has(el.id.replace('conversation-', ''))) el.remove();
    });

    // Reconcile: update existing items in-place, create missing ones.
    // appendChild on an existing node moves it — this reorders to match filteredConversations.
    filteredConversations.forEach(conversation => {
        let el = document.getElementById(`conversation-${conversation.id}`);
        if (el) {
            _updateConversationItem(el, conversation, currentConvId);
        } else {
            const tmp = document.createElement('div');
            tmp.innerHTML = createConversationItem(conversation);
            el = tmp.firstElementChild;
            _bindConversationItemListeners(el, conversation);
        }
        conversationsList.appendChild(el);
    });

    updateLoadMoreState(filteredConversations.length);
}

function _updateConversationItem(el, conversation, currentConvId) {
    el.classList.toggle('current', conversation.id === currentConvId);

    const title = conversation.title || 'Untitled Conversation';
    const titleEl = el.querySelector('.conversation-title');
    if (titleEl && titleEl.textContent !== title) titleEl.textContent = title;

    const favBtn = el.querySelector('.favorite-btn');
    if (favBtn) {
        favBtn.classList.toggle('active', !!conversation.is_favorite);
        favBtn.title = conversation.is_favorite ? 'Remove from favorites' : 'Add to favorites';
        const icon = favBtn.querySelector('.material-icons');
        if (icon) icon.textContent = conversation.is_favorite ? 'star' : 'star_border';
    }

    const meta = el.querySelector('.conversation-meta');
    if (meta) {
        const favIndicator = meta.querySelector('.favorite-indicator');
        if (conversation.is_favorite && !favIndicator) {
            meta.insertAdjacentHTML('beforeend', '<span class="material-icons favorite-indicator">star</span>');
        } else if (!conversation.is_favorite && favIndicator) {
            favIndicator.remove();
        }
    }
}

function _bindConversationItemListeners(el, conversation) {
    el.addEventListener('click', (e) => {
        if (!e.target.closest('.conversation-actions')) loadConversation(conversation.id);
    });
    el.querySelector('.favorite-btn')?.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleFavorite(conversation.id);
    });
    el.querySelector('.delete-btn')?.addEventListener('click', (e) => {
        e.stopPropagation();
        deleteConversation(conversation.id, conversation.title);
    });
    el.querySelector('.share-btn')?.addEventListener('click', (e) => {
        e.stopPropagation();
        shareConversation(conversation.id);
    });
}

function updateLoadMoreState(visibleCount = null) {
    const loadMoreButton = document.getElementById('loadMoreConversations');
    const countLabel = document.getElementById('conversationCount');
    if (!loadMoreButton || !countLabel) {
        return;
    }

    const loadedCount = conversationManager.getAllConversations().length;
    const totalCount = conversationManager.getTotalConversations();
    const hasMore = conversationManager.hasMoreConversations();
    const isLoading = conversationManager.isLoadingConversations();
    const displayedCount = visibleCount === null ? loadedCount : visibleCount;

    if (totalCount > 0) {
        countLabel.textContent = `Showing ${displayedCount} of ${totalCount}`;
    } else if (loadedCount > 0) {
        countLabel.textContent = `Showing ${displayedCount}`;
    } else {
        countLabel.textContent = '';
    }

    loadMoreButton.style.display = hasMore ? 'inline-flex' : 'none';
    loadMoreButton.disabled = isLoading;
    loadMoreButton.textContent = isLoading ? 'Loading...' : 'Load more';
}

function createConversationItem(conversation) {
    const date = new Date(conversation.created_at).toLocaleDateString();
    const time = new Date(conversation.created_at).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
    const title = conversation.title || 'Untitled Conversation';
    const isCurrentConversation = conversation.id === conversationManager.getCurrentConversationId();
    
    return `
        <div class="conversation-item ${isCurrentConversation ? 'current' : ''}" id="conversation-${conversation.id}">
            <div class="conversation-content">
                <div class="conversation-header">
                    <h4 class="conversation-title">${escapeHtml(title)}</h4>
                    <div class="conversation-meta">
                        <span class="conversation-date">${date} ${time}</span>
                        ${conversation.is_favorite ? '<span class="material-icons favorite-indicator">star</span>' : ''}
                        ${conversation.is_shared ? '<span class="material-icons shared-indicator">share</span>' : ''}
                    </div>
                </div>
            </div>
            <div class="conversation-actions">
                <button class="action-btn favorite-btn ${conversation.is_favorite ? 'active' : ''}" 
                        title="${conversation.is_favorite ? 'Remove from favorites' : 'Add to favorites'}">
                    <span class="material-icons">${conversation.is_favorite ? 'star' : 'star_border'}</span>
                </button>
                <button class="action-btn share-btn" title="Share conversation">
                    <span class="material-icons">share</span>
                </button>
                <button class="action-btn delete-btn" title="Delete conversation">
                    <span class="material-icons">delete</span>
                </button>
            </div>
        </div>
    `;
}

async function loadConversation(conversationId) {
    try {
        const conversation = await conversationManager.loadConversation(conversationId);

        closeConversationsModal();

        const chatDisplay = document.getElementById('chatDisplay');
        const loadedMessages = conversationManager.getCurrentMessages() || [];

        if (typeof window.resetSessionForConversationLoad === 'function') {
            window.resetSessionForConversationLoad();
        }
        localStorage.setItem('activeConversationId', conversationId);

        if (typeof window.hydrateChatWithMessages === 'function') {
            window.hydrateChatWithMessages(loadedMessages, { persist: false });
        } else {
            chatDisplay.innerHTML = '';
            if (typeof window.resetStdoutState === 'function') window.resetStdoutState();
            loadedMessages.forEach(message => displayMessageInChat(message));
        }

        displayConversations();
        showNotification(`Loaded conversation: ${conversation.title || 'Untitled'}`, 'success');

        // Interpreter sync is best-effort: a failure here does NOT mean the conversation
        // failed to load — the DB history is already displayed. Surface it as a warning only.
        try {
            await loadConversationIntoInterpreter(loadedMessages);
        } catch (syncError) {
            console.warn('Interpreter sync failed after conversation load:', syncError);
            showNotification('Historique chargé — contexte interprète non synchronisé', 'warning');
        }

    } catch (error) {
        console.error('Error loading conversation:', error);
        showNotification('Impossible de charger la conversation', 'error');
    }
}

async function toggleFavorite(conversationId) {
    try {
        await conversationManager.toggleFavorite(conversationId);
        displayConversations();
        showNotification('Conversation updated', 'success');
    } catch (error) {
        console.error('Error toggling favorite:', error);
        showNotification('Failed to update conversation', 'error');
    }
}

async function deleteConversation(conversationId, title) {
    const confirmed = confirm(`Are you sure you want to delete "${title || 'this conversation'}"? This action cannot be undone.`);

    if (confirmed) {
        try {
            await conversationManager.deleteConversation(conversationId);
            displayConversations();

            // Si la conversation supprimée était active, vider le chat et refresher la session
            if (localStorage.getItem('activeConversationId') === conversationId) {
                localStorage.removeItem('activeConversationId');
                const chatDisplay = document.getElementById('chatDisplay');
                if (chatDisplay) chatDisplay.innerHTML = '';
                if (typeof window.resetSessionForConversationLoad === 'function') {
                    window.resetSessionForConversationLoad();
                }
                if (typeof window.showPromptIdeas === 'function') window.showPromptIdeas();
            }

            showNotification('Conversation deleted', 'success');
        } catch (error) {
            console.error('Error deleting conversation:', error);
            showNotification('Failed to delete conversation', 'error');
        }
    }
}

async function shareConversation(conversationId) {
    try {
        const shareData = await conversationManager.createShareLink(conversationId);
        
        // Create full URL
        const fullShareUrl = `${window.location.origin}${shareData.share_url}`;
        
        // Try to copy to clipboard
        let copiedToClipboard = false;
        if (navigator.clipboard && navigator.clipboard.writeText) {
            try {
                await navigator.clipboard.writeText(fullShareUrl);
                copiedToClipboard = true;
                showNotification('Share link copied to clipboard!', 'success');
            } catch (clipboardError) {
                console.warn('Clipboard copy failed, falling back to prompt:', clipboardError);
            }
        }

        if (!copiedToClipboard) {
            // Fallback: show the URL in a prompt
            prompt('Copy this link to share the conversation:', fullShareUrl);
        }
        
        displayConversations();
        
    } catch (error) {
        console.error('Error creating share link:', error);
        showNotification('Failed to create share link', 'error');
    }
}

function displayMessageInChat(message) {
    const chatDisplay = document.getElementById('chatDisplay');
    
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${message.role}`;
    messageDiv.setAttribute('data-id', message.id || generateId('msg'));
    
    const contentElement = document.createElement('div');
    contentElement.classList.add('content');
    const effectiveType =
        message.message_type === 'message'
        && typeof isDeliverableJsonContent === 'function'
        && isDeliverableJsonContent(message.content)
            ? 'deliverable'
            : message.message_type;
    contentElement.setAttribute('data-type', effectiveType);
    
    // Handle different message types and formats similar to updateMessageContent in assistant.js
    if (effectiveType === 'message') {
        contentElement.innerHTML = marked
            ? DOMPurify.sanitize(marked.parse(message.content))
            : escapeHtml(message.content);
    } else if (effectiveType === 'image') {
        if (message.message_format === 'base64.png') {
            contentElement.innerHTML = `<img src="data:image/png;base64,${message.content}" alt="Image">`;
        } else if (message.message_format === 'path') {
            const img = document.createElement('img');
            img.src = message.content;
            img.alt = 'Image';
            contentElement.appendChild(img);
        } else {
            const img = document.createElement('img');
            img.src = message.content;
            img.alt = 'Image';
            contentElement.appendChild(img);
        }
    } else if (effectiveType === 'code') {
        if (message.message_format === 'html') {
            contentElement.innerHTML = DOMPurify.sanitize(message.content);
        } else {
            const language = message.message_format || '';
            contentElement.innerHTML = `<pre><code class="language-${language}">${escapeHtml(message.content)}</code></pre>`;
        }
    } else if (effectiveType === 'console') {
        contentElement.innerHTML = `<pre>${escapeHtml(message.content)}</pre>`;
        contentElement.style.display = 'none';
    } else if (effectiveType === 'deliverable') {
        contentElement.appendChild(_renderDeliverableCard(message.content || '{}'));
    } else if (effectiveType === 'file') {
        const link = document.createElement('a');
        link.href = message.content;
        link.download = '';
        link.textContent = 'Download File';
        contentElement.appendChild(link);
    } else {
        contentElement.innerHTML = DOMPurify.sanitize(message.content);
    }
    
    messageDiv.appendChild(contentElement);
    chatDisplay.appendChild(messageDiv);
    
    // Scroll to bottom
    chatDisplay.scrollTop = chatDisplay.scrollHeight;
    
    // Apply syntax highlighting if there's code
    if (typeof Prism !== 'undefined') {
        Prism.highlightAllUnder(messageDiv);
    }
    
    // Re-render MathJax if available
    if (typeof MathJax !== 'undefined' && MathJax.typesetPromise) {
        MathJax.typesetPromise([messageDiv]);
    }
}

// Helper function to generate IDs (matching the one in assistant.js)
function generateId(id_type) {
    return id_type + '-' + Math.random().toString(36).substr(2, 9);
}

function searchConversations() {
    displayConversations();
}

function showNotification(message, type = 'info') {
    // Create notification element
    const notification = document.createElement('div');
    notification.className = `notification ${type}`;
    notification.innerHTML = `
        <span class="material-icons">${getNotificationIcon(type)}</span>
        <span>${message}</span>
    `;
    
    // Add to page
    document.body.appendChild(notification);
    
    // Show notification
    setTimeout(() => notification.classList.add('show'), 100);
    
    // Hide and remove after 3 seconds
    setTimeout(() => {
        notification.classList.remove('show');
        setTimeout(() => document.body.removeChild(notification), 300);
    }, 3000);
}

function getNotificationIcon(type) {
    switch (type) {
        case 'success': return 'check_circle';
        case 'error': return 'error';
        case 'warning': return 'warning';
        default: return 'info';
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Shared promise to coalesce concurrent calls — only one HTTP request goes out at a time.
let _loadingIntoInterpreter = null;

async function loadConversationIntoInterpreter(messages) {
    if (_loadingIntoInterpreter) return _loadingIntoInterpreter;
    _loadingIntoInterpreter = _doLoadConversationIntoInterpreter(messages).finally(() => {
        _loadingIntoInterpreter = null;
    });
    return _loadingIntoInterpreter;
}

async function _doLoadConversationIntoInterpreter(messages) {
    try {
        const response = await fetch(config.getEndpoints().loadConversation, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Session-Id': sessionId,
                ...getAuthHeaders()
            },
            body: JSON.stringify({
                messages: messages
            })
        });

        if (!response.ok) {
            throw new Error(`Failed to load conversation into interpreter: ${response.status}`);
        }

        const result = await response.json();
        console.log(`Loaded ${result.message_count} messages into interpreter context`);

    } catch (error) {
        console.error('Error loading conversation into interpreter:', error);
        throw error;
    }
}

// Export for use in other modules
window.conversationUI = {
    openConversationsModal,
    closeConversationsModal,
    displayMessageInChat,
    showNotification,
    displayConversations,
    refreshConversationCsvSidebar,
    selectConversationCsvArtifact,
};

window.loadConversation = loadConversation;
window.loadConversationIntoInterpreter = loadConversationIntoInterpreter;

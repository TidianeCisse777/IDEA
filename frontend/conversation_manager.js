/**
 * Conversation Management Module
 * Handles conversation persistence, message storage, and conversation history
 */

const MESSAGE_TYPES = {
    MESSAGE: 'message',
    CODE: 'code',
    IMAGE: 'image',
    CONSOLE: 'console',
    FILE: 'file',
    CONFIRMATION: 'confirmation'
};

const MESSAGE_ROLES = {
    USER: 'user',
    ASSISTANT: 'assistant',
    COMPUTER: 'computer'
};

class ConversationManager {
    constructor(apiBaseUrl) {
        this.apiBaseUrl = apiBaseUrl || window.API_BASE_URL || 'http://localhost:8002';
        this.currentConversationId = null;
        this.conversations = [];
        this.currentMessages = [];
        this.pageSize = 100;
        this.totalCount = 0;
        this.isLoading = false;
        this._persistenceQueue = [];
        this._retryScheduled = false;
        this._creatingConversation = null;

        // Initialize conversation management
        this.init();
    }
    
    getAuthHeaders() {
        return Auth.getAuthHeaders();
    }

    _handle401() {
        localStorage.removeItem('authToken');
        if (typeof redirectToLogin === 'function') {
            redirectToLogin();
        } else {
            window.location.href = 'login.html';
        }
    }

    async _fetchWithAuth(url, options = {}) {
        const response = await fetch(url, {
            ...options,
            headers: { 'Content-Type': 'application/json', ...this.getAuthHeaders(), ...(options.headers || {}) },
        });
        if (response.status === 401) {
            this._handle401();
            throw new Error('Session expirée');
        }
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response;
    }
    
    /**
     * Initialize the conversation manager
     */
    async init() {
        try {
            await this.loadConversations();
        } catch (error) {
            console.error('Failed to initialize conversation manager:', error);
        }
    }
    
    /**
     * Load all conversations for the current user
     */
    async loadConversations({ reset = true } = {}) {
        if (this.isLoading) {
            return this.conversations;
        }

        const skip = reset ? 0 : this.conversations.length;
        const limit = this.pageSize;

        try {
            this.isLoading = true;
            const url = new URL(`${this.apiBaseUrl}/conversations/`);
            url.searchParams.set('skip', skip);
            url.searchParams.set('limit', limit);

            const response = await this._fetchWithAuth(url.toString());
            const data = await response.json();
            const fetched = data.data || [];
            const total = typeof data.count === 'number' ? data.count : null;
            if (reset) {
                this.conversations = fetched;
            } else {
                const existingIds = new Set(this.conversations.map(conv => conv.id));
                const uniqueFetched = fetched.filter(conv => !existingIds.has(conv.id));
                this.conversations = this.conversations.concat(uniqueFetched);
            }
            if (total !== null) {
                this.totalCount = total;
            } else {
                this.totalCount = Math.max(this.totalCount, this.conversations.length);
            }
            this.notifyConversationListeners('conversations_loaded', this.conversations);
            return this.conversations;
        } catch (error) {
            console.error('Error loading conversations:', error);
            throw error;
        } finally {
            this.isLoading = false;
        }
    }

    /**
     * Load the next page of conversations
     */
    async loadMoreConversations() {
        if (!this.hasMoreConversations()) {
            return this.conversations;
        }
        return this.loadConversations({ reset: false });
    }
    
    /**
     * Create a new conversation
     */
    async createConversation(title = null) {
        try {
            const response = await this._fetchWithAuth(`${this.apiBaseUrl}/conversations/`, {
                method: 'POST',
                body: JSON.stringify({ title }),
            });

            const conversation = await response.json();
            this.conversations.unshift(conversation);
            this.totalCount += 1;
            this.currentConversationId = conversation.id;
            this.currentMessages = [];
            localStorage.setItem('activeConversationId', conversation.id);

            this.notifyConversationListeners('conversation_created', conversation);
            this.notifyConversationListeners('conversation_changed', conversation);
            return conversation;
        } catch (error) {
            console.error('Error creating conversation:', error);
            throw error;
        }
    }
    
    /**
     * Get a specific conversation with its messages
     */
    async loadConversation(conversationId) {
        try {
            const response = await this._fetchWithAuth(`${this.apiBaseUrl}/conversations/${conversationId}`);
            const conversation = await response.json();
            this.currentConversationId = conversationId;
            this.currentMessages = conversation.messages || [];

            this.notifyConversationListeners('conversation_loaded', conversation);
            this.notifyConversationListeners('messages_updated', this.currentMessages);
            return conversation;
        } catch (error) {
            console.error('Error loading conversation:', error);
            throw error;
        }
    }
    
    /**
     * Add a message to the current conversation
     */
    async addMessage(role, content, messageType = MESSAGE_TYPES.MESSAGE, messageFormat = null, recipient = null) {
        if (!this.currentConversationId) {
            // Serialize concurrent calls so only one conversation is created
            if (!this._creatingConversation) {
                this._creatingConversation = this.createConversation().finally(() => {
                    this._creatingConversation = null;
                });
            }
            await this._creatingConversation;
        }

        try {
            const messageData = {
                role,
                content,
                message_type: messageType,
                message_format: messageFormat,
                recipient,
                conversation_id: this.currentConversationId,
            };

            const response = await this._fetchWithAuth(
                `${this.apiBaseUrl}/conversations/${this.currentConversationId}/messages`,
                { method: 'POST', body: JSON.stringify(messageData) }
            );
            const message = await response.json();
            this.currentMessages.push(message);

            // Update the conversation's updated_at timestamp in our local list
            const conversationIndex = this.conversations.findIndex(c => c.id === this.currentConversationId);
            if (conversationIndex !== -1) {
                this.conversations[conversationIndex].updated_at = message.created_at;
                // Move to top of list
                const conversation = this.conversations.splice(conversationIndex, 1)[0];
                this.conversations.unshift(conversation);
            }

            this.notifyConversationListeners('message_added', message);
            this.notifyConversationListeners('messages_updated', this.currentMessages);
            return message;
        } catch (error) {
            console.error('Error adding message:', error);
            this._enqueueForRetry({
                conversationId: this.currentConversationId,
                data: {
                    role,
                    content,
                    message_type: messageType,
                    message_format: messageFormat,
                    recipient,
                    conversation_id: this.currentConversationId,
                },
            });
            throw error;
        }
    }

    _enqueueForRetry(item) {
        this._persistenceQueue.push(item);
        if (!this._retryScheduled) {
            this._retryScheduled = true;
            setTimeout(() => this._flushPersistenceQueue(), 5000);
        }
        this.notifyConversationListeners('persistence_error', { queued: this._persistenceQueue.length });
    }

    async _flushPersistenceQueue() {
        this._retryScheduled = false;
        const queue = this._persistenceQueue.splice(0);
        const failed = [];
        for (const item of queue) {
            if (!item.conversationId) { failed.push(item); continue; }
            try {
                const response = await this._fetchWithAuth(
                    `${this.apiBaseUrl}/conversations/${item.conversationId}/messages`,
                    { method: 'POST', body: JSON.stringify(item.data) }
                );
                const message = await response.json();
                this.currentMessages.push(message);
                this.notifyConversationListeners('message_added', message);
            } catch (_) {
                failed.push(item);
            }
        }
        if (failed.length > 0) {
            this.notifyConversationListeners('persistence_failed', { count: failed.length });
        } else {
            this.notifyConversationListeners('persistence_recovered', {});
        }
    }
    
    /**
     * Delete a conversation
     */
    async deleteConversation(conversationId) {
        try {
            await this._fetchWithAuth(`${this.apiBaseUrl}/conversations/${conversationId}`, {
                method: 'DELETE',
            });

            this.conversations = this.conversations.filter(c => c.id !== conversationId);
            if (this.totalCount > 0) this.totalCount -= 1;

            if (this.currentConversationId === conversationId) {
                this.currentConversationId = null;
                this.currentMessages = [];
                this.notifyConversationListeners('conversation_changed', null);
                this.notifyConversationListeners('messages_updated', []);
            }

            this.notifyConversationListeners('conversation_deleted', conversationId);
            this.notifyConversationListeners('conversations_loaded', this.conversations);
        } catch (error) {
            console.error('Error deleting conversation:', error);
            throw error;
        }
    }
    
    /**
     * Delete all conversations for the current user
     */
    async deleteAllConversations() {
        await this._fetchWithAuth(`${this.apiBaseUrl}/conversations/`, {
            method: 'DELETE',
        });
        this.conversations = [];
        this.totalCount = 0;
        if (this.currentConversationId) {
            this.currentConversationId = null;
            this.currentMessages = [];
            this.notifyConversationListeners('conversation_changed', null);
            this.notifyConversationListeners('messages_updated', []);
        }
        this.notifyConversationListeners('conversations_loaded', []);
    }

    /**
     * Update conversation (title, favorite status)
     */
    async updateConversation(conversationId, updates) {
        try {
            const response = await this._fetchWithAuth(`${this.apiBaseUrl}/conversations/${conversationId}`, {
                method: 'PUT',
                body: JSON.stringify(updates),
            });
            const updatedConversation = await response.json();

            const index = this.conversations.findIndex(c => c.id === conversationId);
            if (index !== -1) this.conversations[index] = updatedConversation;

            this.notifyConversationListeners('conversation_updated', updatedConversation);
            this.notifyConversationListeners('conversations_loaded', this.conversations);
            return updatedConversation;
        } catch (error) {
            console.error('Error updating conversation:', error);
            throw error;
        }
    }
    
    /**
     * Toggle favorite status of a conversation
     */
    async toggleFavorite(conversationId) {
        try {
            const response = await this._fetchWithAuth(
                `${this.apiBaseUrl}/conversations/${conversationId}/favorite`,
                { method: 'POST' }
            );
            const updatedConversation = await response.json();

            const index = this.conversations.findIndex(c => c.id === conversationId);
            if (index !== -1) this.conversations[index] = updatedConversation;

            this.notifyConversationListeners('conversation_updated', updatedConversation);
            this.notifyConversationListeners('conversations_loaded', this.conversations);
            return updatedConversation;
        } catch (error) {
            console.error('Error toggling favorite:', error);
            throw error;
        }
    }
    
    /**
     * Create a share link for a conversation
     */
    async createShareLink(conversationId) {
        try {
            const response = await this._fetchWithAuth(
                `${this.apiBaseUrl}/conversations/${conversationId}/share`,
                { method: 'POST', body: JSON.stringify({}) }
            );
            const shareData = await response.json();

            const index = this.conversations.findIndex(c => c.id === conversationId);
            if (index !== -1) this.conversations[index].is_shared = true;

            this.notifyConversationListeners('share_created', shareData);
            return shareData;
        } catch (error) {
            console.error('Error creating share link:', error);
            throw error;
        }
    }
    
    /**
     * Start a new conversation (clear current state)
     */
    startNewConversation() {
        this.currentConversationId = null;
        this.currentMessages = [];
        this.notifyConversationListeners('conversation_changed', null);
        this.notifyConversationListeners('messages_updated', []);
    }
    
    /**
     * Get current conversation ID
     */
    getCurrentConversationId() {
        return this.currentConversationId;
    }
    
    /**
     * Get current messages
     */
    getCurrentMessages() {
        return this.currentMessages;
    }
    
    /**
     * Get all conversations
     */
    getAllConversations() {
        return this.conversations;
    }

    /**
     * Get total conversation count
     */
    getTotalConversations() {
        return this.totalCount;
    }

    /**
     * Check if more conversations are available
     */
    hasMoreConversations() {
        return this.totalCount > this.conversations.length;
    }

    /**
     * Check if conversation list is loading
     */
    isLoadingConversations() {
        return this.isLoading;
    }
    
    /**
     * Event listener management
     */
    listeners = {};
    
    addEventListener(event, callback) {
        if (!this.listeners[event]) {
            this.listeners[event] = [];
        }
        this.listeners[event].push(callback);
    }
    
    removeEventListener(event, callback) {
        if (this.listeners[event]) {
            this.listeners[event] = this.listeners[event].filter(cb => cb !== callback);
        }
    }
    
    notifyConversationListeners(event, data) {
        if (this.listeners[event]) {
            this.listeners[event].forEach(callback => {
                try {
                    callback(data);
                } catch (error) {
                    console.error('Error in conversation event listener:', error);
                }
            });
        }
    }
}

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { ConversationManager, MESSAGE_TYPES, MESSAGE_ROLES };
} else {
    window.ConversationManager = ConversationManager;
    window.MESSAGE_TYPES = MESSAGE_TYPES;
    window.MESSAGE_ROLES = MESSAGE_ROLES;
}

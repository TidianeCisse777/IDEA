// Auto-detect environment: localhost = local, anything else = production
const _isLocal = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
const _base = _isLocal ? 'http://localhost' : window.location.origin;

const config = {
    environment: _isLocal ? 'local' : 'production',
    
    // API endpoints
    endpoints: {
        local: {
            chat: 'http://localhost/api/chat',
            history: 'http://localhost/api/history',
            clear: 'http://localhost/api/clear',
            interrupt: 'http://localhost/api/interrupt',
            upload: 'http://localhost/api/upload',
            files: 'http://localhost/api/files',
            transcribe: 'http://localhost/api/transcribe',
            login: 'http://localhost/api/login',
            logout: 'http://localhost/api/logout',
            changePassword: 'http://localhost/api/users/change-password',
            verify: 'http://localhost/api/auth/verify',
            userProfile: 'http://localhost/api/users/me',
            users: 'http://localhost/api/users',
            prompts: 'http://localhost/api/prompts',
            setActivePrompt: 'http://localhost/api/prompts/set-active',
            knowledgeBase: 'http://localhost/api/knowledge-base/papers',
            knowledgeBaseUpload: 'http://localhost/api/knowledge-base/papers/upload',
            knowledgeBaseStats: 'http://localhost/api/knowledge-base/stats',
            conversations: 'http://localhost/api/conversations',
            conversationMessages: 'http://localhost/api/conversations',
            conversationShare: 'http://localhost/conversations',
            loadConversation: 'http://localhost/api/load-conversation'
        },
        production: {
            chat: `${_base}/api/chat`,
            history: `${_base}/api/history`,
            clear: `${_base}/api/clear`,
            interrupt: `${_base}/api/interrupt`,
            upload: `${_base}/api/upload`,
            files: `${_base}/api/files`,
            transcribe: `${_base}/api/transcribe`,
            login: `${_base}/api/login`,
            logout: `${_base}/api/logout`,
            verify: `${_base}/api/auth/verify`,
            userProfile: `${_base}/api/users/me`,
            users: `${_base}/api/users`,
            changePassword: `${_base}/api/users/change-password`,
            prompts: `${_base}/api/prompts`,
            setActivePrompt: `${_base}/api/prompts/set-active`,
            knowledgeBase: `${_base}/api/knowledge-base/papers`,
            knowledgeBaseUpload: `${_base}/api/knowledge-base/papers/upload`,
            knowledgeBaseStats: `${_base}/api/knowledge-base/stats`,
            conversations: `${_base}/conversations`,
            conversationMessages: `${_base}/conversations`,
            conversationShare: `${_base}/conversations`,
            loadConversation: `${_base}/api/load-conversation`
        }
    },

    // Get the current environment's endpoints
    getEndpoints() {
        return this.endpoints[this.environment];
    }
};

// Set global API_BASE_URL for ConversationManager
window.API_BASE_URL = (() => {
    const endpoints = config.endpoints[config.environment];
    if (endpoints.conversations) {
        const url = new URL(endpoints.conversations);
        return `${url.protocol}//${url.host}`;
    }
    return 'http://localhost:8002';
})();

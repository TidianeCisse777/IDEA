// welcome-screen.js — écran d'accueil, profil utilisateur, prompt ideas

function deriveFirstName(fullName) {
    if (!fullName || typeof fullName !== 'string') return null;
    const trimmed = fullName.trim();
    if (!trimmed) return null;
    return trimmed.split(/\s+/)[0] || null;
}

function getWelcomeGreeting() {
    return '';
}

function updateWelcomeExtras(welcomeEl) {
    const content = welcomeEl.querySelector('.chat-welcome-content');
    if (!content) return;
    content.querySelectorAll('.chat-welcome-body, .chat-welcome-hints, .chat-welcome-title').forEach(el => el.remove());
    const title = document.createElement('p');
    title.className = 'chat-welcome-title';
    title.textContent = 'Comment ça marche ?';
    content.appendChild(title);
    const hints = document.createElement('ol');
    hints.className = 'chat-welcome-hints';
    ['Chargez un fichier', 'Décrivez votre contexte scientifique', 'Posez votre question', 'Explorez les résultats'].forEach(text => {
        const li = document.createElement('li');
        li.textContent = text;
        hints.appendChild(li);
    });
    content.appendChild(hints);
}

async function loadCurrentUserProfile() {
    if (userProfilePromise) return userProfilePromise;
    userProfilePromise = (async () => {
        try {
            const response = await fetch(config.getEndpoints().userProfile, {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json',
                    ...getAuthHeaders()
                }
            });
            if (!response.ok) {
                throw new Error('Failed to load user profile');
            }
            const profile = await response.json();
            currentUserFirstName = deriveFirstName(profile.full_name);
        } catch (error) {
            console.warn('Unable to load user profile for greeting:', error);
            currentUserFirstName = null;
        }
    })();
    return userProfilePromise;
}

async function waitForNameOrTimeout(timeoutMs = 1000) {
    let resolvedName = null;
    const timeout = new Promise((resolve) => setTimeout(resolve, timeoutMs));
    const profile = loadCurrentUserProfile().then(() => {
        resolvedName = currentUserFirstName;
    }).catch(() => {
        resolvedName = null;
    });
    await Promise.race([profile, timeout]);
    return resolvedName || currentUserFirstName || null;
}

async function renderWelcomeGreeting() {
    if (welcomeRendered) {
        const section = ensureWelcomeSection();
        if (section?.welcome) {
            updateWelcomeExtras(section.welcome);
            section.welcome.classList.remove('hidden');
        }
        return Promise.resolve();
    }
    if (welcomeRenderPromise) return welcomeRenderPromise;
    welcomeRenderPromise = (async () => {
        const section = ensureWelcomeSection();
        if (!section?.welcome) return;
        updateWelcomeExtras(section.welcome);
        section.welcome.classList.remove('hidden');
        welcomeRendered = true;
    })().finally(() => {
        welcomeRenderPromise = null;
    });
    return welcomeRenderPromise;
}

window.refreshWelcome = function () {
    welcomeRendered = false;
    renderWelcomeGreeting();
};

function ensureWelcomeSection() {
    if (!chatDisplay) return null;
    let welcome = document.getElementById('chatWelcome');
    if (!welcome) {
        welcome = document.createElement('div');
        welcome.id = 'chatWelcome';
        welcome.className = 'chat-welcome';
    }

    let bubble = welcome.querySelector('.chat-welcome-bubble');
    if (!bubble) {
        welcome.innerHTML = '';

        bubble = document.createElement('div');
        bubble.className = 'message assistant chat-welcome-bubble';

        const content = document.createElement('div');
        content.className = 'content chat-welcome-content';

        bubble.appendChild(content);
        welcome.appendChild(bubble);
    }

    welcome.classList.add('hidden');

    if (!chatDisplay.contains(welcome)) {
        chatDisplay.prepend(welcome);
    }

    return { welcome };
}

function showWelcomeSection() {
    return ensureWelcomeSection();
}

function hideWelcomeSection() {
    const welcome = document.getElementById('chatWelcome');
    if (welcome) {
        welcome.classList.add('hidden');
    }
}

function showPromptExamplesSection() {
    const examplesSection = document.getElementById('promptExamplesSection');
    if (examplesSection) {
        examplesSection.classList.remove('hidden');
    }
}

function hidePromptExamplesSection() {
    const examplesSection = document.getElementById('promptExamplesSection');
    if (examplesSection) {
        examplesSection.classList.add('hidden');
    }
}

function createPromptIdeas() {
    renderWelcomeGreeting();
    const container = document.getElementById('promptIdeasContainer');
    if (!container) {
        hidePromptExamplesSection();
        return null;
    }

    showPromptExamplesSection();
    container.innerHTML = '';
    const promptsContainer = document.createElement('div');
    promptsContainer.className = 'prompt-ideas';
    promptsContainer.id = 'promptIdeas';

    const prompts = [
        {
            title: "Introduce",
            prompt: "Introduce yourself and explain how you can help me."
        },
        {
            title: "Explore",
            prompt: "Explore a dataset for me, such as climate data. Load the data, analyze it, and provide visualizations like time series plots, or bar charts to help me understand the data better."
        },
        {
            title: "Analyze",
            prompt: "Analyze a dataset for me, such as climate data. Perform statistical analyses and calculate trends, then show me visualizations and your interpretation."
        },
        {
            title: "Create",
            prompt: "Create a web page for me to view the El Niño-Southern Oscillation index as a time series. Include background information and an interactive map showing locations of common ENSO indices. Save the web page so that I can open it here."
        },
        {
            title: "Brainstorm",
            prompt: "Help me brainstorm research ideas using an available dataset such as about El Niño. Suggest interesting questions, guide me through the initial analysis, and create visualizations to support the findings."
        },
    ];

    prompts.forEach(prompt => {
        const button = document.createElement('button');
        button.className = 'prompt-button';
        button.textContent = prompt.title;
        button.addEventListener('click', () => {
            messageInput.value = prompt.prompt;
            sendRequest();
            hidePromptIdeas();
        });
        promptsContainer.appendChild(button);
    });

    container.appendChild(promptsContainer);
    return promptsContainer;
}

function showPromptIdeas() {
    const existingIdeas = document.getElementById('promptIdeas');
    if (promptIdeasVisible && existingIdeas) {
        renderWelcomeGreeting();
        showPromptExamplesSection();
        return;
    }

    if (existingIdeas) existingIdeas.remove();

    if (createPromptIdeas()) {
        promptIdeasVisible = true;
    }
}

function hidePromptIdeas() {
    const container = document.getElementById('promptIdeasContainer');
    if (container) {
        container.innerHTML = '';
    }
    promptIdeasVisible = false;
    hideWelcomeSection();
    hidePromptExamplesSection();
}

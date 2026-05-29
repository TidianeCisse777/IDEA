// message-renderer.js — rendu des messages, math, highlights, indicateurs de travail

//// Math formatting helpers

function protectMath(text) {
  const store = [];

  const protect = (regex) => (src) =>
    src.replace(regex, (m) => {
      const key = `@@MATH${store.length}@@`;
      store.push(m);
      return key;
    });

  let out = protect(/\$\$([\s\S]*?)\$\$/g)(text);
  out = protect(/\\\[([\s\S]*?)\\\]/g)(out);
  out = protect(/(?<!\$)\$([^\n]+?)\$(?!\$)/g)(out);
  out = protect(/\\\(([^\n]+?)\\\)/g)(out);

  return { text: out, store };
}

function restoreMath(html, store) {
  // Use a function replacer so `$$` in math content is not interpreted as
  // String.replace's literal-$ escape.
  return store.reduce((acc, m, i) => acc.replace(`@@MATH${i}@@`, () => m), html);
}

function countUnescapedSequence(text, sequence) {
  if (!text || !sequence) return 0;
  let count = 0;
  let index = text.indexOf(sequence);
  while (index !== -1) {
    let backslashCount = 0;
    let cursor = index - 1;
    while (cursor >= 0 && text[cursor] === '\\') {
      backslashCount += 1;
      cursor -= 1;
    }
    if (backslashCount % 2 === 0) {
      count += 1;
    }
    index = text.indexOf(sequence, index + sequence.length);
  }
  return count;
}

function hasBalancedMath(s) {
  const dollars = countUnescapedSequence(s, '$$') % 2 === 0;
  const lb = (s.match(/\\\[/g) || []).length;
  const rb = (s.match(/\\\]/g) || []).length;
  const lp = (s.match(/\\\(/g) || []).length;
  const rp = (s.match(/\\\)/g) || []).length;
  return dollars && lb === rb && lp === rp;
}

function typeset(el) {
  if (!el) return Promise.resolve();
  if (!window.MathJax) return Promise.resolve();
  if (MathJax.startup && MathJax.startup.promise) {
    return MathJax.startup.promise.then(() => MathJax.typesetPromise([el]));
  }
  if (MathJax.typesetPromise) {
    return MathJax.typesetPromise([el]);
  }
  return Promise.resolve();
}

function hasMathDelimiters(s) {
  return /\$\$|\\\[|\\\]|(?<!\$)\$[^\n]+?\$(?!\$)|\\\([^\n]+?\\\)/.test(s);
}

let __mathQueue = Promise.resolve();

function prismHighlightUnder(el) {
  if (!el || !window.Prism) return;
  Prism.highlightAllUnder(el);
}

//// Utility functions

function generateId(id_type) {
    return id_type + '-' + Math.random().toString(36).substr(2, 9);
}

function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;',
    };
    return text.replace(/[&<>"']/g, function(m) { return map[m]; });
}

function formatAttachmentLabel(count) {
    return count === 1 ? 'File' : 'Files';
}

function extractAttachmentInfoFromContent(content) {
    if (typeof content !== 'string') return null;
    const lines = content.split('\n');
    for (let i = 0; i < lines.length; i++) {
        const trimmed = lines[i].trim();
        const match = trimmed.match(/^(?:\*\*)?(File|Files):(?:\*\*)?\s*(.+)$/i);
        if (match && i === 0) {
            const remaining = [...lines.slice(0, i), ...lines.slice(i + 1)].join('\n').trim();
            return {
                label: match[1].toLowerCase() === 'file' ? 'File' : 'Files',
                names: match[2].trim(),
                remaining
            };
        }
    }
    return null;
}

//// Chat display helpers

function scrollToBottom() {
    chatDisplay.scrollTop = chatDisplay.scrollHeight;
}

function showWorkingIndicator() {
    if (workingIndicatorId) {
        return workingIndicatorId;
    }

    workingIndicatorId = generateId('thinking');

    const messageElement = document.createElement('div');
    messageElement.classList.add('message', 'assistant', 'thinking');
    messageElement.setAttribute('data-id', workingIndicatorId);

    const contentElement = document.createElement('div');
    contentElement.classList.add('content');
    contentElement.innerHTML = `
        <div class="thinking-content" role="status" aria-live="polite">
            <span class="thinking-spinner" aria-hidden="true"></span>
            <span class="thinking-label">Thinking</span>
            <span class="thinking-ellipsis" aria-hidden="true">
                <span></span><span></span><span></span>
            </span>
        </div>
    `;

    messageElement.appendChild(contentElement);
    chatDisplay.appendChild(messageElement);
    scrollToBottom();

    return workingIndicatorId;
}

function removeWorkingIndicator() {
    if (!workingIndicatorId) return;

    const indicator = chatDisplay.querySelector(`.message[data-id="${workingIndicatorId}"]`);
    if (indicator) {
        indicator.remove();
    }

    workingIndicatorId = null;
}

function addCopyButtons(root) {
    const scope = root instanceof Element ? root : document;
    const codeBlocks = scope.querySelectorAll('pre code');

    codeBlocks.forEach((codeBlock) => {
        const pre = codeBlock.parentElement;
        if (!pre) return;

        if (pre.querySelector('.copy-button')) return;

        const button = document.createElement('button');
        button.classList.add('copy-button');
        button.type = 'button';
        button.innerText = 'Copy';
        pre.appendChild(button);

        button.addEventListener('click', () => {
            const code = codeBlock.innerText;
            navigator.clipboard.writeText(code).then(() => {
                button.innerText = 'Copied!';
                setTimeout(() => {
                    button.innerText = 'Copy';
                }, 2000);
            }).catch((err) => {
                console.error('Failed to copy code: ', err);
                button.innerText = 'Error';
                setTimeout(() => {
                    button.innerText = 'Copy';
                }, 2000);
            });
        });
    });
}

//// Message appending

function appendMessage(message, options = {}) {
    const { persist = true } = options;
    const messageElement = document.createElement('div');
    messageElement.classList.add('message', message.role);
    if (message.id) {
        messageElement.setAttribute('data-id', message.id);
    }

    const contentElement = document.createElement('div');
    contentElement.classList.add('content');
    contentElement.setAttribute('data-type', message.type);
    if (message.role === 'user' && message.type === 'message') {
        const userContentWrapper = document.createElement('div');
        userContentWrapper.classList.add('user-message-wrapper');

        let attachmentNames = null;
        let textSource = typeof message.userText === 'string' ? message.userText : null;
        let parsedContentAttachments = null;

        if (Array.isArray(message.attachments) && message.attachments.length > 0) {
            attachmentLabel = formatAttachmentLabel(message.attachments.length);
            attachmentNames = message.attachments.map(att => att.name).join(', ');
        } else if (typeof message.content === 'string') {
            parsedContentAttachments = extractAttachmentInfoFromContent(message.content);
            if (parsedContentAttachments) {
                attachmentLabel = parsedContentAttachments.label || null;
                attachmentNames = parsedContentAttachments.names;
                if (textSource === null) {
                    textSource = parsedContentAttachments.remaining;
                }
            }
        }

        const fallbackText = parsedContentAttachments ? parsedContentAttachments.remaining : (message.content || '');
        const textToShow = (textSource !== null ? textSource : fallbackText || '').trim();
        if (textToShow) {
            const textBlock = document.createElement('div');
            textBlock.textContent = textToShow;
            userContentWrapper.appendChild(textBlock);
        }

        if (attachmentNames) {
            const attachmentLine = document.createElement('div');
            attachmentLine.className = 'user-attachment-line';
            const fallbackCount = (attachmentNames.match(/,/g) || []).length + 1;
            const label = attachmentLabel || formatAttachmentLabel(fallbackCount);
            attachmentLine.innerHTML = `<strong>${label}:</strong> ${escapeHtml(attachmentNames)}`;
            userContentWrapper.appendChild(attachmentLine);
        }

        contentElement.appendChild(userContentWrapper);
    } else if (message.type === 'image' && message.format === 'path') {
        const imageSrc = escapeHtml(message.content || '');
        const imageAlt = escapeHtml(message.filename || 'Uploaded image');
        contentElement.innerHTML = `<img src="${imageSrc}" alt="${imageAlt}" class="uploaded-image-preview">`;
    } else if (message.type === 'file') {
        const displayName = escapeHtml(message.filename || message.name || message.content || 'Attachment');
        const filePath = escapeHtml(message.content || '');
        contentElement.classList.add('file-attachment');
        contentElement.innerHTML = `
            <span class="material-icons attachment-icon">attach_file</span>
            <div class="attachment-details">
                <span class="attachment-name">${displayName}</span>
                <span class="attachment-path">${filePath}</span>
            </div>
        `;
    } else if (message.type === 'console') {
        contentElement.innerHTML = '<pre><code></code></pre>';
        messageElement.classList.add('console-output-message');
        contentElement.setAttribute('aria-hidden', 'true');
    } else {
        contentElement.textContent = message.content;
    }

    if (message.format === 'tool_status') {
        messageElement.classList.add('tool-status-message');
        contentElement.classList.add('tool-status-content');
    }

    messageElement.appendChild(contentElement);

    const skipTypes = ['console', 'confirmation', 'action_button', 'tool_status'];
    const isTextMsg = !skipTypes.includes(message.type) && message.format !== 'tool_status';
    if (isTextMsg && (message.role === 'assistant' || message.role === 'user')) {
        const actions = document.createElement('div');
        actions.className = 'message-actions';

        const copyBtn = document.createElement('button');
        copyBtn.className = 'message-action-btn';
        copyBtn.title = 'Copier';
        copyBtn.innerHTML = '<span class="material-icons" style="font-size:16px">content_copy</span>';
        copyBtn.addEventListener('click', () => {
            const text = contentElement.innerText || contentElement.textContent || '';
            navigator.clipboard.writeText(text).then(() => {
                copyBtn.classList.add('copy-done');
                copyBtn.innerHTML = '<span class="material-icons" style="font-size:16px">check</span>';
                setTimeout(() => {
                    copyBtn.classList.remove('copy-done');
                    copyBtn.innerHTML = '<span class="material-icons" style="font-size:16px">content_copy</span>';
                }, 1800);
            });
        });
        actions.appendChild(copyBtn);

        if (message.role === 'assistant') {
            const thumbUp = document.createElement('button');
            thumbUp.className = 'message-action-btn';
            thumbUp.title = 'Bonne réponse';
            thumbUp.innerHTML = '<span class="material-icons" style="font-size:16px">thumb_up</span>';

            const thumbDown = document.createElement('button');
            thumbDown.className = 'message-action-btn';
            thumbDown.title = 'Mauvaise réponse';
            thumbDown.innerHTML = '<span class="material-icons" style="font-size:16px">thumb_down</span>';

            [thumbUp, thumbDown].forEach((btn, idx) => {
                btn.addEventListener('click', () => {
                    thumbUp.classList.remove('active-thumb');
                    thumbDown.classList.remove('active-thumb');
                    btn.classList.add('active-thumb');
                });
            });

            actions.appendChild(thumbUp);
            actions.appendChild(thumbDown);
        }

        messageElement.appendChild(actions);
    }

    chatDisplay.appendChild(messageElement);
    chatDisplay.scrollTop = chatDisplay.scrollHeight;
    handleStdoutTrackingOnMessageStart(message);

    if (persist && conversationManager && message.role === 'user' && message.content) {
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
            if (frontendId && saved && saved.id && frontendId !== saved.id) {
                const el = document.querySelector(`[data-id="${frontendId}"]`);
                if (el) el.setAttribute('data-id', saved.id);
                message.id = saved.id;
            }
        }).catch(() => {});
    }
}

function appendExternalMessage({ role = 'assistant', content = '', type = 'message', format = null, recipient = null }) {
    if (!content || !chatDisplay) return;
    const id = generateId('msg');
    const message = {
        id,
        role,
        content,
        type,
        format,
        recipient,
        isComplete: true,
    };
    messages.push(message);
    appendMessage(message);
    try {
        updateMessageContent(id, content);
    } catch (err) {
        console.warn('Unable to render external message:', err);
    }

    if (conversationManager) {
        const validTypes = ['message', 'code', 'image', 'console', 'file', 'confirmation'];
        const messageType = validTypes.includes(type) ? type : 'message';
        conversationManager
            .addMessage(role, content, messageType, format, recipient)
            .catch((error) => {
                console.error('Failed to persist external message:', error);
            });
    }
}

window.appendExternalMessage = appendExternalMessage;

function handleActiveLineChunk(content) {
    if (!activeLineCodeId) {
        activeLineCodeId = lastExecutableCodeId || pendingConsoleParentId || null;
    }
    if (!activeLineCodeId) return;
    if (content) {
        isActiveLineRunning = true;
        renderActiveLineSpinner();
    } else {
        isActiveLineRunning = false;
        removeActiveLineSpinner();
        activeLineCodeId = null;
    }
}

function updateMessageContent(id, content) {
    try {
        const messageElement = chatDisplay.querySelector(`.message[data-id="${id}"]`);
        if (!messageElement) {
            throw new Error(`Message element with ID ${id} not found`);
        }

        const message = messages.find(msg => msg.id === id);
        if (!message) {
            throw new Error(`Message data with ID ${id} not found`);
        }

        const contentDiv = messageElement.querySelector('.content');
        if (!contentDiv) {
            throw new Error('Content div not found');
        }

        if (message.type === 'console') {
            if (isTelemetryConsoleMessage(message)) {
                return;
            }
            const pre = contentDiv.querySelector('pre code') || (() => {
                contentDiv.innerHTML = '<pre><code></code></pre>';
                return contentDiv.querySelector('pre code');
            })();
            if (pre) {
                pre.textContent = message.content || '';
            }
            const parent = contentDiv.parentElement;
            if (parent) {
                parent.classList.add('console-output-message');
                if (message.associatedCodeId) {
                    parent.setAttribute('data-associated-code-id', message.associatedCodeId);
                    refreshStdoutPanel(message.associatedCodeId, { autoScroll: true });
                }
            }
            contentDiv.setAttribute('aria-hidden', 'true');
            return;
        }

        if (message.format === 'tool_status') {
            messageElement.classList.add('tool-status-message');
            contentDiv.classList.add('tool-status-content');
            const isDone = !!message.isComplete;
            const text = (content && content.trim()) ? content : message.content || '';
            const statusHtml = `
                <div class="tool-status">
                    <span class="${isDone ? 'tool-check' : 'thinking-spinner'}" aria-hidden="true"></span>
                    <span class="tool-status-text">${escapeHtml(text)}</span>
                </div>
            `;
            contentDiv.innerHTML = statusHtml;
            return;
        } else if (message.type === 'message') {
            let raw = content;

            const { text: shielded, store } = protectMath(raw);

            if (!hasBalancedMath(raw)) {
            contentDiv.textContent = raw;
            return;
            }

            const parsedMarkdown = marked.parse(shielded);
            const htmlWithMath = restoreMath(parsedMarkdown, store);
            contentDiv.innerHTML = DOMPurify.sanitize(htmlWithMath);

            prismHighlightUnder(contentDiv);

            const shouldTypeset = (message.isComplete !== false) && hasMathDelimiters(raw);
            if (shouldTypeset && !message.__mathTypeset) {
                message.__mathTypeset = true;
                typeset(contentDiv);
            }
        } else if (message.type === 'image') {
            if (message.format && message.format.startsWith('base64.')) {
                const mime = message.format.replace('base64.', 'image/');
                if (message.isComplete) {
                    contentDiv.innerHTML =
                        `<img src="data:${mime};base64,${content}" alt="Image">`;
                } else {
                    contentDiv.innerHTML = `<div class="image-placeholder"> Generating image… </div>`;
                }
            } else if (message.format === 'path') {
                const img = document.createElement('img');
                img.src = content;
                img.alt = 'Image';
                contentDiv.appendChild(img);
            }
        } else if (message.type === 'code') {
            const preservedStdoutState = captureStdoutPanelState(message.id);
            if (message.format === "html") {
                contentDiv.innerHTML = DOMPurify.sanitize(content);
            } else {
                let codeBlock = contentDiv.querySelector('pre code');
                if (!codeBlock) {
                    contentDiv.innerHTML = `<pre><code class="language-${message.format || ''}"></code></pre>`;
                    codeBlock = contentDiv.querySelector('pre code');
                } else {
                    codeBlock.className = `language-${message.format || ''}`;
                }

                if (codeBlock) {
                    codeBlock.textContent = content;
                    Prism.highlightElement(codeBlock);
                }
                addCopyButtons();
                ensureStdoutElements(message.id);
                updateStdoutAvailability(message.id);
                restoreStdoutPanelState(message.id, preservedStdoutState);
                if (isActiveLineRunning && activeLineCodeId === message.id) {
                    renderActiveLineSpinner();
                }
            }
        } else if (message.type === 'file') {
            const a = document.createElement('a');
            a.href = content;
            a.download = '';
            a.textContent = 'Download File';
            contentDiv.appendChild(a);
        }
    } catch (error) {
        handleError(error, 'Failed to update message content');
    }
}

function appendSystemMessage(message) {
    const id = generateId('msg');
    const systemMessage = {
        id: id,
        role: 'system',
        type: 'system',
        content: message
    };
    messages.push(systemMessage);

    const messageElement = document.createElement('div');
    messageElement.classList.add('message', 'system');
    messageElement.setAttribute('data-id', id);

    const content = document.createElement('div');
    content.classList.add('content');
    const parsedMarkdown = marked.parse(message);
    content.innerHTML = DOMPurify.sanitize(parsedMarkdown);
    content.querySelectorAll('pre code').forEach((block) => {
        Prism.highlightElement(block);
    });

    messageElement.appendChild(content);
    chatDisplay.appendChild(messageElement);
    chatDisplay.scrollTop = chatDisplay.scrollHeight;
}

function hydrateChatWithMessages(rawMessages, { persist = false } = {}) {
    if (!Array.isArray(rawMessages)) {
        return;
    }

    messages = [];
    chatDisplay.innerHTML = '';
    promptIdeasVisible = false;
    resetStdoutState();
    if (!Array.isArray(rawMessages) || rawMessages.length === 0) {
        showPromptIdeas();
    } else {
        hideWelcomeSection();
    }

    rawMessages.forEach(rawMessage => {
        if (!rawMessage) {
            return;
        }

        if (rawMessage.type === 'action_button') {
            if (sessionMode === 'plan') {
                let parsed = {};
                try { parsed = JSON.parse(rawMessage.content || '{}'); } catch (_) {}
                handleActionButtonChunk(
                    { action: parsed.action || 'validate_plan', label: parsed.label },
                    { persist: false }
                );
            }
            return;
        }

        const normalized = normalizeStdStreamMessage({ ...rawMessage });
        if (normalized.type === 'console' && isTelemetryConsoleMessage(normalized)) {
            return;
        }

        if (!normalized.id) {
            normalized.id = generateId('msg');
        }

        normalized.isComplete = true;
        normalized.content = normalized.content || '';

        messages.push(normalized);
        appendMessage(normalized, { persist });
        updateMessageContent(normalized.id, normalized.content);
    });

    scrollToBottom();
}

window.hydrateChatWithMessages = hydrateChatWithMessages;

if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        protectMath,
        restoreMath,
        countUnescapedSequence,
        hasBalancedMath,
        hasMathDelimiters,
        generateId,
        escapeHtml,
        formatAttachmentLabel,
        extractAttachmentInfoFromContent,
    };
}

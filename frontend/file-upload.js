// file-upload.js — gestion des uploads de fichiers (queue, render, remove, send)

async function handleFiles(files) {
    if (!files || files.length === 0) return;

    hidePromptIdeas();
    if (progressBar) {
        progressBar.style.display = 'block';
    }
    for (const file of files) {
        try {
            const response = await uploadFile(file, progressElement);
            queuePendingUpload(file, response);
        } catch (error) {
            appendSystemMessage(`Error uploading ${file.name}: ${error.message}`);
        }
    }
    if (progressBar) {
        progressBar.style.display = 'none';
    }
}

function queuePendingUpload(file, uploadResponse = {}) {
    const storedName = uploadResponse.filename || uploadResponse.name || file.name;
    const storagePath = uploadResponse.path || storedName;
    const isImage = (file.type || '').startsWith('image/');

    const attachment = {
        id: generateId('upload'),
        name: file.name,
        storedName,
        path: storagePath,
        url: uploadResponse.url || null,
        sessionId,
        size: file.size,
        mimeType: file.type,
        messageType: isImage ? 'image' : 'file',
        messageFormat: isImage ? 'path' : null
    };

    pendingUploads.push(attachment);
    renderPendingUploads();
    window.conversationUI?.refreshConversationCsvSidebar?.();
}

function renderPendingUploads() {
    const uploadedFiles = document.getElementById('uploadedFiles');
    if (!uploadedFiles) return;

    uploadedFiles.innerHTML = '';

    if (pendingUploads.length === 0) {
        uploadedFiles.classList.remove('active');
        return;
    }

    uploadedFiles.classList.add('active');

    pendingUploads.forEach((attachment) => {
        const fileElement = document.createElement('span');
        fileElement.className = 'attached-file';

        const nameSpan = document.createElement('span');
        nameSpan.className = 'attached-file-name';
        nameSpan.textContent = attachment.name;
        fileElement.appendChild(nameSpan);

        const removeButton = document.createElement('button');
        removeButton.className = 'remove-attachment';
        removeButton.setAttribute('aria-label', `Remove ${attachment.name}`);
        removeButton.textContent = '×';
        removeButton.addEventListener('click', () => removePendingAttachment(attachment.id));
        fileElement.appendChild(removeButton);

        uploadedFiles.appendChild(fileElement);
    });
}

async function removePendingAttachment(attachmentId) {
    const attachment = pendingUploads.find(att => att.id === attachmentId);
    if (!attachment) return;

    try {
        const response = await fetch(`${config.getEndpoints().files}/${encodeURIComponent(attachment.storedName)}`, {
            method: 'DELETE',
            headers: {
                'X-Session-Id': sessionId,
                ...getAuthHeaders()
            }
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || 'Delete failed');
        }

        pendingUploads = pendingUploads.filter(att => att.id !== attachmentId);
        renderPendingUploads();
        window.conversationUI?.refreshConversationCsvSidebar?.();
    } catch (error) {
        appendSystemMessage(`Error deleting file: ${error.message}`);
    }
}

function buildAttachmentInstruction(attachments = []) {
    if (!attachments.length) return '';
    const activeSessionId = globalThis.sessionId || (typeof sessionId !== 'undefined' ? sessionId : '');
    const basePath = `./static/{user_id}/${activeSessionId}/uploads`;
    const lines = attachments.map(att => {
        const relPath = att.path || att.storedName || att.name;
        const mimeType = att.mimeType ? ` (${att.mimeType})` : '';
        return `- ${att.name}${mimeType}${relPath ? ` | relative path: ${relPath}` : ''}`;
    }).join('\n');
    return `Files uploaded in this message:\nSession ID: ${activeSessionId}\nBase path: ${basePath}\n${lines}\nUse these paths when referencing the uploaded files.\nSession rule: compare each filename against filenames already present in this session. If a filename already exists, skip its inspection, explicitly say it is already present, and inspect only the new filenames.`;
}

async function uploadFile(file, progressElement) {
    try {
        if (!file) {
            throw new Error('No file provided');
        }

        const formData = new FormData();
        formData.append('file', file);

        const response = await fetch(config.getEndpoints().upload, {
            method: 'POST',
            headers: {
                'X-Session-Id': sessionId,
                ...getAuthHeaders()
            },
            body: formData
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || `Upload failed with status ${response.status}`);
        }

        const data = await response.json();
        return data;

    } catch (error) {
        handleError(error, `Failed to upload ${file.name}`);
        throw error;
    }
}

function updateFilesList() {
    renderPendingUploads();
}

function initializeFileUpload() {
    const uploadButton = document.getElementById('uploadButton');
    const fileInput = document.getElementById('fileUpload');

    uploadButton.addEventListener('click', () => fileInput.click());

    fileInput.addEventListener('change', async () => {
        await handleFiles(fileInput.files);
        fileInput.value = '';
    });

    // Paste handler for screenshots
    document.addEventListener('paste', async (event) => {
        const items = event.clipboardData?.items;
        if (!items) return;

        for (const item of items) {
            if (item.type.startsWith('image')) {
                const originalFile = item.getAsFile();
                if (originalFile) {
                    const extension = originalFile.type.split('/')[1] || 'png';
                    const uniqueName = `pasted-${Date.now()}-${Math.floor(Math.random() * 1000)}.${extension}`;
                    const renamedFile = new File([originalFile], uniqueName, { type: originalFile.type });

                    if (progressBar) {
                        progressBar.style.display = 'block';
                    }
                    try {
                        const response = await uploadFile(renamedFile, progressElement);
                        queuePendingUpload(renamedFile, response);
                    } catch (error) {
                        appendSystemMessage(`Error uploading pasted image: ${error.message}`);
                    } finally {
                        if (progressBar) {
                            progressBar.style.display = 'none';
                        }
                    }
                }
            }
        }
    });

    updateFilesList();
    window.conversationUI?.refreshConversationCsvSidebar?.();
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        buildAttachmentInstruction,
    };
}

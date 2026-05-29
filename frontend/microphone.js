// microphone.js — préchauffe le micro et gère la dictée vocale

let micStream = null;

async function warmUpMicrophone() {
    try {
        micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
        console.warn("Microphone warm-up failed or was denied:", err);
    }
}

function initializeMicrophone() {
    const micButton = document.getElementById('micButton');
    if (!micButton) return;

    const micIcon = micButton.querySelector('i');
    let mediaRecorder;
    let audioChunks = [];
    let isRecording = false;

    micButton.addEventListener('click', async () => {
        if (!isRecording) {
            await startRecording();
        } else {
            stopRecording();
        }
    });

    async function startRecording() {
        try {
            const stream = micStream || await navigator.mediaDevices.getUserMedia({ audio: true });
            mediaRecorder = new MediaRecorder(stream, {
                mimeType: 'audio/webm;codecs=opus'
            });

            audioChunks = [];

            mediaRecorder.ondataavailable = (event) => {
                if (event.data.size > 0) audioChunks.push(event.data);
            };

            mediaRecorder.onstop = async () => {
                const audioBlob = new Blob(audioChunks, { type: mediaRecorder.mimeType });
                await uploadAudioBlob(audioBlob);
            };

            mediaRecorder.start();
            micButton.classList.add('recording');
            micIcon.textContent = "stop";
            isRecording = true;
        } catch (err) {
            console.error("Microphone error:", err);
            appendSystemMessage("Microphone not available or permission denied.");
            micButton.classList.remove('recording');
            micIcon.textContent = "mic";
            isRecording = false;
        }
    }

    function stopRecording() {
        if (mediaRecorder && mediaRecorder.state !== "inactive") {
            mediaRecorder.stop();
        }
        micButton.classList.remove('recording');
        micIcon.textContent = "mic";
        isRecording = false;
    }

    async function uploadAudioBlob(blob) {
        const formData = new FormData();
        formData.append('file', blob, 'recording.webm');

        try {
            const response = await fetch(config.getEndpoints().transcribe, {
                method: 'POST',
                body: formData
            });

            if (response.ok) {
                const data = await response.json();
                messageInput.value = data.text;
            } else {
                appendSystemMessage("Transcription failed.");
            }
        } catch (err) {
            console.error("Upload error:", err);
            appendSystemMessage("Error sending audio for transcription.");
        }
    }
}

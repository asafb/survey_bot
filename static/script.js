// static/script.js




// --- Session ID Management ---
function getSessionId() {
    let sessionId = sessionStorage.getItem('chatSessionId');
    if (!sessionId) {
        sessionId = crypto.randomUUID(); // Generate a new unique ID
        sessionStorage.setItem('chatSessionId', sessionId);
        console.log("New session started:", sessionId); // For debugging
    }
    return sessionId;
}

// Get or create session ID when script loads
const currentSessionId = getSessionId();

// Add event listeners (keep as before)
document.getElementById('chatInput').addEventListener('keydown', handleKeyPress);
document.querySelector('.send-button').addEventListener('click', sendMessage);



function handleKeyPress(event) {
  // If the user presses Enter (without Shift), send the message
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault(); // Prevent newline in textarea
    sendMessage();
  }
}

async function sendMessage() {
    const inputElem = document.getElementById("chatInput");
    const sendButton = document.querySelector(".send-button");
    const userMessage = inputElem.value.trim();

    if (!userMessage || sendButton.disabled) return;

    appendMessage("user", userMessage);
    inputElem.value = "";
    inputElem.style.height = '';

    const thinkingDiv = appendMessage("bot", "Thinking", true);
    thinkingDiv.id = "thinkingIndicator";
    thinkingDiv.classList.add("thinking-indicator");

    inputElem.disabled = true;
    sendButton.disabled = true;

    let responseData = null;

    try {
        const response = await fetch("/generate_chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            // *** Add session_id to the request body ***
            body: JSON.stringify({
                prompt: userMessage,
                session_id: currentSessionId // Send the current session ID
            })
        });

        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`HTTP error ${response.status}: ${errorText || response.statusText}`);
        }
        responseData = await response.json();

    } catch (error) {
        console.error("Fetch Error:", error);
        responseData = { response: `Sorry, an error occurred: ${error.message}` };
    } finally {
        const indicator = document.getElementById("thinkingIndicator");
        if (indicator) indicator.remove();

        if (responseData?.response) { // Optional chaining
             appendMessage("bot", responseData.response);
        } else if (!responseData) {
             appendMessage("bot", "An unexpected network or server error occurred.");
        }

        inputElem.disabled = false;
        sendButton.disabled = false;
        inputElem.focus();
    }
}
// Modify appendMessage slightly to return the created element
// and handle the temporary indicator text/class
function appendMessage(sender, text, isThinking = false) {
    const chatLog = document.getElementById("chatLog");
    const msgDiv = document.createElement("div");
    msgDiv.classList.add("message");

    if (sender === "user") {
        msgDiv.classList.add("user-message");
        msgDiv.textContent = text;
    } else {
        msgDiv.classList.add("bot-message");
        if (isThinking) {
            msgDiv.setAttribute('aria-label', 'Bot is thinking');
            msgDiv.classList.add("thinking-indicator");
        } else {
            msgDiv.textContent = text;
        }
    }
    chatLog.appendChild(msgDiv);
    requestAnimationFrame(() => {
        if (chatLog.scrollHeight - chatLog.scrollTop <= chatLog.clientHeight + 150) {
            chatLog.scrollTo({ top: chatLog.scrollHeight, behavior: 'smooth' });
        }
    });
    return msgDiv;
}

   

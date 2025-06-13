// Define these once, outside any function, or at the top of your script block in Qualtrics

var chatbotHandshakeState = {}; // Stores { qid: { hasLoaded: false, isReadyForConfig: false, iframeRef: null, config: null } }
if (typeof window.chatbotInitializedForQID === 'undefined') { // Ensure global initialization only once
    window.chatbotInitializedForQID = {};
    console.log("[QUALTRICS GLOBAL] window.chatbotInitializedForQID created for handshake.");
}

function trySendInitConfigForQIDGlobal(currentQID) {
    const state = chatbotHandshakeState[currentQID];
    // chatbotOrigin is globally available from line 2
    // window.chatbotInitializedForQID is globally available
    if (state && state.hasLoaded && state.isReadyForConfig && !window.chatbotInitializedForQID[currentQID]) {
        if (state.iframeRef && state.iframeRef.contentWindow && state.config) {
            console.log("[QUALTRICS QID: " + currentQID + "] Handshake complete. Sending 'init_chatbot'. Config:", state.config);
            state.iframeRef.contentWindow.postMessage({
                type: 'init_chatbot',
                config: state.config
            }, chatbotOrigin); // Assumes chatbotOrigin is in global scope
            window.chatbotInitializedForQID[currentQID] = true;
            console.log("[QUALTRICS QID: " + currentQID + "] 'init_chatbot' sent via handshake and flag set.");
        } else {
            console.warn(`[QUALTRICS QID: ${currentQID}] Handshake complete, but missing critical refs for sending 'init_chatbot'. iframeRef: ${!!state.iframeRef}, contentWindow: ${!!(state.iframeRef && state.iframeRef.contentWindow)}, config: ${!!state.config}`);
        }
    } else if (state) {
        // console.log(`[QUALTRICS QID: ${currentQID}] trySendInitConfigForQIDGlobal: Not ready or already sent. Loaded: ${state.hasLoaded}, ReadyForConfig: ${state.isReadyForConfig}, Initialized: ${window.chatbotInitializedForQID[currentQID]}`);
    } else {
        // console.log(`[QUALTRICS QID: ${currentQID}] trySendInitConfigForQIDGlobal: No state found for ${currentQID}.`);
    }
}

// Define these once, outside any function, or at the top of your script block in Qualtrics
const chatbotAppUrl = 'https://qualtrics-chatbot-927925638706.us-west2.run.app';
const chatbotOrigin = new URL(chatbotAppUrl).origin;

Qualtrics.SurveyEngine.addOnload(function() {
    var qid = this.questionId;
    var questionThis = this; // Store 'this' for use in listeners and Qualtrics API calls
    console.log("[QUALTRICS QID: " + qid + "] addOnload triggered.");

    // Initialize handshake state for this QID
    chatbotHandshakeState[qid] = {
        hasLoaded: false,
        isReadyForConfig: false,
        iframeRef: null, // Will be set below
        config: null // Will be set below
    };
    console.log("[QUALTRICS QID: " + qid + "] Initialized chatbotHandshakeState.");

    // The window.chatbotInitializedForQID is already initialized globally before this script block.

    const chatbotConfig = {
        qid: qid, // Add qid to the config
        initialQuestion: "What are your main pain points with this product?",
        promptParams: { /* ... your params ... */ },
        uiConfig: { /* ... your UI config ... */ },
        qualtricsParentOrigin: window.location.origin
    };
    console.log("[QUALTRICS QID: " + qid + "] Chatbot config prepared:", chatbotConfig);
    if (chatbotHandshakeState[qid]) chatbotHandshakeState[qid].config = chatbotConfig;

    var iframeContainerId = 'iframeContainer-' + qid;
    var iframeContainer = document.getElementById(iframeContainerId);
    var iframe; // Declare iframe here

    if (!iframeContainer) {
        console.log("[QUALTRICS QID: " + qid + "] Iframe container '" + iframeContainerId + "' not found, creating new one.");
        iframeContainer = document.createElement('div');
        iframeContainer.id = iframeContainerId;
        iframeContainer.style.width = '100%';
        iframeContainer.style.height = '600px'; // Or your desired height
        questionThis.getQuestionContainer().appendChild(iframeContainer);

        iframe = document.createElement('iframe');
        iframeContainer.appendChild(iframe);
        console.log("[QUALTRICS QID: " + qid + "] New iframe created and appended.");
    } else {
        console.log("[QUALTRICS QID: " + qid + "] Iframe container '" + iframeContainerId + "' found.");
        iframe = iframeContainer.querySelector('iframe');
        if (!iframe) {
            console.log("[QUALTRICS QID: " + qid + "] No iframe inside existing container. Creating and appending iframe.");
            iframeContainer.innerHTML = ''; // Clear if there was other stale content
            iframe = document.createElement('iframe');
            iframeContainer.appendChild(iframe);
        } else {
            console.log("[QUALTRICS QID: " + qid + "] Iframe already exists in container. Current SRC: " + iframe.src);
        }
    }

    if (iframe) {
        if (chatbotHandshakeState[qid]) chatbotHandshakeState[qid].iframeRef = iframe;
        iframe.style.width = '100%';
        iframe.style.height = '100%';
        iframe.style.border = 'none';
        iframe.setAttribute('allow', 'microphone');

        const isSrcAlreadySet = iframe.getAttribute('data-chatbot-src-set') === 'true';
        const currentSrcIsCorrect = iframe.src === chatbotAppUrl;

        if (isSrcAlreadySet && currentSrcIsCorrect) {
            console.log("[QUALTRICS QID: " + qid + "] Iframe already correctly set up with data-chatbot-src-set='true' and correct src. Skipping src/onload re-assignment.");
            // Ensure handshake state reflects it's loaded, as iframe.onload won't fire again for an existing, correct iframe.
            if (chatbotHandshakeState[qid]) {
                chatbotHandshakeState[qid].hasLoaded = true; // Mark as loaded
                // trySendInitConfigForQIDGlobal will handle if it's also readyForConfig
                trySendInitConfigForQIDGlobal(qid);
            }
        } else {
            var needsSrcAndHandlerSetup = true;
            if (isSrcAlreadySet && !currentSrcIsCorrect) {
                console.warn("[QUALTRICS QID: " + qid + "] Iframe had data-chatbot-src-set='true' but SRC ('" + iframe.src + "') is NOT correct ('" + chatbotAppUrl + "'). External modification suspected. Resetting and re-initializing.");
                // Reset handshake flags for this QID as we are about to reload the iframe
                if (chatbotHandshakeState[qid]) {
                    chatbotHandshakeState[qid].hasLoaded = false;
                    chatbotHandshakeState[qid].isReadyForConfig = false;
                }
                window.chatbotInitializedForQID[qid] = false;
                iframe.removeAttribute('data-chatbot-src-set'); // Clear the marker before re-setting src
            } else if (!isSrcAlreadySet && currentSrcIsCorrect) {
                 console.log("[QUALTRICS QID: " + qid + "] Iframe SRC is correct but data-chatbot-src-set attribute not found. Will set attribute and handlers.");
            } else if (iframe.src && iframe.src !== chatbotAppUrl && iframe.src !== 'about:blank') {
                 console.log("[QUALTRICS QID: " + qid + "] Iframe SRC is different ('" + iframe.src + "'), updating to '" + chatbotAppUrl + "'. This will reload the iframe.");
            } else if (!iframe.src || iframe.src === 'about:blank') {
                console.log("[QUALTRICS QID: " + qid + "] Iframe SRC is empty or 'about:blank', setting to '" + chatbotAppUrl + "'.");
            }

            if (needsSrcAndHandlerSetup) {
                iframe.onload = function() {
                    console.log("[QUALTRICS QID: " + qid + "] Iframe (SRC: " + iframe.src + ") 'onload' event fired.");
                    if (chatbotHandshakeState[qid]) {
                        chatbotHandshakeState[qid].hasLoaded = true;
                        console.log("[QUALTRICS QID: " + qid + "] Marked as hasLoaded. Attempting to send init config.");
                        trySendInitConfigForQIDGlobal(qid);
                    } else {
                        console.warn("[QUALTRICS QID: " + qid + "] onload: chatbotHandshakeState not found for qid.");
                    }
                };

                iframe.onerror = function(e) {
                    console.error("[QUALTRICS QID: " + qid + "] Iframe failed to load. SRC: " + (iframe ? iframe.src : 'unknown') + ". Error:", e);
                    if (iframeContainer) {
                        iframeContainer.innerHTML = "<p style='color:red;'>Error: The chat interface could not be loaded. Please contact support.</p>";
                    }
                };

                if (iframe.src !== chatbotAppUrl) {
                    console.log("[QUALTRICS QID: " + qid + "] Setting iframe.src to " + chatbotAppUrl + " and data-chatbot-src-set='true'.");
                    iframe.src = chatbotAppUrl;
                    iframe.setAttribute('data-chatbot-src-set', 'true');
                } else if (!isSrcAlreadySet) {
                    // Src is correct, but attribute wasn't set. Set it now.
                    console.log("[QUALTRICS QID: " + qid + "] SRC was correct, setting data-chatbot-src-set='true'. Onload/onerror handlers also (re)attached.");
                    iframe.setAttribute('data-chatbot-src-set', 'true');
                    // If already loaded and src is correct, but attribute was missing, onload might not fire.
                    // Manually trigger loaded state if document is complete.
                    if (iframe.contentWindow && iframe.contentWindow.document.readyState === 'complete') {
                         console.log("[QUALTRICS QID: " + qid + "] Iframe already loaded with correct SRC (attribute was missing). Manually marking as hasLoaded.");
                         if (chatbotHandshakeState[qid]) {
                            chatbotHandshakeState[qid].hasLoaded = true;
                            trySendInitConfigForQIDGlobal(qid);
                        }
                    }
                }
            }
        }
    } else {
        console.error("[QUALTRICS QID: " + qid + "] Iframe object is null/undefined after setup logic. Cannot attach handlers or set src.");
    }
});

// Store the last received chat data globally so we can access it from different contexts
window.lastReceivedChatData = null;

// Track if embedded data has been set in the current page
window.chatDataSetInCurrentPage = false;

// Function to create or update hidden fields in the Qualtrics form
// This approach uses actual form fields that Qualtrics will submit with the page
function createHiddenQuestionField(qid, fieldName, fieldValue) {
    console.log("[QUALTRICS QID: " + qid + "] Creating hidden field for " + fieldName);
    try {
        // First try to find the question container
        let questionContainer = null;
        
        // First attempt: Try the standard QID format
        questionContainer = document.getElementById("QID" + qid.replace('QID', ''));
        
        // Second attempt: Try the full question container ID
        if (!questionContainer) {
            questionContainer = document.getElementById("QR~" + qid);
        }
        
        // Third attempt: Try to find any Qualtrics question container
        if (!questionContainer) {
            const containers = document.querySelectorAll('.QuestionOuter, .QuestionBody');
            if (containers.length > 0) {
                questionContainer = containers[0];
                console.log("[QUALTRICS QID: " + qid + "] Using generic question container");
            }
        }
        
        if (!questionContainer) {
            console.warn("[QUALTRICS QID: " + qid + "] Could not find question container");
            return false;
        }
        
        // Field IDs/names based on Qualtrics naming convention
        const fieldId = "QR~" + qid + "~" + fieldName;
        const formId = "QR~" + qid;
        
        // Check if we already created this field
        let hiddenInput = document.getElementById(fieldId);
        if (!hiddenInput) {
            // Create a hidden input field 
            hiddenInput = document.createElement('input');
            hiddenInput.type = 'hidden';
            hiddenInput.id = fieldId;
            hiddenInput.name = fieldName;  // Important for Qualtrics to capture it
            hiddenInput.className = 'chatbotDataField';
            
            // Add special attributes to ensure Qualtrics processes this as a form field
            hiddenInput.setAttribute('data-qid', qid);
            hiddenInput.setAttribute('data-runtime-value', 'runtime.Value');
            
            // Create a label for accessibility
            const label = document.createElement('label');
            label.id = fieldName + "-label";
            label.style.display = 'none';
            label.textContent = "Chat Data";
            hiddenInput.setAttribute('aria-labelledby', label.id);
            
            // Append elements to question container
            questionContainer.appendChild(label);
            questionContainer.appendChild(hiddenInput);
            
            // Also create a simple form field with standard ID pattern
            const formField = document.createElement('input');
            formField.type = 'hidden';
            formField.id = formId;
            formField.name = formId;
            formField.value = fieldValue;
            questionContainer.appendChild(formField);
            
            console.log("[QUALTRICS QID: " + qid + "] Created new hidden field: " + fieldId);
        }
        
        // Set the value
        hiddenInput.value = fieldValue;
        
        // Also try to find and update any questions directly in the Qualtrics form
        const formElements = document.querySelectorAll('input[name="' + formId + '"]');
        if (formElements.length > 0) {
            formElements.forEach(function(el) {
                el.value = fieldValue;
            });
        }
        
        return true;
    } catch (e) {
        console.error("[QUALTRICS QID: " + qid + "] Error creating hidden field:", e);
        return false;
    }
}

// Function to save chat data using multiple methods for reliability
function saveChatDataToQualtrics(dataString) {
    console.log("[QUALTRICS GLOBAL] Attempting to save chatData:", dataString);

    if (typeof dataString !== 'string' || dataString.trim() === "") {
        console.warn("[QUALTRICS GLOBAL] Invalid data string received:", dataString);
        return false;
    }

    try {
        // Validate it's proper JSON first
        JSON.parse(dataString);
    } catch (e) {
        console.error("[QUALTRICS GLOBAL] Failed to parse data as JSON. Error:", e);
        return false;
    }

    // Store globally for access in other contexts (like onunload)
    window.lastReceivedChatData = dataString;

    // Store in session storage as a backup
    try {
        if (window.sessionStorage) {
            window.sessionStorage.setItem('qualtricsLastChatData', dataString);
            console.log("[QUALTRICS GLOBAL] Chat data saved to sessionStorage.");
        }
    } catch (storageError) {
        console.warn("[QUALTRICS GLOBAL] Failed to save to sessionStorage:", storageError);
    }

    // Use the official Qualtrics API
    let saveSuccessful = false;
    
    try {
        // Method 1: Standard API
        if (typeof Qualtrics !== 'undefined' && 
            typeof Qualtrics.SurveyEngine !== 'undefined' && 
            typeof Qualtrics.SurveyEngine.setEmbeddedData === 'function') {
            
            console.log("[QUALTRICS GLOBAL] Using Qualtrics.SurveyEngine.setEmbeddedData");
            Qualtrics.SurveyEngine.setEmbeddedData('chatData', dataString);
            saveSuccessful = true;
        }
    } catch (e) {
        console.warn("[QUALTRICS GLOBAL] Error using standard setEmbeddedData:", e);
    }

    // Try using internal Qualtrics registry object
    try {
        if (typeof Qualtrics !== 'undefined' && 
            typeof Qualtrics.SurveyEngine !== 'undefined' && 
            typeof Qualtrics.SurveyEngine.registry !== 'undefined' && 
            Qualtrics.SurveyEngine.registry.qobj) {
            
            console.log("[QUALTRICS GLOBAL] Using Qualtrics.SurveyEngine.registry.qobj.setEDValue");
            // Force the data into the internal registry object
            Qualtrics.SurveyEngine.registry.qobj.setEDValue('chatData', dataString);
            
            // Some versions of Qualtrics might require an explicit save on the registry
            if (typeof Qualtrics.SurveyEngine.registry.save === 'function') {
                console.log("[QUALTRICS GLOBAL] Calling Qualtrics.SurveyEngine.registry.save()");
                Qualtrics.SurveyEngine.registry.save();
            }
            
            saveSuccessful = true;
        }
    } catch (e) {
        console.warn("[QUALTRICS GLOBAL] Error using registry setEDValue:", e);
    }

    // Try to find active question ID for the hidden field
    let activeQID = "";
    try {
        // Method 1: Check all question containers to find active ones
        document.querySelectorAll('.QuestionOuter, .QuestionBody, [id^="QID"]').forEach(function(el) {
            if (el.id && el.id.startsWith('QID') && el.style.display !== 'none') {
                activeQID = el.id;
            }
        });

        // Method 2: Try to find via DOM hierarchy
        if (!activeQID) {
            const iframe = document.querySelector('iframe[src*="qualtrics-chatbot"]');
            if (iframe) {
                // Go up the DOM to find the nearest question container
                let parent = iframe.parentElement;
                while (parent) {
                    if (parent.id && parent.id.startsWith('QID')) {
                        activeQID = parent.id;
                        break;
                    }
                    parent = parent.parentElement;
                }
            }
        }
        
        // 3. Check for QID in various parts of Qualtrics object
        if (!activeQID && typeof Qualtrics !== 'undefined') {
            // Try to get from the registry
            if (Qualtrics.SurveyEngine && 
                Qualtrics.SurveyEngine.registry && 
                Qualtrics.SurveyEngine.registry.qrid) {
                activeQID = Qualtrics.SurveyEngine.registry.qrid;
            } 
            // Try to get from the current question
            else if (Qualtrics.SurveyEngine && 
                     Qualtrics.SurveyEngine.QuestionInfo && 
                     Qualtrics.SurveyEngine.QuestionInfo.QID) {
                activeQID = "QID" + Qualtrics.SurveyEngine.QuestionInfo.QID;
            }
        }

        // 4. Also try to use any QIDs we know from the handshake state
        if (!activeQID) {
            for (let qid in chatbotHandshakeState) {
                if (qid && qid.startsWith('QID')) {
                    activeQID = qid;
                    break;
                }
            }
        }

        if (activeQID) {
            console.log("[QUALTRICS GLOBAL] Found active QID:", activeQID);
            
            // Create hidden form fields for this QID
            const hiddenFieldCreated = createHiddenQuestionField(activeQID, 'chatData', dataString);
            console.log("[QUALTRICS GLOBAL] Hidden field creation result:", hiddenFieldCreated);
            
            if (hiddenFieldCreated) {
                saveSuccessful = true;
                window.chatDataSetInCurrentPage = true;
            }
        } else {
            console.warn("[QUALTRICS GLOBAL] Could not find active QID for hidden field");
            
            // Fallback: Try to create hidden field in any question container
            try {
                const containers = document.querySelectorAll('.QuestionOuter, .QuestionBody');
                if (containers.length > 0) {
                    const fallbackQID = "chatbot_container";
                    const hiddenFieldCreated = createHiddenQuestionField(fallbackQID, 'chatData', dataString);
                    console.log("[QUALTRICS GLOBAL] Fallback hidden field creation result:", hiddenFieldCreated);
                    if (hiddenFieldCreated) {
                        saveSuccessful = true;
                        window.chatDataSetInCurrentPage = true;
                    }
                }
            } catch (containerError) {
                console.error("[QUALTRICS GLOBAL] Error creating fallback hidden field:", containerError);
            }
        }
    } catch (qidError) {
        console.error("[QUALTRICS GLOBAL] Error finding active QID:", qidError);
    }
    
    // Update global state and return result
    window.chatDataSetInCurrentPage = saveSuccessful;
    return saveSuccessful;
}

// ... (rest of the code remains the same)

// --- Global listener for messages from the iframe --- 
if (!window.qualtricsChatbotMessageListenerAttached) {
    console.log("[QUALTRICS GLOBAL] Attaching global message listener.");
    window.addEventListener('message', function(event) {
        const qualtricsParentOrigin = window.location.origin;

        // Phase 1: Basic Origin Filtering
        if (event.origin !== chatbotOrigin && event.origin !== qualtricsParentOrigin) {
            console.warn(`[QUALTRICS GLOBAL] Message from untrusted origin (${event.origin}) ignored. Expected ${chatbotOrigin} or ${qualtricsParentOrigin}.`);
            return;
        }

        // Phase 2: Handling messages based on type and stricter origin check for OUR messages
        if (event.data && event.data.type) {
            switch (event.data.type) {
                case 'iframe_ready_for_config':
                    if (event.origin === chatbotOrigin) {
                        console.log(`[QUALTRICS GLOBAL] Received 'iframe_ready_for_config' from: ${event.origin}. Attempting to map to QID via event.source.`);
                        let sourceQID = null;
                        for (const q_id_key in chatbotHandshakeState) {
                            if (chatbotHandshakeState[q_id_key] && chatbotHandshakeState[q_id_key].iframeRef && chatbotHandshakeState[q_id_key].iframeRef.contentWindow === event.source) {
                                sourceQID = q_id_key;
                                break;
                            }
                        }

                        if (sourceQID && chatbotHandshakeState[sourceQID]) {
                            console.log(`[QUALTRICS QID: ${sourceQID}] 'iframe_ready_for_config' (mapped via event.source) processing.`);
                            window.chatbotInitializedForQID[sourceQID] = false; // Allow re-init if iframe reloaded
                            chatbotHandshakeState[sourceQID].isReadyForConfig = true;
                            trySendInitConfigForQIDGlobal(sourceQID);
                        } else {
                            console.warn("[QUALTRICS GLOBAL] 'iframe_ready_for_config' received, but could not map event.source to a known QID/iframe or handshake state not found. This can happen if the iframe reloaded unexpectedly or if state is mismatched.");
                        }
                    } else {
                        console.warn(`[QUALTRICS GLOBAL] 'iframe_ready_for_config' received from non-chatbot origin ${event.origin}. Expected ${chatbotOrigin}. Ignoring.`);
                    }
                    break;

                case 'chatbot_data':
                    if (event.origin === chatbotOrigin) {
                        const receivedDataString = event.data.data;
                        console.log("[QUALTRICS GLOBAL] 'chatbot_data' received from chatbot. Raw data string:", receivedDataString);
                        
                        // Extract QID from the data if possible
                        let currentQID = "";
                        try {
                            const parsedData = JSON.parse(receivedDataString);
                            if (parsedData && parsedData.qid) {
                                currentQID = parsedData.qid;
                                console.log("[QUALTRICS GLOBAL] Extracted QID from chat data: " + currentQID);
                            }
                        } catch (e) {}
                        
                        if (typeof receivedDataString === 'string' && receivedDataString.trim() !== "") {
                            saveChatDataToQualtrics(receivedDataString); // Use the consolidated save function
                        } else {
                            console.warn(`[QUALTRICS GLOBAL] 'chatbot_data' message received from non-chatbot origin ${event.origin}. Expected ${chatbotOrigin}. Ignoring.`);
                        }
                    } else {
                        console.warn(`[QUALTRICS GLOBAL] 'chatbot_data' message received from non-chatbot origin ${event.origin}. Expected ${chatbotOrigin}. Ignoring.`);
                    }
                    break;

                // ... (rest of the code remains the same)
                    if (event.origin === chatbotOrigin) {
                        console.log("[QUALTRICS GLOBAL] Received other message type from chatbot: " + event.data.type + ". Data:", event.data);
                    } else if (event.origin === qualtricsParentOrigin) {
                        // These are messages from Qualtrics itself. Usually not an issue unless they interfere.
                        // console.log(`[QUALTRICS GLOBAL] Message from PARENT PAGE (${event.origin}) of type ${event.data.type} allowed to propagate. Data:`, event.data);
                    }
                    break;
            }
        } else {
            // Message without event.data or event.data.type
            if (event.origin === chatbotOrigin) {
                console.warn("[QUALTRICS GLOBAL] Received message from chatbot origin without data.type or data is null/undefined:", event);
            } else if (event.origin === qualtricsParentOrigin) {
                // console.log(`[QUALTRICS GLOBAL] Message from PARENT PAGE (${event.origin}) without data.type allowed to propagate. Data:`, event.data);
            }
        }
    });
    window.qualtricsChatbotMessageListenerAttached = true;
}

// --- Logic for "Continue" button to ensure data is captured ---
Qualtrics.SurveyEngine.addOnReady(function() {
    var qid = this.questionId;
    var questionThis = this; // Store for use in callbacks
    console.log("[QUALTRICS QID: " + qid + "] addOnReady triggered. Attempting to find Next button.");

    var buttonToUse = null;
    var foundLocation = "";

    var nextButtonInQuestion = this.getQuestionContainer().querySelector('#NextButton');
    if (nextButtonInQuestion) {
        buttonToUse = nextButtonInQuestion;
        foundLocation = "question container";
    } else {
        console.warn("[QUALTRICS QID: " + qid + "] Next button NOT FOUND within question container. Trying global search.");
        var globalNextButton = document.getElementById('NextButton');
        if (globalNextButton) {
            buttonToUse = globalNextButton;
            foundLocation = "globally";
        } else {
            console.error("[QUALTRICS QID: " + qid + "] Next button NOT FOUND globally either. Cannot attach 'get_chat_data' handler.");
            return; 
        }
    }

    if (buttonToUse) {
        console.log("[QUALTRICS QID: " + qid + "] Using Next button found " + foundLocation + ". outerHTML: " + buttonToUse.outerHTML);
        
        // Store the original click handler if it exists
        var originalOnClick = buttonToUse.onclick;

        buttonToUse.onclick = function(event) {
            console.log("[QUALTRICS QID: " + qid + "] Next button 'onclick' handler EXECUTED (found " + foundLocation + ").");
            
            var iframe = document.querySelector('#iframeContainer-' + qid + ' iframe'); 
            
            if (iframe && iframe.contentWindow) {
                console.log("[QUALTRICS DEBUG] Inside onclick: qid = " + qid + ", chatbotOrigin = " + chatbotOrigin);
                console.log("%c[QUALTRICS QID: " + qid + "] Sending 'get_chat_data' to iframe. Target Origin: " + chatbotOrigin, "color: orange; font-weight: bold;");
                
                if (typeof chatbotOrigin !== 'string' || chatbotOrigin.trim() === '' || !chatbotOrigin.startsWith('http')) {
                    console.error("[QUALTRICS ERROR] chatbotOrigin is invalid ('" + chatbotOrigin + "'). NOT sending postMessage.");
                } else {
                    iframe.contentWindow.postMessage({ type: 'get_chat_data' }, chatbotOrigin);
                }
            } else {
                console.error("[QUALTRICS QID: " + qid + "] Could not find iframe (selector: #iframeContainer-" + qid + " iframe) to send 'get_chat_data'.");
            }

            console.log("[QUALTRICS QID: " + qid + "] Preventing default navigation and setting timeout for 700ms.");
            event.preventDefault(); 
            
            setTimeout(function() {
                console.log("[QUALTRICS QID: " + qid + "] Executing delayed navigation to next page.");
                
                // Force Qualtrics to commit any pending data operations
                // Check if this is the last question in the survey
                const isLastQuestion = (function() {
                    // Method 1: Look for "Submit" text or translation equivalent on button
                    if (buttonToUse && 
                        (buttonToUse.value === "Submit" || 
                         buttonToUse.innerText === "Submit" || 
                         buttonToUse.getAttribute("alt") === "Submit")) {
                        return true;
                    }
                    // Method 2: Check Qualtrics internal API if available
                    if (typeof Qualtrics !== 'undefined' && 
                        typeof Qualtrics.SurveyEngine !== 'undefined' && 
                        typeof Qualtrics.SurveyEngine.getInstance === 'function') {
                        var instance = Qualtrics.SurveyEngine.getInstance();
                        if (instance && instance.isLastPage) {
                            return instance.isLastPage();
                        }
                    }
                    // Method 3: Try to detect via URL or other means
                    if (window.location.href.indexOf("LastPage=1") > -1) {
                        return true;
                    }
                    return false;
                })();
            
            console.log("[QUALTRICS QID: " + qid + "] Is this the final question? " + isLastQuestion);
            
            if (isLastQuestion) {
                console.log("[QUALTRICS QID: " + qid + "] This appears to be the FINAL QUESTION. Using special submission handling.");
            }
            
            setTimeout(function() {
                console.log("[QUALTRICS QID: " + qid + "] Executing delayed navigation to next page.");
                console.log("[QUALTRICS QID: " + qid + "] Attempting to force data commit before navigation...");
                
                try {
                    // Final attempt to ensure our data is saved
                    if (window.lastReceivedChatData) {
                        console.log("[QUALTRICS QID: " + qid + "] Final check: Setting embedded data from window.lastReceivedChatData");
                        
                        // Multiple approaches to force data persistence
                        Qualtrics.SurveyEngine.setEmbeddedData('chatData', window.lastReceivedChatData);
                        
                        if (typeof Qualtrics !== 'undefined' && 
                            typeof Qualtrics.SurveyEngine !== 'undefined' && 
                            typeof Qualtrics.SurveyEngine.registry !== 'undefined' && 
                            typeof Qualtrics.SurveyEngine.registry.qobj !== 'undefined' && 
                            typeof Qualtrics.SurveyEngine.registry.qobj.setEDValue === 'function') {
                            Qualtrics.SurveyEngine.registry.qobj.setEDValue('chatData', window.lastReceivedChatData);
                        }
                        
                        // Force flush any pending changes
                        if (typeof Qualtrics.SurveyEngine.registry !== 'undefined' && 
                            typeof Qualtrics.SurveyEngine.registry.save === 'function') {
                            console.log("[QUALTRICS QID: " + qid + "] Calling Qualtrics.SurveyEngine.registry.save()");
                            Qualtrics.SurveyEngine.registry.save();
                        }
                    }
                    
                    // Verify data was actually saved and saved to hidden field
                    if (isLastQuestion) {
                        const chatDataField = document.querySelector('#QR\\~' + qid + '\\~chatData, input[name="QR~' + qid + '~chatData"]');
                        if (chatDataField) {
                            console.log("[QUALTRICS QID: " + qid + "] FINAL CHECK: Hidden field exists with value length: " + chatDataField.value.length);
                        } else {
                            console.warn("[QUALTRICS QID: " + qid + "] FINAL CHECK: Hidden field not found, creating one last attempt...");
                            createHiddenQuestionField(qid, 'chatData', window.lastReceivedChatData || 
                                                     (window.sessionStorage ? window.sessionStorage.getItem('qualtricsLastChatData') : ''));
                        }
                        
                        // Get the form element that contains the hidden fields
                        var form = document.querySelector('form#Page');
                        if (form) {
                            // Force a form submit directly
                            console.log("[QUALTRICS QID: " + qid + "] FINAL SUBMIT: Forcing form submission directly.");
                            form.submit();
                            return; // Skip other navigation methods
                        }
                    }
                } catch (e) {
                    console.error("[QUALTRICS QID: " + qid + "] Error in final question handling:", e);
                }
                
                // Restore original click handler temporarily to prevent infinite loops
                if (buttonToUse) {
                    buttonToUse.onclick = null;
                    console.log("[QUALTRICS QID: " + qid + "] Restoring original Next button click handler.");
                }
                
                // Method 1: Try to use the question context to navigate properly
                if (typeof questionThis === 'object' && 
                    typeof questionThis.clickNextButton === 'function') {
                    console.log("[QUALTRICS QID: " + qid + "] Using questionThis.clickNextButton()");
                    questionThis.clickNextButton();
                }
                // Method 2: Try to use Qualtrics's native form submission method
                else if (typeof Qualtrics !== 'undefined' && 
                    typeof Qualtrics.SurveyEngine !== 'undefined' && 
                    typeof Qualtrics.SurveyEngine.navBtn !== 'undefined' && 
                    typeof Qualtrics.SurveyEngine.navBtn.submitForm === 'function') {
                    console.log("[QUALTRICS QID: " + qid + "] Using Qualtrics.SurveyEngine.navBtn.submitForm() for proper form submission");
                    // This is expected to properly submit the form, committing all data
                    Qualtrics.SurveyEngine.navBtn.submitForm();
                }
                // Method 3: Use jQuery to trigger a click on the Next button directly
                else if (typeof jQuery !== 'undefined') {
                    console.log("[QUALTRICS QID: " + qid + "] Using jQuery to click Next button");
                    jQuery("#NextButton").click();
                } 
                // Method 4: If jQuery not available, directly click the button
                else if (buttonToUse && typeof buttonToUse.click === 'function') {
                    console.log("[QUALTRICS QID: " + qid + "] Directly clicking Next button");
                    buttonToUse.click();
                }
                // Method 5: Last resort, try a different Qualtrics API
                else {
                    console.log("[QUALTRICS QID: " + qid + "] All standard methods failed, trying to find any available navigation method");
                    if (typeof Qualtrics !== 'undefined' && Qualtrics.SurveyEngine && 
                        typeof Qualtrics.SurveyEngine.Page !== 'undefined' && 
                        typeof Qualtrics.SurveyEngine.Page.pageButtons !== 'undefined' && 
                        typeof Qualtrics.SurveyEngine.Page.pageButtons.clickNextButton === 'function') {
                        console.log("[QUALTRICS QID: " + qid + "] Using Qualtrics.SurveyEngine.Page.pageButtons.clickNextButton()");
                        Qualtrics.SurveyEngine.Page.pageButtons.clickNextButton();
                    } else {
                        console.error("[QUALTRICS QID: " + qid + "] Could not find any method to navigate to next page. Manual navigation required.");
                        alert("Please click Next manually to continue.");
                    }
                }
            }, 1000); // Increased delay to 1000ms for final page reliability

        };
        console.log("[QUALTRICS QID: " + qid + "] 'onclick' handler ASSIGNED to Next button (found " + foundLocation + ") with delayed navigation.");
    }
});

// --- Save data on page unload as an extra precaution ---
// Commented out until needed - can be enabled for additional safety
// Qualtrics.SurveyEngine.addOnUnload(function() {
//     var qid = this.questionId;
//     console.log("[QUALTRICS QID: " + qid + "] addOnUnload triggered. Attempting final data save.");
//     
//     // Try to save the data from our backup sources if possible
//     try {
//         if (window.lastReceivedChatData) {
//             console.log("[QUALTRICS QID: " + qid + "] Setting embedded data from window.lastReceivedChatData on unload");
//             Qualtrics.SurveyEngine.setEmbeddedData('chatData', window.lastReceivedChatData);
//         } else if (window.sessionStorage && window.sessionStorage.getItem('qualtricsLastChatData')) {
//             console.log("[QUALTRICS QID: " + qid + "] Setting embedded data from sessionStorage on unload");
//             Qualtrics.SurveyEngine.setEmbeddedData('chatData', window.sessionStorage.getItem('qualtricsLastChatData'));
//         } else {
//             console.log("[QUALTRICS QID: " + qid + "] No backup data found to set on unload");
//         }
//     } catch (e) {
//         console.error("[QUALTRICS QID: " + qid + "] Error setting embedded data on unload:", e);
//     }
// });
import logging
import os
import google.generativeai as genai
from fastapi import FastAPI, HTTPException, Form, Request
from fastapi.staticfiles import StaticFiles
from fastapi.concurrency import run_in_threadpool # Needed for LLM call
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import google.api_core.exceptions
import re
import time
import json # Needed for postMessage data
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional, Dict

# Firestore imports
from google.cloud import firestore

# --- Load Environment Variables ---
load_dotenv()

# --- Configure Logging ---
logging.basicConfig(level=logging.INFO) # Back to INFO for less verbose logs unless debugging
logger = logging.getLogger(__name__)

# --- Configure Gemini ---
try:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not found in environment variables.")
    genai.configure(api_key=api_key)
    # Use Flash for speed/cost with large context window
    model_name = "gemini-2.5-flash-preview-04-17"
    # Base model instance - system prompt applied per-call now
    logger.info(f"Gemini base model configured: '{model_name}'.")
    generation_config = genai.types.GenerationConfig(
        temperature=0.7,
        # max_output_tokens=150 # Optional: Limit bot response length
    )
except Exception as e:
    logger.error(f"Gemini Initialization error: {e}", exc_info=True)
    exit()

# --- Configure Firestore Client ---
try:
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT", "automltry")
    database_id = "qualtricsbot" # Your specific database ID

    if not project_id:
        raise ValueError("GOOGLE_CLOUD_PROJECT env var not set")

    db = firestore.Client(
        project=project_id,
        database=database_id
    )
    SESSIONS_COLLECTION = "chatbot_sessions_step5" # Use a distinct name for testing this step
    logger.info(f"Firestore client initialized for project '{project_id}' targeting database '{database_id}'. Using collection '{SESSIONS_COLLECTION}'.")

except Exception as e:
    logger.error(f"Error initializing Firestore client: {e}", exc_info=True)
    exit()

# --- FastAPI App ---
app = FastAPI()

# --- Jinja2 Template Setup ---
try:
    templates = Jinja2Templates(directory="templates")
    logger.info("Jinja2 templates initialized.")
except Exception as e:
    logger.error(f"Error initializing Jinja2 templates: {e}", exc_info=True)
    exit()

# --- Static Files Mount (for CSS) ---
try:
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    if not os.path.isdir(static_dir):
         logger.warning(f"Static dir not found: {static_dir}. Creating.")
         os.makedirs(static_dir, exist_ok=True)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    logger.info("Static files mounted.")
except Exception as e:
     logger.error(f"Error mounting static files: {e}", exc_info=True)
     exit()

# --- Default Session State ---
def get_default_session_state():
    # State now just holds the history list and timestamp for TTL
    return {
        "history": [], # List of {'role': 'user'/'model', 'parts': ['text']}
        "last_updated": firestore.SERVER_TIMESTAMP
    }

# --- LLM Helper Function ---
async def generate_llm_response(system_prompt: str, history: list) -> str:
    """Generates response using Gemini, passing history and system instruction."""
    logger.debug(f"LLM Call Start. History length: {len(history)}. System Prompt: '{system_prompt[:100]}...'")
    if history:
         log_history = json.dumps(history[-4:], indent=2) # Log last 2 Q&A pairs
         logger.debug(f"LLM Call History Snippet:\n{log_history}")

    try:
        # Create model instance with the specific system instruction FOR THIS CALL
        # Ensure model_name is accessible here (it's global in this structure)
        model_with_system_prompt = genai.GenerativeModel(
             model_name,
             system_instruction=system_prompt
        )
        # Send only the user/model message history to generate_content
        # Use run_in_threadpool because generate_content is synchronous
        response = await run_in_threadpool(
            model_with_system_prompt.generate_content,
            contents=history, # History should be in the correct format
            generation_config=generation_config,
        )
        # logger.debug(f"Raw Gemini Response: {response}") # Optional: very verbose

        # Robust checks for response validity
        if not response.candidates:
             block_reason = response.prompt_feedback.block_reason if response.prompt_feedback else 'Unknown'
             logger.warning(f"LLM Helper: Gemini returned no candidates. Blocked? Reason: {block_reason}")
             return "ERROR_LLM_BLOCKED"
        try:
            content = response.candidates[0].content
            parts = content.parts
            if not parts:
                 sf = response.candidates[0].safety_ratings if response.candidates[0].safety_ratings else 'N/A'
                 logger.warning(f"LLM Helper: Gemini returned no content parts. Safety: {sf}")
                 return "ERROR_LLM_NO_RESPONSE"
            result_text = parts[0].text.strip()
        except (AttributeError, IndexError, ValueError, TypeError) as e:
             sf = response.candidates[0].safety_ratings if response.candidates[0].safety_ratings else 'N/A'
             logger.warning(f"LLM Helper: Error accessing response parts: {e}. Safety: {sf}.")
             return "ERROR_LLM_NO_RESPONSE"

        if not result_text:
             logger.warning(f"LLM Helper: Gemini returned empty text string. Safety: {response.candidates[0].safety_ratings}")
             return "ERROR_LLM_EMPTY_TEXT"

        # Basic sanitization
        result_text = re.sub(r'^[\s"\']+|[\s"\']+$', '', result_text)
        result_text = re.sub(r'^(Assistant|XUX):\s*', '', result_text, flags=re.IGNORECASE)
        logger.debug(f"LLM Call End. Result: '{result_text[:100]}...'")
        return result_text

    except google.api_core.exceptions.GoogleAPIError as e:
        logger.error(f"LLM Helper: Gemini API Error: {e}", exc_info=True)
        # Check for specific permission denied errors
        if 'PERMISSION_DENIED' in str(e) or 'API key not valid' in str(e):
             logger.error("LLM Helper: PERMISSION DENIED or INVALID API KEY detected.")
             return "ERROR_LLM_AUTH_ERROR" # More specific error
        return "ERROR_LLM_API_ERROR"
    except Exception as e:
        logger.error(f"LLM Helper: Error during call/processing: {e}", exc_info=True)
        return "ERROR_LLM_UNKNOWN"

# --- System Prompt Definition ---
INITIAL_SURVEY_QUESTION = "What are your main pain points with this product?" # Example

# --- Define your Pydantic models for the config ---
# (You might have these already from previous suggestions, ensure they match what JS sends)
class PromptParams(BaseModel):
    maxFollowUps: int = 10
    focusAreas: List[str] = Field(default_factory=list)
    avoidTopics: List[str] = Field(default_factory=list)
    tone: str = "professional"
    depth: str = "moderate"

class UiConfig(BaseModel):
    headerText: str = "Survey Bot Demo"
    inputPlaceholder: str = "Type something..."
    botName: str = "Research Assistant" # Example, if you use it

class ChatbotConfig(BaseModel):
    initialQuestion: str = "What are your main pain points with this product?"
    promptParams: PromptParams = Field(default_factory=PromptParams)
    uiConfig: UiConfig = Field(default_factory=UiConfig)

# --- Store the configuration (globally or per session) ---
# For simplicity, let's use a global variable for now.
# In a production system, you'd likely store this per session_id in Firestore
# alongside the conversation history if it can vary per respondent.
# This will hold the latest config received from ANY Qualtrics iframe instance.
# If multiple users are taking the survey simultaneously with different configs,
# this simple global approach will lead to them overwriting each other's configs
# for the Python backend. A session-based approach is more robust for multiple users.
current_chatbot_config: ChatbotConfig = ChatbotConfig() # Initialize with default

# --- Add the new /config endpoint ---
@app.post("/config")
async def receive_config(config: ChatbotConfig):
    global current_chatbot_config
    current_chatbot_config = config
    logger.info(f"Received new chatbot configuration: {config.model_dump_json(indent=2)}")
    # You might want to save this config to Firestore associated with a session_id
    # if the config can change per user/session initiated from Qualtrics.
    # For now, just updating a global one.
    return {"message": "Configuration received successfully."}

def generate_system_prompt(config: ChatbotConfig) -> str:
    return f"""You are a helpful and insightful qualitative research assistant conducting a brief follow-up interview. 
    The user is responding to the initial question: '{config.initialQuestion}'.

    CONVERSATION RULES:
1. Analyze History: Carefully read the entire conversation history below.
2. If the user brings up these areas, put particular focus on them: {', '.join(config.promptParams.focusAreas) if config.promptParams.focusAreas else 'N/A'}
3. Avoid these topics: {', '.join(config.promptParams.avoidTopics) if config.promptParams.avoidTopics else 'N/A'}
4. Maintain a {config.promptParams.tone} tone
5. Explore topics to a {config.promptParams.depth} depth
6. Ask at most {config.promptParams.maxFollowUps} concise, natural sounding follow-up question(s)
7. The follow up question should probe deeper into an interesting, unclear, or newly mentioned point 
in the *user's latest response*.
8.  Stay focused on making sure that you ask a follow up question about every topic the user first lists. 
Don't go too deep into new issues until address the first ones. If someone's response is short, vague or not information in one area. Check to see if there other topics you didn't address and ask questions about that.
9.  Avoid Redundancy: Do NOT ask about something the user has already clearly explained or that you have already asked about in the history. Check the history thoroughly.
10.  Stay Focused: Keep questions relevant to the initial survey question and the user's answers. If the user goes off-topic, gently guide them back.
11.  Be Concise: Keep your questions short. Do not add introductory phrases like "Okay, tell me more about..." or "Thanks for sharing...". Just ask the question.
12.  If the user starts with multiple points, return to those points with follow up questions without getting too deep into new topics and before ending the interaction or going too deep into new topics. 
13.  Forbidden Questions: Do NOT ask for personal information, solutions, feelings/emotions, willingness to pay, or numerical ratings. Do NOT ask "yes/no" questions or questions starting with "Do you...", "Have you...", "Did you...", "Is there...", "Are there...", "Was there...", "Were there...". Focus on 'What', 'How', 'Why', 'Tell me more about...' style questions related to their statement.
14.  Make sure you return to the first issues the user mentioned before going too deep into any new issues. Circle back before getting too deep into new areas past the first question. 
15. Know when to stop. If you get a string of really short, uninformative answers, or if people have answered max number of questions. Conclude with the exact phrase "Thank you, that's helpful feedback on those points"
"""

# --- State Helper Functions ---
def load_session_state(session_id: str) -> dict:
    """Loads history from Firestore, returns default if not found or error."""
    logger.debug(f"Session {session_id}: Entering load_session_state")
    state = get_default_session_state() # Start with default structure
    try:
        logger.debug(f"Session {session_id}: Attempting Firestore GET...")
        doc_ref = db.collection(SESSIONS_COLLECTION).document(session_id)
        doc_snapshot = doc_ref.get()
        logger.debug(f"Session {session_id}: Firestore GET completed. Exists: {doc_snapshot.exists}")
        if doc_snapshot.exists:
            loaded_data = doc_snapshot.to_dict()
            if loaded_data:
                 state = loaded_data
                 state.setdefault("history", [])
                 state.setdefault("last_updated", None)
                 logger.info(f"Session {session_id}: Loaded state with {len(state['history'])} history turns.")
            else:
                 logger.warning(f"Session {session_id}: Document exists but to_dict() returned None. Using default.")
                 state = get_default_session_state()
        else:
            logger.info(f"Session {session_id}: No state found. Using default.")
            state = get_default_session_state()
    except Exception as e:
        logger.error(f"Session {session_id}: Error loading state from Firestore: {e}", exc_info=True)
        state = get_default_session_state()
    logger.debug(f"Session {session_id}: Exiting load_session_state")
    return state

def save_session_state(session_id: str, current_state_dict: dict):
    """Saves the full state dictionary (including history and timestamp) to Firestore."""
    logger.debug(f"Session {session_id}: Entering save_session_state (History length: {len(current_state_dict.get('history',[]))})")
    try:
        doc_ref = db.collection(SESSIONS_COLLECTION).document(session_id)
        state_to_save = current_state_dict.copy()
        state_to_save["last_updated"] = firestore.SERVER_TIMESTAMP
        state_to_save.setdefault("history", [])
        # Remove keys that shouldn't be saved if they exist (like internal sets if we used them)
        # state_to_save.pop('internal_set_variable', None)

        doc_ref.set(state_to_save, merge=True) # Use merge=True to be safer
        logger.info(f"Session {session_id}: Saved state to Firestore.")
    except Exception as e:
         logger.error(f"Session {session_id}: Error saving state to Firestore: {e}", exc_info=True)

# --- FastAPI App Instance ---
app = FastAPI()

# --- Jinja2 Template Setup ---
templates = Jinja2Templates(directory="templates")

# --- Endpoints ---

@app.post("/config")
async def receive_config(config: ChatbotConfig):
    global current_chatbot_config
    current_chatbot_config = config
    logger.info(f"Received new chatbot configuration: {config.model_dump_json(indent=2)}")
    return {"message": "Configuration received successfully."}

@app.get("/health", response_class=JSONResponse)
async def health_check():
    """Simple health check endpoint."""
    logger.info("Health check endpoint called.")
    return {"status": "ok"}

@app.get("/", response_class=HTMLResponse)
async def get_chat_page(request: Request, session_id: str | None = None):
    """Handles initial load or refresh - renders chat interface"""
    logger.info(f"GET / endpoint entered. Provided session_id: {session_id}")
    is_new_session = False
    if not session_id:
        session_id = db.collection('_temp').document().id # Generate new Firestore-style ID
        is_new_session = True
        logger.info(f"GET request: No session_id provided, generated new one: {session_id}")
        current_state = get_default_session_state()
        # Use the initialQuestion from the globally (or session-specifically) stored config
        effective_initial_question = current_chatbot_config.initialQuestion
        # Add initial prompt to history for new sessions
        current_state["history"] = [{'role': 'model', 'parts': [effective_initial_question]}]
        save_session_state(session_id, current_state) # Save initial state
    else:
         logger.info(f"GET request for existing session {session_id}. Loading state.")
         current_state = load_session_state(session_id)
         if not current_state.get("history"):
              logger.warning(f"Session {session_id}: Loaded state but history was empty. Adding initial question from config: '{current_chatbot_config.initialQuestion}'")
              current_state["history"] = [{'role': 'model', 'parts': [current_chatbot_config.initialQuestion]}]

    conversation_history = current_state.get("history", [])
    conversation_active = True
    if conversation_history and conversation_history[-1]['role'] == 'model' and "thank you," in conversation_history[-1]['parts'][0].lower():
         conversation_active = False

    template_context = { "request": request, "session_id": session_id, "history": conversation_history,
                         "conversation_active": conversation_active, "final_data_to_post": None,
                         "ui_config": current_chatbot_config.uiConfig }
    logger.info(f"GET request for session {session_id}: Rendering template.")
    try:
        return templates.TemplateResponse("chat.html", template_context)
    except Exception as template_e:
         logger.error(f"Session {session_id}: Error rendering template: {template_e}", exc_info=True)
         return HTMLResponse("<html><body><h1>Template Error</h1></body></html>", status_code=500)


@app.post("/", response_class=HTMLResponse)
async def post_chat_message(
    request: Request,
    session_id: str = Form(...),
    prompt: str = Form(...),
    # config: Optional[ChatbotConfig] = None # Remove this, config will come from global/session
):
    """Handles user form submission, calls LLM, updates state, and re-renders."""
    logger.info(f">>>>>>> POST / endpoint entered for session {session_id} <<<<<<<")

    # Use the globally (or session-specifically) stored config
    system_prompt = generate_system_prompt(current_chatbot_config) # Pass the whole config object
    
    user_prompt = prompt.strip()
    logger.info(f"POST request for session {session_id}. User prompt: '{user_prompt[:100]}...'")
    bot_response_text = "Sorry, something went wrong processing your message." # Default
    conversation_history = []
    conversation_active = True
    final_data_to_post = None
    current_state = {} # Initialize

    try:
        # --- Load Conversation History ---
        current_state = load_session_state(session_id) # Uses helper
        conversation_history = current_state.get("history", [])
        logger.debug(f"Session {session_id}: History loaded.")

        # --- Append User Prompt (if not empty) ---
        if not user_prompt:
             logger.warning(f"Session {session_id}: Received empty prompt on POST.")
             bot_response_text = "Please type a response."
             conversation_active = True # Keep interface active
             # Skip LLM call, just save state to update timestamp
             save_session_state(session_id, current_state)
        else:
             conversation_history.append({'role': 'user', 'parts': [user_prompt]})
             current_state["history"] = conversation_history # Update state dict

             # --- Call LLM --- <<<< MODIFIED PART >>>>
             logger.info(f"Session {session_id}: Calling LLM with history length {len(conversation_history)}...")
             llm_response = await generate_llm_response(system_prompt, conversation_history)
             logger.info(f"Session {session_id}: LLM call completed.")

             if llm_response.startswith("ERROR_LLM"):
                 logger.error(f"Session {session_id}: LLM call failed: {llm_response}")
                 # Handle specific errors for user feedback
                 if llm_response == "ERROR_LLM_BLOCKED":
                      bot_response_text = "I cannot process that previous request due to safety policies."
                 elif llm_response == "ERROR_LLM_AUTH_ERROR":
                      bot_response_text = "There seems to be an authentication issue with the AI service."
                 else: # NO_RESPONSE, EMPTY_TEXT, UNKNOWN, API_ERROR
                      bot_response_text = "Sorry, I encountered an internal error generating a response."
                 # Don't append this error to history
             else:
                 bot_response_text = llm_response # Use the successful response
                 # Append successful bot response to history
                 conversation_history.append({'role': 'model', 'parts': [bot_response_text]})
                 current_state["history"] = conversation_history # Update state dict
                 # Check if this was the concluding response
                 if "thank you," in bot_response_text.lower():
                      conversation_active = False
                      logger.info(f"Session {session_id}: Conversation concluded by bot.")
                      # Prepare data for postMessage
                      try:
                          final_data_to_post = json.dumps({
                              "sessionId": session_id,
                              "history": conversation_history # Send the final history
                          })
                      except Exception as json_e:
                           logger.error(f"Session {session_id}: Failed to serialize final data for postMessage: {json_e}")
                           final_data_to_post = json.dumps({"error": "failed to serialize history", "sessionId": session_id})

             # --- Save Updated State to Firestore ---
             # Save state regardless of LLM success (to capture user message etc.)
             save_session_state(session_id, current_state) # Pass the whole state dict

    except Exception as e:
        logger.error(f"Session {session_id}: Uncaught Error DURING POST request processing: {e}", exc_info=True)
        bot_response_text = "Sorry, a critical server error occurred."
        conversation_active = False
        # Try to add error to history for display, but state might be inconsistent
        if isinstance(conversation_history, list):
             conversation_history.append({'role': 'model', 'parts': [bot_response_text]})

    # --- Render Template ---
    template_context = {
        "request": request, "session_id": session_id, "history": conversation_history,
        "conversation_active": conversation_active, "final_data_to_post": final_data_to_post,
        "ui_config": current_chatbot_config.uiConfig }
    logger.info(f"Session {session_id}: Rendering template. Active: {conversation_active}, History items: {len(conversation_history)}, Posting?: {final_data_to_post is not None}")
    try:
        return templates.TemplateResponse("chat.html", template_context)
    except Exception as template_e:
         logger.error(f"Session {session_id}: Error rendering template: {template_e}", exc_info=True)
         return HTMLResponse("<html><body><h1>Internal Server Error</h1><p>Could not render chat interface.</p></body></html>", status_code=500)


# --- Static Files Mount (needed for CSS) ---
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.isdir(static_dir):
     logger.warning(f"Static dir not found: {static_dir}. Creating.")
     os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://*.qualtrics.com"],  # Matches any Qualtrics subdomain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


import logging
import os
import google.generativeai as genai
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from dotenv import load_dotenv
import google.api_core.exceptions
import re
import time
# Firestore imports - Use the Firestore library for Native Mode DB
from google.cloud import firestore
# No longer need datetime for timestamp if using SERVER_TIMESTAMP

# --- Load Environment Variables ---
load_dotenv()

# --- Configure Logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Configure Gemini ---
try:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not found")
    genai.configure(api_key=api_key)
    # Using a generally available stable model - adjust if needed
    model_name = 'gemini-1.5-flash-latest'
    model = genai.GenerativeModel(model_name)
    logger.info(f"Gemini model '{model_name}' initialized.")
    generation_config = genai.types.GenerationConfig(temperature=0.6)
except Exception as e:
    logger.error(f"Initialization error: {e}", exc_info=True)
    exit()

# --- Configure Firestore Client --- (Using firestore library)
try:
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT", "automltry")
    database_id = "qualtricsbot" # Your specific database ID

    if not project_id:
        raise ValueError("GOOGLE_CLOUD_PROJECT environment variable not set and could not be determined.")

    # Initialize Firestore client, targeting your Native Mode DB
    db = firestore.Client( # <--- Use firestore.Client
        project=project_id,
        database=database_id # Specify your named database
    )

    # Define the Collection name (Firestore term)
    SESSIONS_COLLECTION = "chatbot_sessions"
    # Corrected logging using variables
    logger.info(f"Firestore client initialized for project '{project_id}' targeting database '{database_id}'. Using collection '{SESSIONS_COLLECTION}'.")

except ValueError as ve:
    logger.error(f"Configuration error: {ve}")
    exit()
except Exception as e:
    logger.error(f"Error initializing Firestore client: {e}", exc_info=True)
    exit()

# --- Define Input Model ---
class UserInput(BaseModel):
    prompt: str
    session_id: str

# --- Default Session State ---
def get_default_session_state():
    # Use Firestore's special server timestamp for TTL field
    # Store addressed_pain_points as a list for Firestore compatibility
    return {
        "turn_count": 0,
        "initial_pain_points": [],
        "addressed_pain_points": [], # Store as list
        "last_updated": firestore.SERVER_TIMESTAMP # Use Firestore timestamp
    }

# --- LLM Helper Function ---
async def generate_llm_response(prompt_text: str, context_history=None) -> str:
    logger.debug(f"Generating LLM response for prompt: {prompt_text[:100]}...")
    try:
        contents_to_send = [{'role': 'user', 'parts': [prompt_text]}]
        response = await run_in_threadpool(
            model.generate_content,
            contents=contents_to_send,
            generation_config=generation_config,
        )
        logger.debug(f"Raw Gemini Response: {response}")
        result_text = response.text.strip()
        if not result_text:
             safety_feedback = response.prompt_feedback
             logger.warning(f"LLM Helper: Gemini returned empty text. Safety: {safety_feedback}")
             # Return a specific indicator instead of the error message itself
             return "ERROR_LLM_NO_RESPONSE"
        # Basic sanitization
        result_text = re.sub(r'^[\s"\']+|[\s"\']+$', '', result_text) # Remove leading/trailing quotes/space
        return result_text
    except google.api_core.exceptions.GoogleAPIError as e:
        logger.error(f"LLM Helper: Gemini API Error: {e}", exc_info=True)
         # Return a specific indicator
        return "ERROR_LLM_API_ERROR"
    except Exception as e:
        logger.error(f"LLM Helper: Error during call/processing: {e}", exc_info=True)
         # Return a specific indicator
        return "ERROR_LLM_UNKNOWN"


# --- FastAPI App ---
app = FastAPI()

@app.post("/generate_chat")
async def generate_chat(input: UserInput):
    session_id = input.session_id
    user_prompt = input.prompt
    result_text = "An error occurred processing your request." # Default
    current_session_state = None
    logger.info(f"Session {session_id}: generate_chat endpoint START")

    try:
        # Get Firestore document reference for this session
        logger.info(f"Session {session_id}: Getting Firestore doc ref...")
        doc_ref = db.collection(SESSIONS_COLLECTION).document(session_id) # Firestore method
        logger.info(f"Session {session_id}: Got Firestore doc ref.")

        # --- Load State from Firestore ---
        logger.info(f"Session {session_id}: Attempting Firestore GET...")
        doc_snapshot = doc_ref.get() # Firestore method
        logger.info(f"Session {session_id}: Firestore GET completed. Exists: {doc_snapshot.exists}")

        # Use a set internally for easier logic
        addressed_points_set = set()

        if doc_snapshot.exists: # Firestore method
            try:
                current_session_state = doc_snapshot.to_dict() # Firestore method
                # Ensure required keys exist with defaults before accessing
                current_session_state.setdefault("turn_count", 0)
                current_session_state.setdefault("initial_pain_points", [])
                current_session_state.setdefault("addressed_pain_points", [])
                # Convert list from Firestore back to set for easier logic below
                addressed_points_set = set(current_session_state.get("addressed_pain_points", []))
                logger.info(f"Session {session_id}: Successfully loaded state from Firestore.")
            except Exception as e:
                logger.warning(f"Session {session_id}: Failed to decode/process state snapshot: {e}. Starting fresh.")
                current_session_state = get_default_session_state()
                addressed_points_set = set() # Ensure set is empty
        else:
            logger.info(f"Session {session_id}: No state found. Starting new session.")
            current_session_state = get_default_session_state()
            addressed_points_set = set() # Ensure set is empty


        # Increment turn count
        current_session_state["turn_count"] += 1
        current_turn = current_session_state["turn_count"]
        logger.info(f"Session {session_id}: Turn count incremented to {current_turn}")

        # == Turn 1 Logic ==
        if current_turn == 1:
            logger.info(f"Session {session_id}, Turn 1: Processing initial points.")
            current_session_state["initial_pain_points"] = [] # Reset list
            addressed_points_set = set() # Reset set

            extraction_prompt = f"""Analyze the user statement about product pain points. List the distinct pain points mentioned as a comma-separated list (e.g., price, usability, documentation). If none, respond 'NONE'. User statement: "{user_prompt}" """
            logger.info(f"Session {session_id}: Calling LLM for extraction...")
            extracted_points_str = await generate_llm_response(extraction_prompt)
            logger.info(f"Session {session_id}: Extraction LLM call completed. Result: '{extracted_points_str}'")

            # Check for LLM errors before proceeding
            if extracted_points_str.startswith("ERROR_LLM"):
                logger.error(f"Session {session_id}: LLM extraction failed with code: {extracted_points_str}")
                result_text = "Sorry, I had trouble understanding the initial points due to an internal error."
                current_session_state["turn_count"] = 0 # Reset turn count
            elif extracted_points_str and extracted_points_str.upper() != 'NONE':
                potential_points = [p.strip() for p in extracted_points_str.split(',') if p.strip() and len(p.strip()) > 1] # Basic filter
                current_session_state["initial_pain_points"] = potential_points
                logger.info(f"Session {session_id}: Extracted initial points: {potential_points}")

                if current_session_state["initial_pain_points"]:
                    first_point = current_session_state["initial_pain_points"][0]
                    # Refined prompt for Turn 1
                    initial_list_str = ", ".join(current_session_state['initial_pain_points'])
                    follow_up_prompt = f"The user initially mentioned these pain points: {initial_list_str}. Ask exactly ONE short, open-ended follow-up question specifically about their concern regarding '{first_point}'. Just the question, no extra text."
                    logger.info(f"Session {session_id}: Calling LLM for follow-up on '{first_point}'...")
                    result_text = await generate_llm_response(follow_up_prompt) # Call LLM here
                    logger.info(f"Session {session_id}: Follow-up LLM call completed.")
                    if result_text.startswith("ERROR_LLM"):
                         logger.error(f"Session {session_id}: LLM follow-up failed with code: {result_text}")
                         result_text = "Sorry, I had trouble generating a follow-up due to an internal error."
                         # Don't mark point as addressed if follow-up failed
                    else:
                        addressed_points_set.add(first_point) # Add to the set only on success
                else: # Case where potential_points was empty
                     result_text = "Thanks. I see you mentioned something, but could you clarify the specific pain points?"
                     current_session_state["turn_count"] = 0 # Reset
            else: # Case where extraction returned 'NONE' or was empty after stripping
                logger.warning(f"Session {session_id}: No distinct points extracted or extraction failed ('{extracted_points_str}').")
                current_session_state["turn_count"] = 0 # Reset turn count
                result_text = "Thanks for your feedback. Could you please tell me more about any specific challenges or pain points you experienced?"
                # No need to save state here, will be saved at the end

        # == Subsequent Turns Logic ==
        else: # current_turn > 1
            logger.info(f"Session {session_id}, Turn {current_turn}: Processing follow-up.")
            next_point_to_address = None
            # Use the set for checking addressed points
            for point in current_session_state["initial_pain_points"]:
                if point not in addressed_points_set:
                    next_point_to_address = point
                    break

            if next_point_to_address:
                 # Refined prompt for subsequent turns
                initial_list_str = ", ".join(current_session_state['initial_pain_points'])
                follow_up_prompt = f"The user initially mentioned these pain points: {initial_list_str}. You are now asking about '{next_point_to_address}'. Ask exactly ONE short, open-ended follow-up question specifically about '{next_point_to_address}'. Just the question, no extra text."
                logger.info(f"Session {session_id}: Calling LLM for follow-up on '{next_point_to_address}'...")
                result_text = await generate_llm_response(follow_up_prompt)
                logger.info(f"Session {session_id}: Follow-up LLM call completed.")
                if result_text.startswith("ERROR_LLM"):
                     logger.error(f"Session {session_id}: LLM follow-up failed with code: {result_text}")
                     result_text = "Sorry, I had trouble generating a follow-up due to an internal error."
                     # Don't mark point as addressed
                else:
                    addressed_points_set.add(next_point_to_address) # Add to the set only on success
            else: # All initial points addressed
                result_text = "Thank you, that's helpful feedback on those points."
                logger.info(f"Session {session_id}: All initial points addressed. Preparing concluding message.")
                # Optionally reset state here by preparing default dict below
                # current_session_state = get_default_session_state()

        # --- Save Updated State to Firestore ---
        state_to_save = current_session_state.copy()
        # Convert set back to list for Firestore storage
        state_to_save["addressed_pain_points"] = sorted(list(addressed_points_set)) # Save sorted list
        # Ensure timestamp is set for update/TTL
        state_to_save["last_updated"] = firestore.SERVER_TIMESTAMP # Firestore timestamp
        logger.info(f"Session {session_id}: Preparing to save final state to Firestore: {state_to_save}")
        # Use set() to overwrite or create the document
        doc_ref.set(state_to_save, merge=True) # merge=True is often safer
        logger.info(f"Session {session_id}: Firestore SET completed for collection '{SESSIONS_COLLECTION}'.")

    except Exception as e:
        logger.error(f"Session {session_id}: Uncaught Error DURING chat logic or Firestore operation: {e}", exc_info=True)
        # Raise generic 500, specific error logged above
        raise HTTPException(status_code=500, detail="Internal Server Error processing request.")

    logger.info(f"Session {session_id}: generate_chat endpoint END. Returning response: '{result_text[:50]}...'")
    return {"response": result_text}

# --- Static Files Mount (Keep as before) ---
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.isdir(static_dir):
     logger.warning(f"Static dir not found: {static_dir}. Creating.")
     os.makedirs(static_dir, exist_ok=True)
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

# --- Running Instructions Reminder ---
# Needs appropriate IAM role (Cloud Datastore User) for the Cloud Run service account. <-- CORRECT THIS COMMENT
# Requires Firestore TTL policy to be enabled on the 'last_updated' field for automatic cleanup.

# --- Running Instructions Reminder ---
# Needs appropriate IAM role (Cloud Datastore User) for the Cloud Run service account. <--- UPDATE COMMENT
# Requires Firestore TTL policy to be enabled on the 'last_updated' field for automatic cleanup.
import logging
import os
import google.generativeai as genai
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from dotenv import load_dotenv
import google.api_core.exceptions
import re # For parsing extracted points

# --- Load Environment Variables ---
load_dotenv()

# --- Configure Logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Configure Gemini ---
try:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not found in environment variables.")
    genai.configure(api_key=api_key)
    # Use the specific model user requested
    model_name = 'gemini-2.5-pro-exp-03-25'
    model = genai.GenerativeModel(model_name)
    logger.info(f"Gemini model '{model_name}' initialized successfully.")
    generation_config = genai.types.GenerationConfig(temperature=0.6) # Slightly lower temp may help adherence

except ValueError as ve:
     logger.error(f"Configuration error: {ve}")
     exit()
except Exception as e:
    logger.error(f"Error initializing Gemini: {e}", exc_info=True)
    exit()

# --- Define Input Model ---
class UserInput(BaseModel):
    prompt: str

# --- Simple In-Memory State (NOT FOR PRODUCTION) ---
# This dictionary will store state for ONE conversation.
# A real app needs proper session management per user.
session_state = {
    "turn_count": 0,
    "initial_pain_points": [], # List of strings extracted
    "addressed_pain_points": set(), # Set of strings marked as asked
    # "conversation_history": [] # Optional: could store full history here
}

# --- Helper Function for LLM Calls ---
async def generate_llm_response(prompt_text: str, context_history=None) -> str:
    """Calls the LLM and returns the text response, handling basic errors."""
    logger.debug(f"Generating LLM response for prompt: {prompt_text[:100]}...")
    # Note: history management within this helper could be added if needed
    # For now, sending specific prompts without extensive history per call
    try:
        contents_to_send = [{'role': 'user', 'parts': [prompt_text]}]
        # If we passed context_history, structure it appropriately
        # Example: contents_to_send = context_history + [{'role':'user', 'parts':[prompt_text]}]

        response = await run_in_threadpool(
            model.generate_content,
            contents=contents_to_send,
            generation_config=generation_config,
        )
        logger.debug(f"Raw Gemini Response: {response}")
        result_text = response.text.strip()

        if not result_text:
             safety_feedback = response.prompt_feedback
             logger.warning(f"LLM Helper: Gemini returned empty text. Safety feedback: {safety_feedback}")
             return "I couldn't generate a response for that. Could you try rephrasing?"
        return result_text

    except google.api_core.exceptions.GoogleAPIError as e:
        logger.error(f"LLM Helper: Gemini API Error: {e}", exc_info=True)
        # Don't raise HTTPException here, return an error message
        return f"Sorry, there was an API error communicating with the AI model."
    except Exception as e:
        logger.error(f"LLM Helper: Error during call/processing: {e}", exc_info=True)
        return "Sorry, an internal error occurred while generating the response."


# --- Create FastAPI App ---
app = FastAPI()

@app.post("/generate_chat")
async def generate_chat(input: UserInput):
    """
    Handles chat requests, manages state (simple demo), and generates follow-ups.
    """
    global session_state # Allow modification of the global dict (demo only)

    session_state["turn_count"] += 1
    current_turn = session_state["turn_count"]
    user_prompt = input.prompt
    result_text = "An error occurred in state logic." # Default error

    try:
        # == Turn 1: User lists initial pain points ==
        if current_turn == 1:
            logger.info("Turn 1: Processing initial pain points.")
            session_state["initial_pain_points"] = []
            session_state["addressed_pain_points"] = set()

            # --- Task 1: Extract Pain Points ---
            extraction_prompt = f"""Analyze the following user statement about product pain points. List the distinct pain points mentioned as a comma-separated list (e.g., price, usability, missing feature X). If no clear pain points are mentioned, respond with 'NONE'. User statement: "{user_prompt}" """
            extracted_points_str = await generate_llm_response(extraction_prompt)
            logger.info(f"Attempted extraction, result: '{extracted_points_str}'")

            if extracted_points_str and extracted_points_str.upper() != 'NONE':
                # Simple parsing, might need refinement
                potential_points = [p.strip() for p in extracted_points_str.split(',') if p.strip()]
                # Basic filtering/validation could be added here
                session_state["initial_pain_points"] = potential_points
                logger.info(f"Extracted initial points: {session_state['initial_pain_points']}")
            else:
                logger.info("No distinct pain points extracted or 'NONE' returned.")
                # Fallback if extraction fails or nothing is mentioned
                result_text = "Thanks for your feedback. Could you please specify any particular aspects you found challenging?"
                # Reset turn count maybe? Or handle state differently? For now, proceed but list is empty.
                # return {"response": result_text} # Exit early if no points


            # --- Task 2: Ask about the first extracted point ---
            if session_state["initial_pain_points"]:
                first_point = session_state["initial_pain_points"][0]
                follow_up_prompt = f"Ask exactly ONE short, open-ended follow-up question about the user's concern regarding '{first_point}'. Do not add any commentary. Just the question."
                result_text = await generate_llm_response(follow_up_prompt)
                session_state["addressed_pain_points"].add(first_point)
                logger.info(f"Asked about first point: '{first_point}'. Question: '{result_text}'")
            elif not result_text: # If extraction failed and no fallback set yet
                 result_text = "Thanks for your feedback. Can you tell me more about your experience?"


        # == Subsequent Turns: Cycle through remaining points ==
        else:
            logger.info(f"Turn {current_turn}: Processing follow-up.")
            next_point_to_address = None
            for point in session_state["initial_pain_points"]:
                if point not in session_state["addressed_pain_points"]:
                    next_point_to_address = point
                    break

            # --- Task 1: Ask about the next unaddressed initial point ---
            if next_point_to_address:
                logger.info(f"Addressing next initial point: '{next_point_to_address}'")
                follow_up_prompt = f"The user previously mentioned concerns including '{next_point_to_address}'. Ask exactly ONE short, open-ended follow-up question specifically about '{next_point_to_address}'. Do not refer back to previous answers. Just the question about '{next_point_to_address}'."
                result_text = await generate_llm_response(follow_up_prompt)
                session_state["addressed_pain_points"].add(next_point_to_address)
                logger.info(f"Asked about point: '{next_point_to_address}'. Question: '{result_text}'")

            # --- Task 2: All initial points addressed, probe latest response ---
            else:
                logger.info("All initial points addressed. Probing latest response.")
                # Simple probe based on the last user message
                # Define a concluding message instead of probing further
                result_text = "Thank you, that's helpful feedback on those points."
                logger.info(f"All initial points addressed. Sending concluding message: '{result_text}'")
                # Optionally, you could reset state here if needed for a new "round"
                # session_state["turn_count"] = 0
                # session_state["initial_pain_points"] = []
                # session_state["addressed_pain_points"] = set()

    except Exception as e:
        # Catch potential errors in the state logic itself
        logger.error(f"Error in stateful chat logic: {e}", exc_info=True)
        # Use the default error or raise HTTPException
        raise HTTPException(status_code=500, detail="Internal Server Error in chat logic.")

    logger.info(f"Final response for turn {current_turn}: '{result_text[:50]}...'")
    # Add response to history if implementing history tracking
    # session_state["conversation_history"].append({'role': 'user', 'parts': [user_prompt]})
    # session_state["conversation_history"].append({'role': 'model', 'parts': [result_text]})
    return {"response": result_text}


# --- Mount Static Files ---
# (Keep the static files mounting code as before)
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.isdir(static_dir):
     logger.warning(f"Static files directory not found at: {static_dir}. Creating it.")
     os.makedirs(static_dir, exist_ok=True)
     logger.info("Please ensure your index.html is inside the 'static' directory.")
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

# --- Running Instructions ---
# (Keep comments about running with uvicorn)
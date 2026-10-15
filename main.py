
# Imports
# Import necessary libraries for logging, environment variables, web framework, and AI interaction.
import logging
import os
import uuid
import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from google import genai
from google.genai.errors import ClientError, ServerError


# App configuration and state
# Initialize the background job storage, logging, environment configuration, and FastAPI application settings.
jobs = {}
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api-wrapper")
DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() == "true"
client = genai.Client() if not DEMO_MODE else None
def get_api_key_or_ip(request: Request) -> str:
    api_key = request.headers.get("x-api-key")
    return api_key if api_key else get_remote_address(request)
limiter = Limiter(key_func=get_api_key_or_ip)
app = FastAPI(title="LLM API Wrapper")
app.state.limiter = limiter
app.add_exception_handler(
    RateLimitExceeded,
    _rate_limit_exceeded_handler,
)


# Health check
# Endpoint to verify that the service is running.
@app.get("/health")
def health_check():
    """Basic liveness check — confirms the server is up and responding."""
    return {"status": "ok"}


# Sync request model
# Data validation schema for standard synchronous generation requests.
class GenerateRequest(BaseModel):
    prompt: str
    @field_validator("prompt")
    @classmethod
    def prompt_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("prompt cannot be empty")
        return v


# Gemini API call logic
# Centralized function for interfacing with the Gemini AI model with robust error handling.
def call_gemini(prompt: str) -> str:
    """The actual model call, isolated in its own function so both
    the sync endpoint (/generate) and the async endpoint (/generate/async)
    can share the exact same error-handling logic instead of
    duplicating it in two places.
    Returns the generated text on success, or raises an HTTPException
    with a specific status code describing what went wrong.
    """
    if DEMO_MODE:
        return f"[demo response] You said: {prompt}"
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        return response.text
    except ClientError as e:
        if e.code == 429:
            logger.warning("Rate limited by Gemini")
            raise HTTPException(
                status_code=429,
                detail=(
                    "AI service is rate limited right now — "
                    "please retry shortly."
                ),
            )
        logger.error(
            f"Gemini client error: code={e.code}, msg={e.message}"
        )
        raise HTTPException(
            status_code=400,
            detail=(
                "Request was rejected by the AI service — "
                "check your input."
            ),
        )
    except ServerError:
        logger.error("Gemini server error")
        raise HTTPException(
            status_code=503,
            detail=(
                "AI service temporarily unavailable — "
                "please try again."
            ),
        )
    except Exception:
        logger.exception("Unexpected error calling Gemini")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred.",
        )


# Sync generation endpoint
# Handles standard HTTP POST requests for immediate text generation.
@app.post("/generate")
@limiter.limit("5/minute")
def generate(request: Request, req: GenerateRequest):
    result = call_gemini(req.prompt)
    return {"result": result}


# Async request model
# Data validation schema for asynchronous generation requests.
class GenerateAsyncRequest(BaseModel):
    prompt: str
    @field_validator("prompt")
    @classmethod
    def prompt_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("prompt cannot be empty")
        return v


# Background task worker
# Executes the AI generation in the background and updates the job status upon completion or failure.
def run_job_and_store(
    job_id: str,
    prompt: str,
):
    """Runs in the BACKGROUND, after the caller has already received
    their {"job_id": ..., "status": "accepted"} response.
    Actually do the slow work (call_gemini) and store result in memory.
    """
    try:
        result = call_gemini(prompt)
        jobs[job_id] = {"status": "completed", "result": result}
    except Exception as e:
        jobs[job_id] = {"status": "failed", "error": str(e)}


# Async generation endpoint
# Accepts a prompt, initiates a background generation task, and returns a job ID.
@app.post("/generate/async")
@limiter.limit("5/minute")
def generate_async(
    request: Request,
    req: GenerateAsyncRequest,
    background_tasks: BackgroundTasks,
):
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "pending"}
    background_tasks.add_task(
        run_job_and_store,
        job_id,
        req.prompt,
    )
    return {
        "job_id": job_id,
        "status": "accepted",
    }


# Job status endpoint
# Retrieves the current status and result of a previously submitted asynchronous generation job.
@app.get("/job/{job_id}")
def get_job_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# Serve static files
# Mounts the static directory to serve the frontend application.
app.mount("/", StaticFiles(directory="static", html=True), name="static")

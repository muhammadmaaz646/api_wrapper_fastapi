# ============================================================
# OVERVIEW: LLM API Wrapper — Fully Annotated main.py
# ============================================================
#
# This file is a FastAPI wrapper around Google's Gemini API.
#
# The overall shape: one shared "call the model safely" function, wrapped by two different delivery mechanisms
# respond-now (/generate) and respond-later-via-webhook (/generate/async) —
# both protected by the same rate limiter.

# It demonstrates several production-style API concepts:
#   - Environment-based configuration / demo mode
#   - Rate limiting
#   - Request validation
#   - Centralized upstream API error handling
#   - A synchronous generation endpoint
#   - An asynchronous/background generation endpoint
#   - Webhook callbacks
#   - Logging
#
# The overall architecture is:
#
#                    ┌─────────────────────┐
#                    │     FastAPI app     │
#                    └──────────┬──────────┘
#                               │
#                    ┌──────────▼──────────┐
#                    │    Rate limiter     │
#                    └──────────┬──────────┘
#                               │
#                     ┌─────────▼─────────┐
#                     │  Request schema   │
#                     │   + validation    │
#                     └─────────┬─────────┘
#                               │
#                     ┌─────────▼─────────┐
#                     │   call_gemini()   │
#                     │ shared error      │
#                     │ handling core     │
#                     └─────────┬─────────┘
#                               │
#                    ┌──────────▼──────────┐
#                    │     Gemini API      │
#                    └─────────────────────┘
#
# There are two ways to deliver the result:
#
#   /generate
#       Caller waits for Gemini → result returned in same response
#
#   /generate/async
#       Caller gets job_id immediately → background task runs →
#       result is POSTed to the caller's callback_url
#
# ============================================================

# ============================================================
# THE WHOLE FILE IN ONE VIEW
# ============================================================
#
# The architecture can now be summarized as:
#
#                  Incoming HTTP request
#                           │
#                           ▼
#                    ┌─────────────┐
#                    │ Rate limit  │
#                    └──────┬──────┘
#                           │
#                           ▼
#                    ┌─────────────┐
#                    │ Pydantic    │
#                    │ validation  │
#                    └──────┬──────┘
#                           │
#                ┌──────────┴──────────┐
#                │                     │
#                ▼                     ▼
#          /generate            /generate/async
#                │                     │
#                │              Generate job_id
#                │                     │
#                ▼                     ▼
#          call_gemini()        Schedule background
#           [With Error Handling]
#                │                     │
#                ▼                     ▼
#           Gemini API            Respond immediately
#                │                     │
#                ▼                     │
#             Result                    │
#                                      ▼
#                             run_job_and_notify()
#                                      │
#                                      ▼
#                                call_gemini()
#                            [With Error Handling]
#                                      │
#                                      ▼
#                                Gemini result
#                                      │
#                                      ▼
#                               HTTP POST webhook
#                                      │
#                                      ▼
#                               Caller receives
#                                  the result
#
#
# The key design principle is separation of concerns:
#
#     call_gemini()
#         → knows how to communicate safely with Gemini.
#
#     /generate
#         → knows how to provide a normal synchronous API.
#
#     run_job_and_notify()
#         → knows how to perform background work and send a webhook.
#
#     /generate/async
#         → knows how to accept a job and schedule background work.
#
#     slowapi
#         → handles rate limiting.
#
#     Pydantic
#         → handles request validation.
#
#     logging
#         → handles observability and debugging.
#
# This is what makes the wrapper more than a simple script that
# calls an LLM: the application adds an API layer around the model
# with validation, rate limiting, error handling, asynchronous job
# handling, and webhook delivery.
# ============================================================
# ============================================================
# SETUP GUIDE
# ============================================================

# ============================================================
# 1. IMPORTS
# ============================================================
#
# logging — gives us real application logs instead of print().
#
# os — lets us read environment variables, such as DEMO_MODE.
#
# uuid — generates unique job IDs for asynchronous requests.
#
# httpx — HTTP client used to send the webhook POST request to
#         the callback URL supplied by the caller.
#
# BackgroundTasks — FastAPI's built-in mechanism for scheduling
#                   work to run after the response is sent.
#
# FastAPI — creates the API application.
#
# HTTPException — lets us return controlled HTTP errors such as
#                 400, 429, 500, or 503.
#
# Request — gives us access to the incoming HTTP request. The
#           rate limiter needs this to inspect headers/IP address.
#
# BaseModel — Pydantic base class used to define request schemas.
#
# field_validator — Pydantic decorator used to validate individual
#                   fields before our endpoint logic runs.
#
# slowapi — rate-limiting library for FastAPI/Starlette.
#
# Limiter — creates the rate limiter.
#
# _rate_limit_exceeded_handler — converts a rate-limit exception
#                                into a proper HTTP 429 response.
#
# RateLimitExceeded — exception raised when the configured limit
#                     is exceeded.
#
# get_remote_address — gets the caller's IP address.
#
# google.genai — Google's Gemini SDK.
#
# ClientError — represents client-side Gemini API errors, such as
#               a 4xx response.
#
# ServerError — represents server-side errors from Google's service.
# ============================================================

import logging
import os
import uuid

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from pydantic import BaseModel, field_validator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from google import genai
from google.genai.errors import ClientError, ServerError


# ============================================================
# Logging setup
# ============================================================
#
# Instead of using print(), we configure Python's logging system.
#
# INFO means normal informational messages will be shown.
# logger is then used throughout the application.
# ============================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api-wrapper")


# ============================================================
# 2. DEMO MODE TOGGLE
# ============================================================
#
# DEMO_MODE is read from an environment variable.
#
# If:
#
#     DEMO_MODE=true
#
# then:
#
#     DEMO_MODE == True
#
# and we do NOT create a real Gemini client.
#
# This is useful when testing the wrapper itself — especially
# rate limiting, validation, and webhooks — without needing a
# real Gemini API key or consuming API quota.
#
# On a normal laptop with a real GEMINI_API_KEY configured,
# DEMO_MODE can simply be left unset. In that case it defaults
# to "false", meaning the real Gemini client is created.
#
# .lower() makes TRUE, True, and true behave the same way.
# ============================================================

DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() == "true"

client = genai.Client() if not DEMO_MODE else None


# ============================================================
# 3. RATE LIMITER SETUP
# ============================================================
#
# First we need to answer:
#
#     "WHO should the rate limit apply to?"
#
# The function below determines the identity of the caller.
#
# If the caller sends:
#
#     X-API-Key: abc123
#
# then "abc123" becomes the rate-limit identity.
#
# If there is no X-API-Key header, we fall back to the caller's
# IP address.
#
# This means two different API keys can have separate rate-limit
# buckets even when they come from the same computer.
#
# For example:
#
#     API key A → 5 requests/minute
#     API key B → 5 requests/minute
#
# They do not share the same bucket.
#
# If no API key is supplied:
#
#     IP address → 5 requests/minute
# ============================================================

def get_api_key_or_ip(request: Request) -> str:
    api_key = request.headers.get("x-api-key")
    return api_key if api_key else get_remote_address(request)


# Create the rate limiter and tell slowapi to use our identity
# function for every incoming request.
limiter = Limiter(key_func=get_api_key_or_ip)


# ============================================================
# FastAPI application setup
# ============================================================
#
# FastAPI creates the actual web application.
#
# app.state.limiter = limiter
#     Stores the limiter on the FastAPI application so slowapi
#     can access it.
#
# add_exception_handler(...)
#     Tells FastAPI what to do when slowapi raises a
#     RateLimitExceeded exception.
#
# Without this handler, the exception would not be converted
# into the clean 429 response we want.
#
# For example, after exceeding 5 requests/minute, the caller
# can receive something like:
#
#     {
#         "error": "Rate limit exceeded: 5 per 1 minute"
#     }
# ============================================================

app = FastAPI(title="LLM API Wrapper")

app.state.limiter = limiter

app.add_exception_handler(
    RateLimitExceeded,
    _rate_limit_exceeded_handler,
)


# ============================================================
# 4. HEALTH CHECK
# ============================================================
#
# This endpoint does not call Gemini.
#
# Its only purpose is to answer:
#
#     "Is the API server alive and responding?"
#
# This is commonly used by monitoring systems, deployment
# platforms, load balancers, and health checks.
# ============================================================

@app.get("/health")
def health_check():
    """Basic liveness check — confirms the server is up and responding."""
    return {"status": "ok"}


# ============================================================
# 5. REQUEST SCHEMA + VALIDATION
# ============================================================
#
# Pydantic lets us define exactly what the /generate endpoint
# expects.
#
# The incoming JSON should look like:
#
#     {
#         "prompt": "Explain quantum computing"
#     }
#
# FastAPI automatically uses this model to parse and validate
# the request body.
#
# The field_validator adds one extra rule:
#
#     prompt cannot be empty or only whitespace.
#
# This is important because bad input should be rejected before
# it reaches the upstream Gemini API.
# ============================================================

class GenerateRequest(BaseModel):
    prompt: str

    @field_validator("prompt")
    @classmethod
    def prompt_not_empty(cls, v: str) -> str:
        # Catch bad input BEFORE it ever reaches the upstream API
        # or wastes an upstream model call.
        if not v or not v.strip():
            raise ValueError("prompt cannot be empty")

        return v


# ============================================================
# 6. call_gemini() — THE SHARED ERROR-HANDLING CORE
# ============================================================
#
# This function contains the actual Gemini API call.
#
# The important architectural idea is that the Gemini logic is
# centralized here instead of duplicated inside both endpoints.
#
# Both:
#
#     /generate
#
# and:
#
#     /generate/async
#
# need to call Gemini.
#
# If we wrote the Gemini call and all its error handling twice,
# we would eventually have two slightly different versions of
# the same logic.
#
# Instead, both endpoints simply call:
#
#     call_gemini(prompt)
#
# This function either:
#
#     1. returns generated text
#
# OR
#
#     2. raises an HTTPException with an appropriate status code.
#
# The endpoints therefore do not need to understand all the ways
# Gemini can fail.
# ============================================================

def call_gemini(prompt: str) -> str:
    """The actual model call, isolated in its own function so both
    the sync endpoint (/generate) and the async endpoint (/generate/async)
    can share the exact same error-handling logic instead of
    duplicating it in two places.

    Returns the generated text on success, or raises an HTTPException
    with a specific status code describing what went wrong.
    """

    # --------------------------------------------------------
    # Demo mode
    # --------------------------------------------------------
    #
    # When DEMO_MODE is enabled, we do not contact Gemini at all.
    #
    # Instead, we return a fake response. This lets us test the
    # wrapper's own behavior without needing an API key.
    # --------------------------------------------------------

    if DEMO_MODE:
        return f"[demo response] You said: {prompt}"


    # --------------------------------------------------------
    # Real Gemini request
    # --------------------------------------------------------
    #
    # Everything that could fail while communicating with Gemini
    # is wrapped in try/except blocks.
    # --------------------------------------------------------

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )

        return response.text


    # --------------------------------------------------------
    # Gemini ClientError
    # --------------------------------------------------------
    #
    # A ClientError generally represents a 4xx-style problem.
    #
    # One important example is HTTP 429:
    #
    #     "Too Many Requests"
    #
    # which means Gemini is rate limiting us.
    #
    # We distinguish 429 from other client errors because the
    # caller can reasonably retry a rate-limit error shortly.
    #
    # Other 4xx errors usually mean the request itself needs fixing
    # rather than simply being retried.
    # --------------------------------------------------------

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

        # Log the real Gemini error internally.
        logger.error(
            f"Gemini client error: code={e.code}, msg={e.message}"
        )

        # Return a safer, simpler message to the API caller.
        # We do not expose internal provider details unnecessarily.
        raise HTTPException(
            status_code=400,
            detail=(
                "Request was rejected by the AI service — "
                "check your input."
            ),
        )


    # --------------------------------------------------------
    # Gemini ServerError
    # --------------------------------------------------------
    #
    # This means the problem is on Google's side rather than
    # necessarily something wrong with our request.
    #
    # 503 is appropriate because the upstream service is
    # temporarily unavailable.
    # --------------------------------------------------------

    except ServerError:

        logger.error("Gemini server error")

        raise HTTPException(
            status_code=503,
            detail=(
                "AI service temporarily unavailable — "
                "please try again."
            ),
        )


    # --------------------------------------------------------
    # Unexpected errors
    # --------------------------------------------------------
    #
    # We also have a catch-all.
    #
    # This prevents an unexpected internal exception from:
    #
    #     - crashing the request unexpectedly
    #     - exposing implementation details to the caller
    #
    # logger.exception() records the full traceback in the logs,
    # which is useful for debugging.
    #
    # The caller receives only a safe generic message.
    # --------------------------------------------------------

    except Exception:

        logger.exception("Unexpected error calling Gemini")

        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred.",
        )


# ============================================================
# 7. SYNCHRONOUS /generate ENDPOINT
# ============================================================
#
# This is the normal request/response pattern.
#
# The caller sends:
#
#     POST /generate
#
# with:
#
#     {
#         "prompt": "Hello"
#     }
#
# The server then:
#
#     1. validates the request
#     2. checks the rate limit
#     3. calls Gemini
#     4. waits for Gemini's response
#     5. returns the result
#
# The caller therefore waits for the model generation to finish.
#
# The two decorators are important:
#
#     @app.post("/generate")
#
# registers the route.
#
#     @limiter.limit("5/minute")
#
# limits the route to 5 requests per minute per API key/IP.
# ============================================================

@app.post("/generate")
@limiter.limit("5/minute")
def generate(request: Request, req: GenerateRequest):

    # --------------------------------------------------------
    # Why is request: Request here if we don't use it?
    # --------------------------------------------------------
    #
    # slowapi's rate-limiting decorator needs access to the raw
    # Request object so it can inspect the caller's IP address
    # and/or API key header.
    #
    # FastAPI supplies the Request automatically because we
    # declared it as a parameter.
    # --------------------------------------------------------

    result = call_gemini(req.prompt)

    return {"result": result}


# ============================================================
# 8. ASYNC REQUEST SCHEMA
# ============================================================
#
# The asynchronous endpoint needs one additional piece of data:
#
#     callback_url
#
# The caller provides a URL where we should send the result after
# the background job finishes.
#
# Example:
#
#     {
#         "prompt": "Write a summary",
#         "callback_url": "https://example.com/webhook"
#     }
#
# The server accepts the job immediately, then later POSTs the
# result to the callback URL.
# ============================================================

class GenerateAsyncRequest(BaseModel):
    prompt: str

    # The caller's own endpoint.
    # We will POST the completed/failed result here.
    callback_url: str


    @field_validator("prompt")
    @classmethod
    def prompt_not_empty(cls, v: str) -> str:

        # Same basic validation as the synchronous endpoint:
        # reject empty or whitespace-only prompts.
        if not v or not v.strip():
            raise ValueError("prompt cannot be empty")

        return v


# ============================================================
# 9. run_job_and_notify() — THE BACKGROUND WORKER
# ============================================================
#
# This is NOT a route.
#
# It is a normal Python function that FastAPI will execute as a
# background task.
#
# The important concept is:
#
#     The caller has ALREADY received the response.
#
# The function then:
#
#     1. calls Gemini
#     2. creates a result payload
#     3. POSTs that payload to the callback URL
#
# This creates a webhook pattern.
#
# Normally:
#
#     Caller → our API → response
#
# Here:
#
#     Caller → our API → immediate "accepted"
#
#     ...later...
#
#     our API → caller's webhook URL → result
#
# Notice that our server becomes an HTTP client when it calls
# callback_url. We are no longer receiving a request; we are
# making an outbound request to someone else's server.
# ============================================================

def run_job_and_notify(
    job_id: str,
    prompt: str,
    callback_url: str,
):
    """Runs in the BACKGROUND, after the caller has already received
    their {"job_id": ..., "status": "accepted"} response and moved on.

    This function is the "call them back" half of the webhook pattern:

    1. Actually do the slow work (call_gemini).
    2. Package the outcome (success or failure) into a payload.
    3. POST that payload to whatever callback_url the caller gave us.

    This is the reverse direction of the normal API interaction:
    instead of the caller calling us, our server now calls them.
    """

    # --------------------------------------------------------
    # First try block: perform the actual model job.
    # --------------------------------------------------------

    try:

        result = call_gemini(prompt)

        # If Gemini succeeds, create a success payload.
        #
        # job_id allows the caller to know which original request
        # this webhook belongs to.
        payload = {
            "job_id": job_id,
            "status": "completed",
            "result": result,
        }


    # --------------------------------------------------------
    # If call_gemini() raises an HTTPException, we convert that
    # failure into a webhook payload instead of allowing the
    # background task to disappear silently.
    # --------------------------------------------------------

    except HTTPException as e:

        payload = {
            "job_id": job_id,
            "status": "failed",
            "error": e.detail,
        }


    # --------------------------------------------------------
    # Second try block: deliver the webhook.
    # --------------------------------------------------------
    #
    # At this point we have a payload regardless of whether the
    # Gemini call succeeded or failed.
    #
    # httpx.post() makes an outbound HTTP POST request to the
    # callback URL supplied by the caller.
    # --------------------------------------------------------

    try:

        httpx.post(
            callback_url,
            json=payload,
            timeout=10,
        )

        logger.info(
            f"Webhook delivered for job {job_id}"
        )


    # --------------------------------------------------------
    # Webhook delivery failure
    # --------------------------------------------------------
    #
    # This is a different failure from a Gemini failure.
    #
    # Gemini might have worked perfectly, but the caller's server
    # might be:
    #
    #     - offline
    #     - unreachable
    #     - using an invalid URL
    #     - timing out
    #
    # At this point the original caller has already received the
    # "accepted" response, so there is nobody waiting on this
    # request to notify.
    #
    # Therefore we log the problem.
    # --------------------------------------------------------

    except httpx.RequestError:

        logger.error(
            f"Failed to deliver webhook for job {job_id}"
        )


# ============================================================
# 10. ASYNCHRONOUS /generate/async ENDPOINT
# ============================================================
#
# This endpoint implements the "fire and forget" pattern.
#
# The caller sends a job, but does NOT wait for Gemini to finish.
#
# The flow is:
#
#     1. Receive request
#     2. Validate prompt + callback URL
#     3. Check rate limit
#     4. Generate a unique job ID
#     5. Schedule run_job_and_notify()
#     6. Immediately return "accepted"
#     7. Background task runs after the response
#     8. Gemini result is sent to callback_url
#
# The key line is:
#
#     background_tasks.add_task(...)
#
# That tells FastAPI:
#
#     "Run this function as background work after this request
#      has returned its response."
#
# The function does NOT execute the Gemini call before returning.
# ============================================================

@app.post("/generate/async")
@limiter.limit("5/minute")
def generate_async(
    request: Request,
    req: GenerateAsyncRequest,
    background_tasks: BackgroundTasks,
):

    # --------------------------------------------------------
    # Generate a unique ID for this job.
    #
    # UUIDs are useful because the caller can use job_id to
    # correlate the eventual webhook with the original request.
    # --------------------------------------------------------

    job_id = str(uuid.uuid4())


    # --------------------------------------------------------
    # Schedule the background task.
    #
    # We give FastAPI:
    #
    #     the function to run
    #     the job ID
    #     the prompt
    #     the callback URL
    #
    # FastAPI will execute run_job_and_notify() after this
    # endpoint returns its response.
    # --------------------------------------------------------

    background_tasks.add_task(
        run_job_and_notify,
        job_id,
        req.prompt,
        req.callback_url,
    )


    # --------------------------------------------------------
    # Respond immediately.
    #
    # The caller gets this before Gemini generation has finished.
    #
    # Example:
    #
    #     {
    #         "job_id": "a1b2c3...",
    #         "status": "accepted"
    #     }
    #
    # The caller can now continue doing other work.
    # Later, the webhook will tell them the actual outcome.
    # --------------------------------------------------------

    return {
        "job_id": job_id,
        "status": "accepted",
    }


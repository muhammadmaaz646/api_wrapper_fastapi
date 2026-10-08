# LLM API Wrapper — Setup Guide

This guide walks you through setting up and testing the FastAPI LLM wrapper, including:

- Gemini API integration
- Request validation
- Rate limiting
- Synchronous generation
- Asynchronous/background generation
- Webhook callbacks
- A local webhook receiver

The project will contain two small FastAPI applications:

```text
api-wrapper/
│
├── venv/
├── main.py
└── receiver.py
```

---

## 1. Check Python is installed

Open **Command Prompt or PowerShell** on Windows and run:

```bash
python --version
```

You need **Python 3.9 or newer**.

If `python` does not work, try:

```bash
py --version
```

If Python is missing or too old, install a current version from:

urlPython.orghttps://www.python.org/

---

## 2. Create a project folder and virtual environment

Create the project folder:

```bash
mkdir api-wrapper
cd api-wrapper
```

Then create a virtual environment:

```bash
python -m venv venv
```

A virtual environment keeps this project's Python packages isolated from other projects on your computer.

Activate it on Windows:

```bash
venv\Scripts\activate
```

You should now see something like:

```text
(venv) C:\Users\YourName\api-wrapper>
```

The `(venv)` tells you that the virtual environment is active.

---

## 3. Install the required packages

With the virtual environment active, run:

```bash
pip install fastapi uvicorn google-genai slowapi httpx
```

These packages have different jobs:

- **fastapi** — web framework used to build the API.
- **uvicorn** — runs the FastAPI application.
- **google-genai** — Google's official Gemini Python SDK.
- **slowapi** — adds rate limiting to the API.
- **httpx** — lets the API make outbound HTTP requests to webhook URLs.

---

## 4. Get a Gemini API key

Go to:

https://aistudio.google.com/apikey

Sign in with your Google account and create an API key.

Copy the key somewhere safe.

**Do not put the API key directly inside `main.py`.**

Keeping secrets out of source code makes the application safer and prevents accidentally committing the key to GitHub or another public repository.

---

## 5. Set the Gemini API key as an environment variable

### Windows Command Prompt

Run:

```bash
set GEMINI_API_KEY=your-key-here
```

Replace `your-key-here` with your actual Gemini API key.

You can verify it with:

```bash
echo %GEMINI_API_KEY%
```

### Windows PowerShell

Run:

```powershell
$env:GEMINI_API_KEY="your-key-here"
```

Verify it with:

```powershell
echo $env:GEMINI_API_KEY
```

The `google-genai` SDK automatically looks for the `GEMINI_API_KEY` environment variable.

### Important

The commands above set the variable for the current terminal session. If you close the terminal and open a new one, you may need to set it again unless you configure it as a permanent environment variable.

---

## 6. Create `main.py`

Place the annotated `main.py` file in your `api-wrapper` folder.

Your project should now look like:

```text
api-wrapper/
│
├── venv/
│
└── main.py
```

The `main.py` file contains:

- the FastAPI application
- Gemini integration
- request validation
- rate limiting
- error handling
- `/health`
- `/generate`
- `/generate/async`
- webhook handling
- demo mode

---

## 7. Run the main API server

Make sure you are inside the project folder and the virtual environment is active:

```bash
cd api-wrapper
venv\Scripts\activate
```

Then start the server:

```bash
uvicorn main:app --reload
```

You should see something similar to:

```text
Uvicorn running on http://127.0.0.1:8000
```

Leave this terminal running.

Your main API is now available at:

```text
http://127.0.0.1:8000
```

The `--reload` option automatically restarts the server when you modify `main.py`, which is useful during development.

---

## 8. Test the health endpoint

Open FastAPI's interactive documentation:

http://127.0.0.1:8000/docs

Find:

```text
GET /health
```

Click:

**Try it out → Execute**

You should receive:

```json
{
  "status": "ok"
}
```

This does not test Gemini. It simply confirms that the FastAPI server is alive and responding.

---

## 9. Test `/generate`

In the same `/docs` page, find:

```text
POST /generate
```

Click:

**Try it out**

Use this request body:

```json
{
  "prompt": "Explain what an API wrapper is in one paragraph."
}
```

Click **Execute**.

If your Gemini API key is configured correctly, you should receive something similar to:

```json
{
  "result": "An API wrapper is..."
}
```

The request flow is:

```text
Your request
     ↓
FastAPI
     ↓
Pydantic validation
     ↓
Rate limiter
     ↓
call_gemini()
     ↓
Gemini
     ↓
Response
```

This is the **synchronous** endpoint because the caller waits for Gemini to finish before receiving the final result.

---

## 10. Test request validation

Try sending an empty prompt:

```json
{
  "prompt": ""
}
```

Or a whitespace-only prompt:

```json
{
  "prompt": "   "
}
```

Pydantic's validator should reject the request.

This demonstrates an important API principle:

> Validate input before sending unnecessary or invalid requests to an upstream service.

---

## 11. Test rate limiting

The `/generate` endpoint contains:

```python
@limiter.limit("5/minute")
```

This means each API key/IP address can make **5 requests per minute** to that endpoint.

Send the `/generate` request 6 times quickly.

The first 5 should normally succeed.

The 6th should return an HTTP:

```text
429 Too Many Requests
```

This proves that the rate limiter is operating independently of Gemini.

The limiter identifies callers using:

```text
X-API-Key header
```

when provided.

If no API key header exists, it falls back to the caller's IP address.

---

# Webhook / Async Setup

The next part tests the second half of the project.

The `/generate/async` endpoint does not make the caller wait for Gemini.

Instead:

1. The caller submits a job.
2. The API generates a `job_id`.
3. The API schedules a background task.
4. The API immediately returns `status: accepted`.
5. Gemini runs in the background.
6. The result is POSTed to the supplied `callback_url`.

To test this locally, we need another small server to receive that callback.

---

## 12. Create `receiver.py`

Create a new file next to `main.py`:

```text
api-wrapper/
│
├── venv/
├── main.py
└── receiver.py
```

Put this code in `receiver.py`:

```python
from fastapi import FastAPI, Request

app = FastAPI(title="Webhook Receiver")


@app.post("/callback")
async def callback(request: Request):
    payload = await request.json()

    print("\n========== WEBHOOK RECEIVED ==========")
    print(payload)
    print("======================================\n")

    return {"status": "received"}
```

This is deliberately tiny.

Its only job is to:

1. Receive a POST request at `/callback`.
2. Read the JSON payload.
3. Print the payload in the terminal.
4. Tell the sender that the webhook was received.

---

## 13. Start the webhook receiver

Open a **second terminal window**.

Go into the project:

```bash
cd api-wrapper
```

Activate the virtual environment:

```bash
venv\Scripts\activate
```

Then start the receiver:

```bash
uvicorn receiver:app --port 9000
```

You should see:

```text
Uvicorn running on http://127.0.0.1:9000
```

You now have two servers running.

### Terminal 1

```text
main.py
http://127.0.0.1:8000
```

### Terminal 2

```text
receiver.py
http://127.0.0.1:9000
```

Keep both terminals running.

---

## 14. Test the async endpoint

Open:

http://127.0.0.1:8000/docs

Find:

```text
POST /generate/async
```

Click:

**Try it out**

Use:

```json
{
  "prompt": "Explain RAG in three sentences.",
  "callback_url": "http://127.0.0.1:9000/callback"
}
```

Click **Execute**.

You should immediately receive something similar to:

```json
{
  "job_id": "7c3d...",
  "status": "accepted"
}
```

Notice that you do **not** receive the Gemini answer here.

That is intentional.

The API has accepted the job and returned immediately.

---

## 15. Watch the receiver terminal

After Gemini finishes, the main API sends a POST request to:

```text
http://127.0.0.1:9000/callback
```

Your second terminal should print something similar to:

```text
========== WEBHOOK RECEIVED ==========
{'job_id': '7c3d...', 'status': 'completed', 'result': 'RAG stands for...'}
======================================
```

This proves the webhook flow is working.

The complete flow is:

```text
Client
  │
  │ POST /generate/async
  ▼
main.py :8000
  │
  │ immediately returns
  ▼
{"job_id": "...", "status": "accepted"}
  │
  │
  │ background task
  ▼
Gemini
  │
  │ result
  ▼
main.py
  │
  │ POST /callback
  ▼
receiver.py :9000
  │
  ▼
Print webhook payload
```

---

## 16. Understand the two endpoints

You now have two different ways of interacting with the same Gemini functionality.

### Synchronous

```text
POST /generate
```

The caller waits:

```text
Client
  ↓
API
  ↓
Gemini
  ↓
API
  ↓
Client receives result
```

Use this when the generation is expected to finish quickly and the caller needs the result immediately.

### Asynchronous + webhook

```text
POST /generate/async
```

The caller does not wait:

```text
Client
  ↓
API
  ↓
Client gets job_id immediately

       ↓ background work ↓

API
  ↓
Gemini
  ↓
API
  ↓
Webhook
  ↓
Client's receiver
```

This pattern is useful when the work may take longer or when the caller does not want to keep an HTTP request open while waiting.

---

# Demo Mode

## 17. Test the wrapper without Gemini

`main.py` includes a `DEMO_MODE` environment variable.

This allows you to test the wrapper's own logic without making a real Gemini API request.

In a **third terminal**, or after stopping the main server, run:

### Command Prompt

```bash
set DEMO_MODE=true
uvicorn main:app --reload
```

### PowerShell

```powershell
$env:DEMO_MODE="true"
uvicorn main:app --reload
```

Now `call_gemini()` will return a fake response such as:

```text
[demo response] You said: Hello
```

instead of contacting Gemini.

This is useful for testing:

- rate limiting
- request validation
- background tasks
- webhook delivery
- API routing

without consuming Gemini quota.

To return to normal Gemini mode, open a fresh terminal or set:

### Command Prompt

```bash
set DEMO_MODE=false
```

### PowerShell

```powershell
$env:DEMO_MODE="false"
```

Then restart Uvicorn.

---

# Final Project Structure

When everything is set up, your project should look like:

```text
api-wrapper/
│
├── venv/
│
├── main.py
│
└── receiver.py
```

And you should be able to run:

### Main API

```bash
uvicorn main:app --reload
```

on port:

```text
8000
```

### Webhook receiver

```bash
uvicorn receiver:app --port 9000
```

on port:

```text
9000
```

---

# Final Testing Checklist

Use this checklist to confirm the whole project works.

- [ ] Python 3.9+ installed
- [ ] Virtual environment created
- [ ] Virtual environment activated
- [ ] `fastapi` installed
- [ ] `uvicorn` installed
- [ ] `google-genai` installed
- [ ] `slowapi` installed
- [ ] `httpx` installed
- [ ] `GEMINI_API_KEY` configured
- [ ] `main.py` created
- [ ] `/health` returns `{"status": "ok"}`
- [ ] `/generate` returns Gemini text
- [ ] Empty prompts are rejected
- [ ] 6th request within a minute triggers `429`
- [ ] `receiver.py` created
- [ ] Receiver running on port `9000`
- [ ] `/generate/async` immediately returns a `job_id`
- [ ] Receiver eventually prints the webhook payload
- [ ] Demo mode works without calling Gemini

---

# What you've built

At this point, this is no longer just a Python script that calls Gemini.

You've built a small **LLM API wrapper** with:

```text
                    ┌────────────────────────┐
                    │       FastAPI API       │
                    └────────────┬───────────┘
                                 │
                  ┌──────────────┼──────────────┐
                  │              │              │
                  ▼              ▼              ▼
             Validation     Rate limiting    Logging
                  │              │              │
                  └──────────────┼──────────────┘
                                 │
                                 ▼
                         ┌───────────────┐
                         │ call_gemini() │
                         └───────┬───────┘
                                 │
                                 ▼
                            Gemini API
                                 │
                       ┌─────────┴─────────┐
                       │                   │
                       ▼                   ▼
                  /generate         /generate/async
                       │                   │
                       ▼                   ▼
                  Direct result       Background job
                                           │
                                           ▼
                                      Webhook POST
                                           │
                                           ▼
                                      receiver.py
```

The important engineering concepts demonstrated here are **separation of concerns, input validation, rate limiting, centralized error handling, background processing, and webhook-based asynchronous communication**.

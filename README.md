# Gemini FastAPI Orchestrator

> **The Problem:** If you just call an LLM directly in your code, you're stuck with a bunch of issues: you don't have proper error handling, there’s nothing stopping someone from spamming 100 requests a minute, and if the model takes two minutes to respond, your code just hangs there waiting. This wrapper acts as a safe, orchestrated intermediary to handle all that.

## 🏗️ Architecture

A production-patterned FastAPI service that wraps the Google Gemini API, providing critical reliability features like rate limiting, request validation, and asynchronous processing. 

I’ve got two ways to get the output, both with the same solid error handling and rate-limiting protection:
1. **Direct Call (Sync):** Answers immediately, but the code waits for the LLM to finish.
2. **Async (Background):** I send the prompt, get a `job_id` immediately, and the client polls for the result while the background task takes over.

```text
       ┌───────────┐        ┌──────────────┐        ┌─────────────┐
       │           │        │              │        │             │
       │  Client   │───────▶│   FastAPI    │───────▶│  Gemini API │
       │ (Browser) │  Sync  │  Application │  API   │  (Upstream) │
       └───────────┘        └──────┬───────┘        └─────────────┘
             │                     │
             │                     │
             │ Async               │
             └─────────────────────┤
                                   ▼
                            ┌──────────────┐
                            │ Background   │
                            │ Task (Worker)│
                            └──────┬───────┘
                                   │
                                   ▼
                            ┌──────────────┐
                            │  In-Memory   │◀─── Poll: GET /job/{id}
                            │    Store     │
                            └──────────────┘
```

---

## 🛠️ Tech Stack

- **Framework:** FastAPI
- **Web Server:** Uvicorn
- **AI SDK:** Google GenAI Python SDK
- **Rate Limiting:** SlowAPI
- **Data Validation:** Pydantic
- **Frontend:** Plain HTML/JS (Polling client)

---

## 💡 Decisions Made & Solved Problems

- **Polling vs. Webhooks:** While webhooks are the planned goal for server-to-server interaction, I implemented a **polling architecture** for this prototype. This allows browsers to reliably get async results without needing complex tunneling like `ngrok`. `receiver.py` is currently set up to act as a listener for future webhook integration.
- **Sync vs. Async:** Decoupled fast-request paths from slow, background-generated paths to prevent blocking the process.
- **Input Validation:** Enforced strict Pydantic rules to reject empty/whitespace prompts at the edge, saving costs and quota.
- **In-Memory Job Queue:** Managed async job state (pending/completed/failed) in-memory for simple prototyping.

---

## 🚀 Setup & How to Run

### Prerequisites

- Python 3.9+
- A Google Gemini API Key

### Installation

1. **Activate Virtual Environment**
   ```powershell
   .\venv\Scripts\activate
   ```

2. **Install Dependencies**
   ```powershell
   pip install fastapi uvicorn slowapi google-genai pydantic
   ```

3. **Set API Key (or use Demo Mode)**
   ```powershell
   # Use API Key
   $env:GEMINI_API_KEY="your-actual-api-key-here"
   
   # OR use Demo Mode (no API key required)
   $env:DEMO_MODE="true"
   ```

4. **Run Application**
   ```powershell
   uvicorn main:app --reload
   ```

5. **Access**
   Open your browser and navigate to: `http://127.0.0.1:8000`

# API Wrapper FastAPI

A FastAPI wrapper for the Gemini API.

## How to run

1.  Create a virtual environment:
    ```bash
    python -m venv venv
    ```
2.  Activate it:
    - Windows: `venv\Scripts\activate`
    - Mac/Linux: `source venv/bin/activate`
3.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
4.  Copy `.env.example` to `.env` and add your API key.
5.  Run the application:
    ```bash
    uvicorn main:app --reload
    ```

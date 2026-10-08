# We created receiver.py as a separate server only to demonstrate 
# the webhook part of your async design.
# main.py — your actual API
# receiver.py — pretending to be the customer's server
# It only exists so we have somewhere to send the webhook.
# In real life, you wouldn't create receiver.py as part of your API wrapper.
# The callback_url would belong to the customer using your API.

from fastapi import FastAPI, Request

app = FastAPI(title="Webhook Receiver")


@app.post("/callback")
async def callback(request: Request):
    payload = await request.json()

    print("\n========== WEBHOOK RECEIVED ==========")
    print(payload)
    print("======================================\n")

    return {"status": "received"}

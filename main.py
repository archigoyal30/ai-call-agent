import os
from typing import Optional
from fastapi import FastAPI, Request, Form, Query
from fastapi.responses import HTMLResponse
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Gather, Pause
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
NGROK_URL = os.getenv("NGROK_URL")
PORT = int(os.getenv("PORT", 5050))
TOURIST_NUMBER = os.getenv("TOURIST_NUMBER")
NOTIFICATION_NUMBER = os.getenv("NOTIFICATION_NUMBER", TWILIO_PHONE_NUMBER)

if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_PHONE_NUMBER and NGROK_URL):
    raise ValueError("Missing required Twilio or NGROK configuration in .env")

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


@app.get("/", response_class=HTMLResponse)
async def root():
    return {"message": "Twilio Call Agent is running."}


@app.post("/make-call")
async def make_call(to_phone_number: Optional[str] = Query(None)):
    to_number = to_phone_number or TOURIST_NUMBER
    if not to_number:
        return {"error": "No phone number provided and TOURIST_NUMBER not set in .env."}

    try:
        call = twilio_client.calls.create(
            url=f"{NGROK_URL}/outgoing-call",
            to=to_number,
            from_=TWILIO_PHONE_NUMBER,
        )
        return {"status": "call_initiated", "call_sid": call.sid}
    except Exception as e:
        return {"error": str(e)}


@app.api_route("/outgoing-call", methods=["GET", "POST"])
async def outgoing_call(request: Request):
    response = VoiceResponse()
    gather = Gather(
        input="dtmf",
        num_digits=1,
        action="/gather-handler",
        method="POST",
        timeout=10,
    )
    gather.say(
        "Hi there! This is a quick call to confirm your appointment. "
        "If you'd like to confirm, please press 1. "
        "If you need to cancel, press 2. "
        "Thank you!",
        voice="Polly.Joanna",
        language="en-US"
    )
    response.append(gather)
    response.say("I didn’t catch that. Goodbye for now.", voice="Polly.Joanna", language="en-US")
    response.pause(length=1)
    response.hangup()
    return HTMLResponse(content=str(response), media_type="application/xml")


@app.post("/gather-handler")
async def gather_handler(Digits: Optional[str] = Form(None), From: Optional[str] = Form(None)):
    digits = (Digits or "").strip()
    caller = From or ""
    response = VoiceResponse()

    if digits == "1":
        sms_body = f"Your appointment has been confirmed by {caller or 'the callee'}. See you soon!"
        voice_msg = "Perfect. Your appointment has been confirmed. We’ll see you soon. Goodbye!"
    elif digits == "2":
        sms_body = f"Your appointment has been cancelled by {caller or 'the callee'}."
        voice_msg = "Got it. Your appointment has been cancelled. Thank you, and have a great day!"
    else:
        sms_body = f"No valid response received by {caller or 'the callee'}."
        voice_msg = "I didn’t get a valid response. Please try again later. Goodbye!"

    try:
        twilio_client.messages.create(
            body=sms_body,
            from_=TWILIO_PHONE_NUMBER,
            to=NOTIFICATION_NUMBER,
        )
    except Exception as e:
        print("Error sending SMS:", e)

    response.say(voice_msg, voice="Polly.Joanna", language="en-US")
    response.pause(length=1)
    response.hangup()
    return HTMLResponse(content=str(response), media_type="application/xml")

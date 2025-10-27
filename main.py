import os
import json
import uuid
from datetime import datetime, timedelta
from typing import Optional
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, FileResponse
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Gather
from dotenv import load_dotenv
import requests

load_dotenv()

app = FastAPI()

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
NGROK_URL = os.getenv("NGROK_URL")
PORT = int(os.getenv("PORT", 5050))
TOURIST_NUMBER = os.getenv("TOURIST_NUMBER")
NOTIFICATION_NUMBER = os.getenv("NOTIFICATION_NUMBER", TWILIO_PHONE_NUMBER)
BARBER_NUMBER = os.getenv("BARBER_NUMBER", NOTIFICATION_NUMBER)

AZURE_TRANSLATOR_KEY = os.getenv("AZURE_TRANSLATOR_KEY")
AZURE_TRANSLATOR_REGION = os.getenv("AZURE_TRANSLATOR_REGION")
AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY")
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION")
AZURE_TTS_VOICE = os.getenv("AZURE_TTS_VOICE", "de-DE-KatjaNeural")

if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER, NGROK_URL, TOURIST_NUMBER]):
    raise ValueError("Missing required Twilio/NGROK/TOURIST configuration in .env")

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(STATIC_DIR, exist_ok=True)


def extract_appointment_from_text(text: str) -> Optional[dict]:
    text_lower = text.lower()
    now = datetime.now()
    appointment_dt = None
    # Simple rules: look for "tomorrow" and a time like "4pm" or "16:00"
    if "tomorrow" in text_lower:
        base = now + timedelta(days=1)
    else:
        base = now
    # find "4pm", "4 pm", "16:00", etc.
    import re
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text_lower)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        ampm = m.group(3)
        if ampm:
            ampm = ampm.lower()
            if ampm == "pm" and hour != 12:
                hour += 12
            if ampm == "am" and hour == 12:
                hour = 0
        appointment_dt = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if appointment_dt is None:
        return None
    return {"datetime": appointment_dt, "text": text}


def translate_text_to_german(text: str) -> str:
    endpoint = "https://api.cognitive.microsofttranslator.com/translate?api-version=3.0&to=de"
    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_TRANSLATOR_KEY,
        "Ocp-Apim-Subscription-Region": AZURE_TRANSLATOR_REGION,
        "Content-Type": "application/json",
    }
    body = [{"text": text}]
    resp = requests.post(endpoint, headers=headers, json=body, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    translated = data[0]["translations"][0]["text"]
    return translated


def synthesize_german_tts(ssml_text: str) -> str:
    tts_endpoint = f"https://{AZURE_SPEECH_REGION}.tts.speech.microsoft.com/cognitiveservices/v1"
    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_SPEECH_KEY,
        "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": "audio-16khz-128kbitrate-mono-mp3",
        "User-Agent": "appointment-confirmation-agent"
    }
    ssml = f"""
    <speak version='1.0' xml:lang='de-DE'>
      <voice xml:lang='de-DE' name='{AZURE_TTS_VOICE}'>
        {ssml_text}
      </voice>
    </speak>
    """
    resp = requests.post(tts_endpoint, headers=headers, data=ssml.encode("utf-8"), timeout=30)
    resp.raise_for_status()
    filename = f"{uuid.uuid4().hex}.mp3"
    path = os.path.join(STATIC_DIR, filename)
    with open(path, "wb") as f:
        f.write(resp.content)
    return filename


@app.get("/", response_class=HTMLResponse)
async def root():
    return {"message": "Appointment voice flow service is online."}


@app.post("/simulate-customer")
async def simulate_customer():
    customer_text = "book an appointment for 4pm tomorrow."
    appt = extract_appointment_from_text(customer_text)
    if not appt:
        return {"error": "Could not extract appointment from text."}
    # Build a polite sentence in German to play to the barber
    en_sentence = f"I would like to book an appointment for {appt['datetime'].strftime('%A %b %d at %I:%M %p')}."
    # Translate to German
    try:
        german = translate_text_to_german(en_sentence)
    except Exception as e:
        return {"error": f"Translation failed: {str(e)}"}
    # Add explicit instruction for barber to press 1 to confirm or 2 to reject
    german_with_prompt = f"{german} Bitte drücken Sie die Taste 1, um den Termin zu bestätigen, oder die Taste 2, um ihn abzulehnen."
    try:
        filename = synthesize_german_tts(german_with_prompt)
    except Exception as e:
        return {"error": f"TTS failed: {str(e)}"}
    audio_url = f"{NGROK_URL}/audio/{filename}"
    # Make call to barber and instruct Twilio to play the generated audio then gather DTMF
    try:
        call = twilio_client.calls.create(
            url=f"{NGROK_URL}/outgoing-to-barber?audio={filename}",
            to=BARBER_NUMBER,
            from_=TWILIO_PHONE_NUMBER,
        )
    except Exception as e:
        return {"error": f"Twilio call failed: {str(e)}"}
    return {
        "status": "barber_call_initiated",
        "call_sid": call.sid,
        "audio_url": audio_url,
        "appointment": appt["datetime"].isoformat()
    }


@app.get("/audio/{filename}")
async def serve_audio(filename: str):
    path = os.path.join(STATIC_DIR, filename)
    if not os.path.isfile(path):
        return {"error": "file not found"}
    return FileResponse(path, media_type="audio/mpeg")


@app.api_route("/outgoing-to-barber", methods=["GET", "POST"])
async def outgoing_to_barber(request: Request):
    filename = request.query_params.get("audio")
    if not filename:
        return HTMLResponse(content="<Response><Say>Missing audio file</Say></Response>", media_type="application/xml")
    audio_url = f"{NGROK_URL}/audio/{filename}"
    resp = VoiceResponse()
    resp.play(audio_url)
    gather = Gather(input="dtmf", num_digits=1, action="/barber-response", method="POST", timeout=15)
    resp.append(gather)
    resp.say("Keine Antwort erhalten. Auf Wiedersehen.")  # fallback in German
    resp.hangup()
    return HTMLResponse(content=str(resp), media_type="application/xml")


@app.post("/barber-response")
async def barber_response(Digits: Optional[str] = Form(None), From: Optional[str] = Form(None)):
    digits = (Digits or "").strip()
    barber = From or BARBER_NUMBER
    if digits == "1":
        customer_msg = f"Your appointment was confirmed by the barber ({barber})."
        barber_reply = "Vielen Dank. Der Termin wurde bestätigt. Auf Wiedersehen."
    elif digits == "2":
        customer_msg = f"Your appointment was rejected by the barber ({barber})."
        barber_reply = "Der Termin wurde abgelehnt. Auf Wiedersehen."
    else:
        customer_msg = f"No valid response received from barber ({barber})."
        barber_reply = "Ich habe keine gültige Eingabe erhalten. Auf Wiedersehen."

    try:
        twilio_client.messages.create(
            body=customer_msg,
            from_=TWILIO_PHONE_NUMBER,
            to=TOURIST_NUMBER,
        )
    except Exception as e:
        print("SMS to customer failed:", e)

    resp = VoiceResponse()
    resp.say(barber_reply, language="de-DE")
    resp.pause(length=1)
    resp.hangup()
    return HTMLResponse(content=str(resp), media_type="application/xml")

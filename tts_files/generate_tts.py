import os
from azure.cognitiveservices.speech import SpeechConfig, SpeechSynthesizer, AudioConfig
from dotenv import load_dotenv

load_dotenv()

AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY")
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION")

speech_text = "Ich möchte morgen um 16 Uhr einen Haarschnitt."  # German translation of "I want a haircut tomorrow at 4 PM"
filename = "tts_files/barber_message.wav"

speech_config = SpeechConfig(subscription=AZURE_SPEECH_KEY, region=AZURE_SPEECH_REGION)
audio_config = AudioConfig(filename=filename)

synthesizer = SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)
synthesizer.speak_text(speech_text)

print(f"TTS file created: {filename}")

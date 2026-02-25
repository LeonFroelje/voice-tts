import os
import json
import wave
import logging
import asyncio
import hashlib
import tempfile
import urllib.request
from typing import Dict

import boto3
import aiomqtt
from botocore.exceptions import ClientError
from piper import PiperVoice

from config import settings

# --- Logging Setup ---
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("TTSWorker")

loaded_voices: Dict[str, PiperVoice] = {}
os.makedirs(settings.models_dir, exist_ok=True)


# --- Piper Logic ---
def download_piper_model(model_name: str):
    """Downloads the ONNX and JSON config for a Piper voice if missing."""
    base_url = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
    parts = model_name.split("-")
    if len(parts) < 3:
        raise ValueError(f"Invalid Piper model name format: {model_name}")

    lang_family, lang_code, dataset, quality = (
        parts[0].split("_")[0],
        parts[0],
        parts[1],
        parts[2],
    )
    onnx_url = (
        f"{base_url}/{lang_family}/{lang_code}/{dataset}/{quality}/{model_name}.onnx"
    )
    json_url = f"{onnx_url}.json"

    onnx_path = os.path.join(settings.models_dir, f"{model_name}.onnx")
    json_path = os.path.join(settings.models_dir, f"{model_name}.onnx.json")

    if not os.path.exists(onnx_path):
        logger.info(f"Downloading {model_name}.onnx from Hugging Face...")
        urllib.request.urlretrieve(onnx_url, onnx_path)
    if not os.path.exists(json_path):
        logger.info(f"Downloading {model_name}.onnx.json from Hugging Face...")
        urllib.request.urlretrieve(json_url, json_path)

    return onnx_path, json_path


def get_voice(voice_name: str) -> PiperVoice:
    """Gets a cached voice or loads it, downloading it if necessary."""
    piper_model_name = voice_name.strip()
    if piper_model_name not in loaded_voices:
        onnx_path, _ = download_piper_model(piper_model_name)
        logger.info(f"Loading '{piper_model_name}' into memory...")
        loaded_voices[piper_model_name] = PiperVoice.load(onnx_path)
    return loaded_voices[piper_model_name]


# --- Synthesis & S3 Logic ---
def synthesize_and_upload(text: str) -> str:
    """Checks S3 cache, synthesizes if missing, uploads, and returns URL."""
    # Create a deterministic filename based on the text and voice
    text_hash = hashlib.md5(
        f"{settings.default_voice}_{text}".encode("utf-8")
    ).hexdigest()
    filename = f"tts_{text_hash}.wav"

    s3_client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        region_name="garage",
        config=boto3.session.Config(signature_version="s3v4"),
    )

    # 1. Check if the audio already exists in S3 (Cache Hit)
    try:
        s3_client.head_object(Bucket=settings.s3_bucket, Key=filename)
        logger.info(f"Cache hit for text: '{text[:30]}...'. Skipping synthesis.")
        return filename
    except ClientError as e:
        if e.response["Error"]["Code"] == "404":
            pass  # File doesn't exist, proceed to generate
        else:
            logger.error(f"S3 Check Error: {e}")

    # 2. Generate Audio (Cache Miss)
    logger.info(f"Synthesizing new audio for: '{text[:30]}...'")
    voice = get_voice(settings.default_voice)
    fd_wav, temp_wav = tempfile.mkstemp(suffix=".wav")
    os.close(fd_wav)

    try:
        with wave.open(temp_wav, "wb") as wav_file:
            voice.synthesize_wav(text, wav_file)

        # 3. Upload to S3
        s3_client.upload_file(
            temp_wav,
            settings.s3_bucket,
            filename,
            ExtraArgs={"ContentType": "audio/wav"},
        )
        return filename

    finally:
        if os.path.exists(temp_wav):
            os.remove(temp_wav)


# --- MQTT Loop ---
async def main_async():
    logger.info(f"Pre-loading default voice: {settings.default_voice}")
    get_voice(settings.default_voice)

    try:
        async with aiomqtt.Client(
            settings.mqtt_host, port=settings.mqtt_port
        ) as client:
            logger.info(
                f"Connected to MQTT Broker at {settings.mqtt_host}:{settings.mqtt_port}"
            )

            await client.subscribe("voice/tts/generate")
            logger.info("Listening for tasks on 'voice/tts/generate'...")

            async for message in client.messages:
                payload = json.loads(message.payload.decode())
                room = payload.get("room")
                text = payload.get("text")

                if not room or not text:
                    logger.warning("Received invalid payload missing 'room' or 'text'.")
                    continue

                try:
                    # Run blocking synthesis/upload in background thread
                    filename = await asyncio.to_thread(synthesize_and_upload, text)

                    if filename:
                        # Construct the action payload exactly as the satellite expects it
                        action_payload = {
                            "actions": [
                                {
                                    "type": "play_audio",
                                    "payload": {"filename": filename},
                                }
                            ]
                        }

                        # Publish back to the specific satellite's action topic
                        logger.info(
                            f"Publishing audio action to satellite/{room}/action"
                        )
                        await client.publish(
                            f"satellite/{room}/action",
                            payload=json.dumps(action_payload),
                        )

                except Exception as e:
                    logger.error(f"Failed to generate TTS for {room}: {e}")

    except aiomqtt.MqttError as error:
        logger.error(f"MQTT Error: {error}")
    except KeyboardInterrupt:
        logger.info("Shutting down TTS worker...")
    finally:
        loaded_voices.clear()


def main():
    """Synchronous wrapper for the setuptools entry point."""
    import asyncio

    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        pass

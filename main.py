import os
import wave
import logging
import urllib.request
import tempfile
import subprocess
import uvicorn
from contextlib import asynccontextmanager
from typing import Dict

from starlette.background import BackgroundTask
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from piper import PiperVoice

from config import settings

# ==========================================
# LOGGING SETUP
# ==========================================
# Configure standard logging format
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("piper_api")

loaded_voices: Dict[str, PiperVoice] = {}
os.makedirs(settings.models_dir, exist_ok=True)


def download_piper_model(model_name: str):
    """Downloads the ONNX and JSON config for a Piper voice if missing."""
    base_url = "https://huggingface.co/rhasspy/piper-voices/resolve/main"

    parts = model_name.split("-")
    if len(parts) < 3:
        raise ValueError(
            f"Invalid Piper model name format (e.g., de_DE-thorsten-high): {model_name}"
        )

    lang_family = parts[0].split("_")[0]  # 'de'
    lang_code = parts[0]  # 'de_DE'
    dataset = parts[1]  # 'thorsten'
    quality = parts[2]  # 'high'

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
        try:
            onnx_path, json_path = download_piper_model(piper_model_name)
            logger.info(f"Loading '{piper_model_name}' into memory...")
            loaded_voices[piper_model_name] = PiperVoice.load(onnx_path)
        except Exception as e:
            logger.error(
                f"Failed to load voice '{piper_model_name}': {e}", exc_info=True
            )
            raise HTTPException(
                status_code=400,
                detail=f"Failed to load voice '{piper_model_name}': {str(e)}",
            )

    return loaded_voices[piper_model_name]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Pre-load the default German voice on startup
    logger.info(f"Pre-loading default voice: {settings.default_voice}")
    get_voice(settings.default_voice)
    yield
    logger.info("Clearing loaded voices from memory during shutdown...")
    loaded_voices.clear()


app = FastAPI(title="Piper TTS API", lifespan=lifespan)


class SpeechRequest(BaseModel):
    input: str
    voice: str = settings.default_voice  # Defaults to de_DE-thorsten-high
    response_format: str = "wav"
    speed: float = 1.0


@app.post("/v1/audio/speech")
async def create_speech(request: SpeechRequest):
    if not request.input.strip():
        logger.warning("Received empty input text for TTS generation.")
        raise HTTPException(status_code=400, detail="Input text cannot be empty")

    logger.debug(
        f"Received TTS request | Voice: {request.voice} | Format: {request.response_format} | Text: '{request.input[:50]}...'"
    )

    voice = get_voice(request.voice)

    fd_wav, temp_wav = tempfile.mkstemp(suffix=".wav")
    os.close(fd_wav)

    try:
        # Synthesize audio
        with wave.open(temp_wav, "wb") as wav_file:
            voice.synthesize_wav(request.input, wav_file)

        logger.debug(f"Successfully synthesized WAV to {temp_wav}")

        # 1. Return WAV immediately and clean it up automatically
        if request.response_format.lower() == "wav":
            return FileResponse(
                temp_wav,
                media_type="audio/wav",
                background=BackgroundTask(os.remove, temp_wav),
            )

        # 2. Convert to MP3
        logger.debug(f"Converting WAV to {request.response_format.upper()}...")
        fd_mp3, temp_mp3 = tempfile.mkstemp(suffix=f".{request.response_format}")
        os.close(fd_mp3)

        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                temp_wav,
                "-vn",
                "-ar",
                "24000",
                "-ac",
                "1",
                "-b:a",
                "64k",
                temp_mp3,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Cleanup logic for MP3 conversion
        def cleanup_files():
            if os.path.exists(temp_wav):
                os.remove(temp_wav)
            if os.path.exists(temp_mp3):
                os.remove(temp_mp3)

        content_type = (
            f"audio/{request.response_format}"
            if request.response_format != "mp3"
            else "audio/mpeg"
        )
        return FileResponse(
            temp_mp3, media_type=content_type, background=BackgroundTask(cleanup_files)
        )

    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg conversion failed: {e}")
        if os.path.exists(temp_wav):
            os.remove(temp_wav)
        raise HTTPException(status_code=500, detail="Audio format conversion failed.")

    except Exception as e:
        logger.error(f"Error during TTS generation: {e}", exc_info=True)
        if os.path.exists(temp_wav):
            os.remove(temp_wav)
        raise HTTPException(status_code=500, detail=str(e))


def main():
    logger.info(f"Starting Piper TTS API on {settings.host}:{settings.port}...")
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()

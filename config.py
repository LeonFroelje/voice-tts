import argparse
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PiperSettings(BaseSettings):
    host: str = Field(default="127.0.0.1", description="Hostname or IP to bind to")
    port: int = Field(default=8080, description="Port for the FastAPI server")
    models_dir: str = Field(
        default="./models", description="Directory for Piper ONNX files"
    )

    # We default directly to a German voice instead of an OpenAI mapping
    default_voice: str = Field(
        default="de_DE-thorsten-high",
        description="The default Piper voice model to use and preload",
    )

    log_level: str = "INFO"
    model_config = SettingsConfigDict(env_prefix="PIPER_")


def get_settings() -> PiperSettings:
    parser = argparse.ArgumentParser(description="Piper TTS API Server Configuration")
    parser.add_argument("--host", help="Hostname or IP")
    parser.add_argument("--port", type=int, help="Port")
    parser.add_argument("--models-dir", help="Directory cache for Piper models")
    parser.add_argument("--default-voice", help="Default Piper voice model")
    parser.add_argument("--log-level", help="Logging Level")

    args, unknown = parser.parse_known_args()
    cli_args = {k.replace("-", "_"): v for k, v in vars(args).items() if v is not None}
    return PiperSettings(**cli_args)


settings = get_settings()

import argparse
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class PiperSettings(BaseSettings):
    # --- MQTT Connection ---
    mqtt_host: str = Field(
        default="localhost", description="Mosquitto broker IP/Hostname"
    )
    mqtt_port: int = Field(default=1883, description="Mosquitto broker port")

    # --- Object Storage (S3 Compatible) ---
    s3_endpoint: str = Field(
        default="http://localhost:3900", description="URL to S3 storage"
    )
    s3_access_key: str = Field(default="your-access-key", description="S3 Access Key")
    s3_secret_key: SecretStr = Field(
        default="your-secret-key", description="S3 Secret Key"
    )
    s3_bucket: str = Field(default="voice-commands", description="S3 Bucket Name")

    # --- Piper Models ---
    models_dir: str = Field(
        default="./models", description="Directory for Piper ONNX files"
    )
    default_voice: str = Field(
        default="de_DE-thorsten-high",
        description="The default Piper voice model to use and preload",
    )

    # --- System ---
    log_level: str = "INFO"
    model_config = SettingsConfigDict(env_prefix="PIPER_")


def get_settings() -> PiperSettings:
    parser = argparse.ArgumentParser(description="Piper TTS Worker")

    parser.add_argument("--mqtt-host", help="Mosquitto broker IP")
    parser.add_argument("--mqtt-port", type=int, help="Mosquitto broker port")
    parser.add_argument("--s3-endpoint", help="URL to S3 storage")
    parser.add_argument("--s3-access-key", help="S3 Access Key")
    parser.add_argument("--s3-secret-key", help="S3 Secret Key")
    parser.add_argument("--s3-bucket", help="S3 Bucket Name")

    parser.add_argument("--models-dir", help="Directory cache for Piper models")
    parser.add_argument("--default-voice", help="Default Piper voice model")
    parser.add_argument("--log-level", help="Logging Level")

    args, unknown = parser.parse_known_args()
    cli_args = {k.replace("-", "_"): v for k, v in vars(args).items() if v is not None}
    return PiperSettings(**cli_args)


settings = get_settings()

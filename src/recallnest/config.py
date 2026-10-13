"""Environment configuration. Connection secrets are never public entity data."""
from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    host: str = "127.0.0.1"
    port: int = 8787
    max_upload_bytes: int = 32 * 1024 * 1024
    max_zip_bytes: int = 128 * 1024 * 1024
    max_zip_members: int = 1000
    api_key: str = ""
    base_url: str = ""
    chat_model: str = ""
    embedding_model: str = ""

    def __post_init__(self):
        from .provider_settings import SettingsInput
        try:
            SettingsInput.model_validate({key: getattr(self, key) for key in ("api_key", "base_url", "chat_model", "embedding_model")})
        except ValueError:
            raise ValueError("Provider settings are invalid; check URL and connection fields") from None
        if min(self.max_upload_bytes, self.max_zip_bytes, self.max_zip_members) <= 0:
            raise ValueError("Import limits must be positive integers")

    @property
    def model_configured(self) -> bool:
        return bool(self.base_url and self.chat_model)


def get_settings(data_dir=None) -> Settings:
    return Settings(
        data_dir=Path(data_dir or os.environ.get("RECALLNEST_DATA_DIR", Path.home() / ".recallnest")).expanduser(),
        api_key=os.environ.get("RECALLNEST_API_KEY", ""),
        base_url=os.environ.get("RECALLNEST_BASE_URL", ""),
        chat_model=os.environ.get("RECALLNEST_CHAT_MODEL", ""),
        embedding_model=os.environ.get("RECALLNEST_EMBEDDING_MODEL", ""),
        max_upload_bytes=int(os.environ.get("RECALLNEST_MAX_UPLOAD_BYTES", 32 * 1024 * 1024)),
        max_zip_bytes=int(os.environ.get("RECALLNEST_MAX_ZIP_BYTES", 128 * 1024 * 1024)),
        max_zip_members=int(os.environ.get("RECALLNEST_MAX_ZIP_MEMBERS", 1000)),
    )

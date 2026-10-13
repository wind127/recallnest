"""Server-owned connection settings. Public representations never contain a key."""
from dataclasses import replace
import json
import os
import threading
from urllib.parse import urlsplit
from pydantic import Field, field_validator
from .models import StrictModel


CONNECTION_FIELDS = ("base_url", "api_key", "chat_model", "embedding_model")


def validate_base_url(value):
    if not value:
        return value
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment or parsed.netloc.endswith(":")
                or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value) or "\\" in value or
                (parsed.port is not None and not 1 <= parsed.port <= 65535)):
            raise ValueError()
    except ValueError:
        raise ValueError("Provider base URL must be HTTP(S), with no credentials, query or fragment") from None
    return value.rstrip("/")


class SettingsInput(StrictModel):
    base_url: str = Field(default="", max_length=2048)
    api_key: str = Field(default="", max_length=4096)
    chat_model: str = Field(default="", max_length=200)
    embedding_model: str = Field(default="", max_length=200)

    @field_validator("base_url")
    @classmethod
    def safe_url(cls, value):
        return validate_base_url(value)

    @field_validator("api_key", "chat_model", "embedding_model")
    @classmethod
    def no_controls(cls, value):
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Connection fields must not contain control characters")
        return value


class ConnectionSettings:
    def __init__(self, initial, *, load_saved=True):
        self._lock = threading.RLock()
        self.path = initial.data_dir / "provider-settings.json"
        self._settings = initial
        self.verified = False
        if load_saved and self.path.is_file():
            try:
                saved = SettingsInput.model_validate(json.loads(self.path.read_text(encoding="utf-8"))).model_dump()
            except (OSError, ValueError):
                raise ValueError("Saved provider settings are invalid; repair provider-settings.json") from None
            # Explicit environment fields override saved values without exposing their contents.
            for name in CONNECTION_FIELDS:
                if "RECALLNEST_" + name.upper() in os.environ:
                    saved[name] = getattr(initial, name)
            self._settings = replace(initial, **saved)

    def current(self):
        with self._lock:
            return self._settings

    def public(self):
        settings = self.current()
        return {"base_url": settings.base_url, "chat_model": settings.chat_model,
                "embedding_model": settings.embedding_model, "has_api_key": bool(settings.api_key),
                "model_configured": settings.model_configured, "connection_verified": self.verified,
                "storage": "server_file"}

    def mark_verified(self, settings):
        with self._lock:
            if settings != self._settings:
                return False
            self.verified = True
            return True

    def save(self, changes):
        with self._lock:
            settings = replace(self._settings, **changes)
            values = SettingsInput.model_validate({field: getattr(settings, field) for field in CONNECTION_FIELDS}).model_dump()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            try:
                with temporary.open("w", encoding="utf-8") as handle:
                    try:
                        os.chmod(temporary, 0o600)
                    except OSError:
                        pass
                    json.dump(values, handle, ensure_ascii=False)
                    handle.flush()
                    os.fsync(handle.fileno())
                temporary.replace(self.path)
                try:
                    os.chmod(self.path, 0o600)
                except OSError:
                    pass
            except OSError:
                raise ValueError("Could not save provider settings") from None
            self._settings = replace(settings, **values)
            self.verified = False
            return self.public()

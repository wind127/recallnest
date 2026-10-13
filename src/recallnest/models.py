"""Validated input and normalization contracts; public IDs are opaque strings."""
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator, create_model
from .json_utils import validate_json_numbers, validate_source_metadata


def utc_iso(value=None) -> str:
    try:
        validate_json_numbers(value)
        if value is None:
            value = datetime.now(timezone.utc)
        elif isinstance(value, (float, int)):
            value = datetime.fromtimestamp(value, timezone.utc)
        elif isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if not isinstance(value, datetime):
            raise ValueError()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    except (ValueError, OverflowError, OSError):
        raise ValueError("timestamp must be a valid ISO 8601 date or epoch seconds within the supported range") from None


class JsonModel(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def finite_numbers(cls, value):
        return validate_json_numbers(value)


class StrictModel(JsonModel):
    model_config = ConfigDict(extra="forbid")


class SourceModel(JsonModel):
    @field_validator("metadata", check_fields=False)
    @classmethod
    def reserved_metadata(cls, value):
        return validate_source_metadata(value)


class NormalizedMessage(SourceModel):
    id: str | None = None
    role: Literal["user", "assistant", "system", "developer", "tool"]
    content: str
    timestamp: str | None = None
    parent_id: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp", mode="before")
    @classmethod
    def normalize_time(cls, value):
        return utc_iso(value) if value is not None else None


class MessageInput(NormalizedMessage):
    """Strict REST message shape; source import archives remain permissive."""
    model_config = ConfigDict(extra="forbid")


class NormalizedConversation(SourceModel):
    source: str = "manual"
    source_identity: str | None = None
    external_id: str | None = None
    title: str = "Untitled"
    created_at: str | None = None
    updated_at: str | None = None
    current_node: str | None = None
    project_id: str | None = None
    messages: list[NormalizedMessage] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def normalize_time(cls, value):
        return utc_iso(value) if value is not None else None


class Evidence(StrictModel):
    message_id: str
    quote: str = Field(min_length=1)
    conversation_id: str | None = None
    message_version: int | None = Field(default=None, gt=0, strict=True)


class KnowledgeInput(StrictModel):
    title: str = Field(min_length=1)
    summary: str = ""
    body: str = ""
    type: str = "note"
    tags: list[str] = Field(default_factory=list)
    project_id: str | None = None
    favorite: bool = False
    unresolved: bool = False
    evidence: list[Evidence] = Field(default_factory=list)
    source: str = "manual"


class ArtifactLink(StrictModel):
    title: str = ""
    url: str = Field(min_length=1)

    @field_validator("url")
    @classmethod
    def web_url(cls, value):
        try:
            parsed = urlsplit(value)
            port = parsed.port
            if (parsed.scheme not in ("https", "http") or not parsed.hostname
                    or parsed.netloc.endswith(":") or any(char.isspace() for char in value) or "\\" in value
                    or (port is not None and not 1 <= port <= 65535)):
                raise ValueError()
        except ValueError:
            raise ValueError("artifact URL must be a complete http or https URL with a host and valid port") from None
        return value


class ProjectInput(StrictModel):
    name: str = Field(min_length=1)
    description: str = ""
    status: Literal["active", "paused", "completed", "archived"] = "active"
    goals: list[str] = Field(default_factory=list)
    artifact_links: list[ArtifactLink] = Field(default_factory=list)


class MemoryInput(StrictModel):
    content: str = Field(min_length=1)
    category: Literal["preference", "background", "goal", "state", "constraint"]
    subject: str = ""
    status: Literal["candidate", "confirmed", "rejected", "expired", "superseded"] = "candidate"
    supersedes: str | None = None
    effective_at: str | None = None
    expires_at: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    source: Literal["manual", "extracted", "demo"] = "manual"

    @field_validator("effective_at", "expires_at", mode="before")
    @classmethod
    def normalize_time(cls, value):
        return utc_iso(value) if value is not None else None


class ReviewInput(StrictModel):
    question: str = Field(min_length=1)
    answer: str = ""
    knowledge_id: str | None = None
    project_id: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    due_at: str | None = None
    paused: bool = False
    source: str = "manual"

    @field_validator("due_at", mode="before")
    @classmethod
    def normalize_time(cls, value):
        return utc_iso(value) if value is not None else None


class ConversationInput(StrictModel):
    source: str = "manual"
    source_identity: str | None = None
    external_id: str | None = None
    title: str = "Untitled"
    project_id: str | None = None
    current_node: str | None = None
    messages: list[MessageInput] = Field(default_factory=list)


class AppendInput(StrictModel):
    messages: list[MessageInput]
    current_node: str | None = None


class GradeInput(StrictModel):
    grade: Literal["again", "hard", "good", "easy"]


class FavoriteInput(StrictModel):
    favorite: bool


def patch_model(name, base):
    return create_model(name, __base__=base, **{
        key: (field.annotation | None, None) for key, field in base.model_fields.items()
    })


KnowledgePatch = patch_model("KnowledgePatch", KnowledgeInput)
ProjectPatch = patch_model("ProjectPatch", ProjectInput)
MemoryPatch = patch_model("MemoryPatch", MemoryInput)
ReviewPatch = patch_model("ReviewPatch", ReviewInput)


class ConversationPatch(StrictModel):
    title: str | None = None
    project_id: str | None = None
    current_node: str | None = None

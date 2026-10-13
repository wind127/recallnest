"""Bounded extraction schema and conservative, source-linked candidate screening."""
import re
from typing import Literal
from pydantic import Field
from .models import StrictModel, Evidence


class Citation(Evidence):
    message_id: str = Field(min_length=1, max_length=200)
    quote: str = Field(min_length=1, max_length=4000)
    message_version: int = Field(gt=0, strict=True)


class Knowledge(StrictModel):
    title: str = Field(min_length=1, max_length=300)
    summary: str = Field(max_length=2000)
    body: str = Field(max_length=8000)
    type: Literal["summary", "topic", "qa", "decision", "unresolved"]
    tags: list[str] = Field(max_length=20)
    evidence: list[Citation] = Field(min_length=1, max_length=20)


class Memory(StrictModel):
    content: str = Field(min_length=1, max_length=2000)
    category: Literal["preference", "background", "goal", "state", "constraint"]
    subject: str = Field(max_length=200)
    evidence: list[Citation] = Field(min_length=1, max_length=20)


class Review(StrictModel):
    question: str = Field(min_length=1, max_length=1000)
    answer: str = Field(max_length=4000)
    evidence: list[Citation] = Field(min_length=1, max_length=20)


class Extraction(StrictModel):
    knowledge: list[Knowledge] = Field(max_length=30)
    memories: list[Memory] = Field(max_length=20)
    reviews: list[Review] = Field(max_length=30)


def normalized(value):
    return " ".join(value.casefold().split())


def assertive_personal_quote(value):
    # A conservative gate, not a truth detector. False negatives stay in the archive.
    if re.search(r"[?？]|吗|嗎|么|麼|是不是|要不要|是否|能否|如果|假如|例如|比如|假设|假設|据说|聽說|听说|有人|他说|她说|if\b|suppose\b|example\b|might\b|could\b|would\b", value, re.I):
        return False
    if any(c in value for c in '"“”「」『』`'):
        return False
    return bool(re.search(r"(?:^|[。！.!\n])\s*(?:我(?:的|偏好|喜欢|喜歡|是|在|正在|计划|計劃|希望|想|需要|不|有|已)|I\s+(?:am|prefer|like|want|need|have|work|study)|My\s+)", value, re.I))


def explicit_personal_claim(value):
    return bool(re.search(r"(?:用户|你|我)(?:是|喜欢|喜歡|偏好|在|正在|有|计划|計劃|想|希望|需要|的(?:职业|姓名|年龄|背景|偏好|目标|状态))|"
        r"\b(?:user|you|I)\s+(?:is|are|am|has|have|prefers?|likes?|wants?|needs?|works?|studies)\b|\bmy\s+(?:name|age|job|background|goal|preference)\b", value, re.I))


def validate_extraction(output, parts, source_messages):
    data = Extraction.model_validate(output).model_dump()
    by_id = {}
    for part in parts:
        by_id.setdefault(part["id"], []).append(part)
    sources = {message["id"]: message for message in source_messages}
    result = []
    for table in ("knowledge", "memories", "reviews"):
        for item in data[table]:
            if table != "memories" and any(explicit_personal_claim(item.get(key, "")) for key in ("title", "summary", "body", "answer")):
                raise ValueError("Explicit personal facts belong only in verbatim user-backed memory candidates")
            if any(not tag.strip() or len(tag) > 100 for tag in item.get("tags", [])):
                raise ValueError("Invalid extraction tags")
            for evidence in item["evidence"]:
                matching = [part for part in by_id.get(evidence["message_id"], [])
                            if part["version"] == evidence["message_version"] and evidence["quote"] in part["content"]]
                if not matching or (evidence.get("conversation_id") and evidence["conversation_id"] != matching[0]["conversation_id"]):
                    raise ValueError("Extraction citation must match a supplied source chunk and version")
                evidence["conversation_id"] = matching[0]["conversation_id"]
                if table == "memories" and (matching[0]["role"] != "user" or not assertive_personal_quote(sources[evidence["message_id"]]["content"])
                        or not assertive_personal_quote(evidence["quote"]) or not assertive_personal_quote(item["content"])
                        or item["content"] not in evidence["quote"]):
                    raise ValueError("Personal candidate must be a verbatim assertive user statement")
            item["source"] = "extracted"
            if table == "knowledge":
                item["unresolved"] = item["type"] == "unresolved"
            if table == "memories":
                item["status"] = "candidate"
            result.append((table, item))
    return result

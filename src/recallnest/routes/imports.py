from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from ..importers import parse_upload
from .common import repository

router = APIRouter(prefix="/api/import")


async def parse_file(request, file, source_identity):
    settings = request.app.state.settings
    chunks, length = [], 0
    try:
        while True:
            chunk = await file.read(min(65536, settings.max_upload_bytes - length + 1))
            if not chunk:
                break
            chunks.append(chunk)
            length += len(chunk)
            if length > settings.max_upload_bytes:
                raise HTTPException(413, "File exceeds upload byte limit")
        return parse_upload(file.filename or "", b"".join(chunks), source_identity=source_identity,
                            max_upload_bytes=settings.max_upload_bytes, max_zip_bytes=settings.max_zip_bytes,
                            max_zip_members=settings.max_zip_members)
    finally:
        await file.close()


@router.post("/preview")
async def import_preview(request: Request, file: UploadFile = File(...), source_identity: str | None = Form(None)):
    conversations = await parse_file(request, file, source_identity)
    non_text = sum(c.metadata.get("non_text_blocks", sum(m.metadata.get("non_text_blocks", 0) for m in c.messages)) for c in conversations)
    return {"conversations": len(conversations), "messages": sum(len(c.messages) for c in conversations), "errors": 0,
            "non_text_blocks": non_text, "warnings": ["Non-text records are archived as source metadata; media pixels/audio are not extracted."] if non_text else [],
            "items": [{"source": c.source, "source_identity": c.source_identity, "external_id": c.external_id,
                       "title": c.title, "messages": len(c.messages), "current_node": c.current_node} for c in conversations]}


@router.post("")
async def import_file(request: Request, file: UploadFile = File(...), source_identity: str | None = Form(None), repo=Depends(repository)):
    conversations = await parse_file(request, file, source_identity)
    return repo.import_conversations(conversations)

from datetime import date
from fastapi import Request


def repository(request: Request):
    return request.app.state.repository


def filters(q: str | None = None, source: str | None = None, project_id: str | None = None,
            type: str | None = None, tag: str | None = None, date_from: date | None = None,
            date_to: date | None = None, favorite: bool | None = None, unresolved: bool | None = None):
    return {"q": q, "source": source, "project_id": project_id, "type": type, "tag": tag,
            "date_from": str(date_from) if date_from else None, "date_to": str(date_to) if date_to else None,
            "favorite": favorite, "unresolved": unresolved}

from fastapi import APIRouter, Depends
from ..models import ConversationInput, ConversationPatch, AppendInput
from .common import repository, filters

router = APIRouter(prefix="/api/conversations")


@router.get("")
def conversation_list(repo=Depends(repository), query=Depends(filters)):
    return {"items": repo.list_conversations(**query)}


@router.post("", status_code=201)
def conversation_create(body: ConversationInput, repo=Depends(repository)):
    return repo.create_conversation(body.model_dump())


@router.get("/{entity_id}")
def conversation_get(entity_id: str, branch: str | None = None, repo=Depends(repository)):
    return repo.get_conversation(entity_id, branch=branch)


@router.patch("/{entity_id}")
def conversation_edit(entity_id: str, body: ConversationPatch, repo=Depends(repository)):
    return repo.update_conversation(entity_id, body.model_dump(exclude_unset=True))


@router.post("/{entity_id}/messages")
def conversation_append(entity_id: str, body: AppendInput, repo=Depends(repository)):
    return repo.append_messages(entity_id, [m.model_dump(exclude_unset=True) for m in body.messages], current_node=body.current_node)

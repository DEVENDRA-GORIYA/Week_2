from fastapi import APIRouter

from app.core.deps import CurrentUser
from app.prompts.library import list_prompts
from app.schemas.inference import PromptPublic

router = APIRouter()


@router.get("", response_model=list[PromptPublic])
async def prompts(_user: CurrentUser) -> list[PromptPublic]:
    return [
        PromptPublic(
            id=item.id,
            kind=item.kind,
            title=item.title,
            description=item.description,
            system=item.system,
        )
        for item in list_prompts()
    ]

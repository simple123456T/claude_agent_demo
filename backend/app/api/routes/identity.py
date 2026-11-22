from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.identity.dependencies import get_current_user
from app.identity.service import CurrentUser
from app.workspaces.schemas import MeOut
from app.workspaces.service import visible_workspaces

router = APIRouter(tags=["identity"])


@router.get("/me", response_model=MeOut)
def read_me(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MeOut:
    return MeOut(
        id=user.id,
        subject=user.subject,
        email=user.email,
        display_name=user.display_name,
        is_org_admin=user.is_org_admin,
        workspaces=visible_workspaces(db, user),
    )

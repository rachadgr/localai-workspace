"""Idempotent demo seed: a demo user, one project, and a sample conversation.

Seeding never overwrites existing data. The demo account exists so the UI is
usable immediately; it is never injected automatically into production builds
unless explicitly requested via the CLI (``python -m scripts.seed``).
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from database.models import Conversation, Project, User, session_scope

logger = logging.getLogger("localai.seed")

DEMO_EMAIL = "demo@localai.workspace"
DEMO_PASSWORD = "demo1234"


def _hash(password: str) -> str:
    from backend.app.core.security import hash_password

    return hash_password(password)


def seed_demo(create_demo_user: bool = True) -> dict:
    from database.models import new_id

    created: dict = {"users": [], "projects": [], "conversations": []}
    with session_scope() as db:
        user = db.execute(select(User).where(User.email == DEMO_EMAIL)).scalar_one_or_none()
        if user is None and create_demo_user:
            user = User(id=new_id("usr_"), email=DEMO_EMAIL, display_name="Demo User", password_hash=_hash(DEMO_PASSWORD))
            db.add(user)
            db.flush()
            created["users"].append(user.id)

        if user is None:
            return created

        project = db.execute(select(Project).where(Project.user_id == user.id, Project.name == "Getting Started")).scalar_one_or_none()
        if project is None:
            project = Project(
                id=new_id("prj_"),
                user_id=user.id,
                name="Getting Started",
                description="Sample project demonstrating LocalAI Workspace capabilities.",
            )
            db.add(project)
            db.flush()
            created["projects"].append(project.id)

        convo = db.execute(select(Conversation).where(Conversation.project_id == project.id)).scalars().first()
        if convo is None:
            convo = Conversation(id=new_id("cnv_"), project_id=project.id, title="Welcome", mode="chat")
            db.add(convo)
            db.flush()
            created["conversations"].append(convo.id)

    return created


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    from database.migrations import init_db

    init_db()
    print(seed_demo())

"""Durable observations. Unknown is not success; a human review is not a model verdict."""
from app.models import AssuranceEvent


def record(session, user_id, kind, detail=None, mission_id=None):
    session.add(AssuranceEvent(user_id=user_id, mission_id=mission_id, kind=kind, detail=detail or {}))

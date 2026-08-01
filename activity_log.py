from models import db, ActivityLog


def log_activity(actor, action, detail=None):
    db.session.add(ActivityLog(actor=actor, action=action, detail=detail))
    db.session.commit()

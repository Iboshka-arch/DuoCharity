from models import db, ActivityLog


def log_activity(actor, action, detail=None):
    try:
        db.session.add(ActivityLog(actor=actor, action=action, detail=detail))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Не удалось записать ActivityLog: {e}")

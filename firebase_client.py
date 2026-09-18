import firebase_admin
from firebase_admin import firestore


def get_db():
    """Return a Firestore client using Application Default Credentials."""
    if not firebase_admin._apps:
        firebase_admin.initialize_app()
    return firestore.client()

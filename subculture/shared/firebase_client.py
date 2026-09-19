import os

import firebase_admin
from firebase_admin import credentials, firestore

from subculture.shared.paths import PROJECT_ROOT


_DEFAULT_KEY = PROJECT_ROOT / "firebase-key.json"


def get_db():
    """Return a Firestore client.

    Uses GOOGLE_APPLICATION_CREDENTIALS if set, otherwise firebase-key.json
    in the project root, otherwise Application Default Credentials.
    """
    if not firebase_admin._apps:
        cred = None
        if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") and _DEFAULT_KEY.is_file():
            cred = credentials.Certificate(_DEFAULT_KEY)
        firebase_admin.initialize_app(cred)
    return firestore.client()

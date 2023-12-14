from firebase_admin import credentials, firestore
import firebase_admin

cred = credentials.ApplicationDefault()
firebase_admin.initialize_app(cred)
db = firestore.Client()

SESSION_NAME='sessions'
def get_value_session(session_id, name):
    cs_ref = db.collection(SESSION_NAME).document(session_id)
    if(cs_ref.get().exists):
        if name in cs_ref.get().to_dict():
            return cs_ref.get().to_dict()[name]
    return None


def set_value_session(session_id, name, value):
    doc_ref = db.collection(SESSION_NAME).document(session_id)
    
    doc_ref.set({
        name: value,
        'last_updated': firestore.SERVER_TIMESTAMP
        }, merge=True)
    
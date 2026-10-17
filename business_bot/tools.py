"""The two assignment functions, bound to a turn's storage context."""
import hashlib
import json


class RecordingTools:
    def __init__(self, storage, session_id, turn_id, feedback_kind):
        self.storage = storage
        self.session_id = session_id
        self.turn_id = turn_id
        self.feedback_kind = feedback_kind

    def key(self, name, payload):
        canonical = json.dumps([self.session_id, self.turn_id, name, payload], sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def record_customer_interest(self, email, name, message):
        """Persist validated customer interest. Does not send or book anything."""
        payload = {"email": email, "name": name, "message": message}
        return self.storage.save_lead(self.session_id, self.turn_id,
                                      self.key("record_customer_interest", payload), **payload)

    def record_feedback(self, question):
        """Persist validated feedback/an unanswered question for local review."""
        payload = {"kind": self.feedback_kind, "question": question}
        return self.storage.save_feedback(self.session_id, self.turn_id,
                                          self.key("record_feedback", payload), **payload)

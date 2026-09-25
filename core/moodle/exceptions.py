class MoodleError(RuntimeError):
    pass


class MoodleAPIError(MoodleError):
    def __init__(self, payload: dict):
        self.payload = payload
        message = (
            payload.get("message")
            or payload.get("error")
            or payload.get("exception")
            or "Unknown Moodle API error"
        )
        super().__init__(message)

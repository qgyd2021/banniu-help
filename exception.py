

class ExpectedError(Exception):
    def __init__(self, status_code, message, traceback="", detail=""):
        self.status_code = status_code
        self.message = message
        self.traceback = traceback
        self.detail = detail

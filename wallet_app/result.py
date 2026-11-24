from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class Result:
    success: bool
    code: str
    message: str
    data: Any = None

    @classmethod
    def ok(cls, code="OK", message="Success", data=None):
        return cls(True, code, message, data)

    @classmethod
    def fail(cls, code, message, data=None):
        return cls(False, code, message, data)

"""Chain enums aligned with agents-flex Java types."""
from enum import Enum


class ChainStatus(str, Enum):
    READY = "READY"
    RUNNING = "RUNNING"
    SUSPEND = "SUSPEND"
    ERROR = "ERROR"
    FINISHED_NORMAL = "FINISHED_NORMAL"
    FINISHED_ABNORMAL = "FINISHED_ABNORMAL"


class RefType(str, Enum):
    REF = "ref"
    FIXED = "fixed"
    INPUT = "input"

    @classmethod
    def of_value(cls, value: str | None) -> "RefType | None":
        if not value:
            return None
        for item in cls:
            if item.value == value:
                return item
        return None


class DataType(str, Enum):
    OBJECT = "Object"
    STRING = "String"
    NUMBER = "Number"
    BOOLEAN = "Boolean"
    FILE = "File"
    ARRAY_OBJECT = "Array<Object>"
    ARRAY_STRING = "Array<String>"
    ARRAY_NUMBER = "Array<Number>"
    ARRAY_BOOLEAN = "Array<Boolean>"
    ARRAY_FILE = "Array<File>"

    @classmethod
    def of_value(cls, value: str | None) -> "DataType | None":
        if not value:
            return None
        normalized = value.strip()
        if normalized.lower() == "array":
            return cls.ARRAY_OBJECT
        for item in cls:
            if item.value.lower() == normalized.lower():
                return item
        return None

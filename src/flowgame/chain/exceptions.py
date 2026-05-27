"""Chain execution exceptions."""


class ChainException(Exception):
    pass


class ChainSuspendException(ChainException):
    pass

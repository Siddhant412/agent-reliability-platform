class ApplicationError(Exception):
    """Base class for control-plane application errors."""


class NotFoundError(ApplicationError):
    pass


class ConflictError(ApplicationError):
    pass


class ApplicationError(Exception):
    """Base class for control-plane application errors."""


class AuthenticationError(ApplicationError):
    pass


class AuthorizationError(ApplicationError):
    pass


class NotFoundError(ApplicationError):
    pass


class ConflictError(ApplicationError):
    pass

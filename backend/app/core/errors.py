class HelixError(Exception):
    status_code = 400
    code = "error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message
        self.headers: dict[str, str] = {}


class Unauthorized(HelixError):
    status_code = 401
    code = "unauthorized"

    def __init__(self, message: str = "Not authenticated.") -> None:
        super().__init__(message)
        self.headers = {"WWW-Authenticate": "Bearer"}


class Forbidden(HelixError):
    status_code = 403
    code = "forbidden"


class NotFound(HelixError):
    status_code = 404
    code = "not_found"


class Conflict(HelixError):
    status_code = 409
    code = "conflict"


class SchemaViolation(HelixError):
    status_code = 422
    code = "schema_violation"


class RateLimited(HelixError):
    status_code = 429
    code = "rate_limited"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.headers = {"Retry-After": "60"}


class BudgetExceeded(HelixError):
    status_code = 429
    code = "budget_exceeded"


class ProviderError(HelixError):
    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = "provider_unavailable" if status_code in {503, 504} else "provider_error"

"""Velbus exceptions."""


class VelbusException(Exception):
    """Velbus Exception."""

    def __init__(self, value: str) -> None:
        """Initialize the exception."""
        Exception.__init__(self)
        self.value = value

    def __str__(self):
        """Return the exception as a string."""
        return repr(self.value)


class VelbusConnectionFailed(VelbusException):
    """Exception for connection setup failure."""

    def __init__(self) -> None:
        """Initialize the exception."""
        super().__init__("Connection setup failed")


class VelbusConnectionTerminated(VelbusException):
    """Exception for connection termination."""

    def __init__(self) -> None:
        """Initialize the exception."""
        super().__init__("Connection terminated")


class VelbusMemoryTimeout(VelbusException):
    """Exception when a memory read/write acknowledgement times out."""

    def __init__(self, address: int, operation: str = "memory") -> None:
        """Initialize the exception."""
        super().__init__(
            f"Timeout waiting for {operation} acknowledgement at 0x{address:04X}"
        )


class VelbusConfigError(VelbusException):
    """Exception for configuration / action-table errors."""

    def __init__(self, value: str) -> None:
        """Initialize the exception."""
        super().__init__(value)

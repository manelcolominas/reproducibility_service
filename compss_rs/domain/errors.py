from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class ErrorCategory(Enum):
    CONFIGURATION = auto()
    VALIDATION = auto()
    USER_INPUT = auto()
    CANCELLATION = auto()
    NETWORK = auto()
    FILE_SYSTEM = auto()
    METADATA = auto()
    COMPATIBILITY = auto()
    EXECUTION = auto()
    PROVENANCE = auto()
    UNKNOWN = auto()


@dataclass(frozen=True, slots=True)
class ServiceError(Exception):
    message: str
    category: ErrorCategory = ErrorCategory.UNKNOWN
    details: str | None = None
    recoverable: bool = False

    def __post_init__(self) -> None:
        if not self.message or not self.message.strip():
            raise ValueError("ServiceError.message cannot be empty")

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} ({self.details})"
        return self.message


class ConfigurationError(ServiceError):
    def __init__(self, message: str, details: str | None = None):
        super().__init__(
            message=message,
            category=ErrorCategory.CONFIGURATION,
            details=details,
            recoverable=False,
        )


class ValidationError(ServiceError):
    def __init__(self, message: str, details: str | None = None, recoverable: bool = False):
        super().__init__(
            message=message,
            category=ErrorCategory.VALIDATION,
            details=details,
            recoverable=recoverable,
        )


class UserInputError(ServiceError):
    def __init__(self, message: str, details: str | None = None, recoverable: bool = True):
        super().__init__(
            message=message,
            category=ErrorCategory.USER_INPUT,
            details=details,
            recoverable=recoverable,
        )


class UserCancellation(ServiceError):
    def __init__(self, message: str = "Operation cancelled by user", details: str | None = None):
        super().__init__(
            message=message,
            category=ErrorCategory.CANCELLATION,
            details=details,
            recoverable=True,
        )


class InterruptedOperation(ServiceError):
    def __init__(self, message: str = "Operation interrupted", details: str | None = None):
        super().__init__(
            message=message,
            category=ErrorCategory.CANCELLATION,
            details=details,
            recoverable=True,
        )


class FileSystemError(ServiceError):
    def __init__(self, message: str, details: str | None = None, recoverable: bool = False):
        super().__init__(
            message=message,
            category=ErrorCategory.FILE_SYSTEM,
            details=details,
            recoverable=recoverable,
        )


class NetworkError(ServiceError):
    def __init__(self, message: str, details: str | None = None, recoverable: bool = True):
        super().__init__(
            message=message,
            category=ErrorCategory.NETWORK,
            details=details,
            recoverable=recoverable,
        )


class MetadataError(ServiceError):
    def __init__(self, message: str, details: str | None = None, recoverable: bool = False):
        super().__init__(
            message=message,
            category=ErrorCategory.METADATA,
            details=details,
            recoverable=recoverable,
        )


class MetadataParseError(MetadataError):
    pass


class MissingMetadataError(MetadataError):
    pass


class UnsupportedMetadataFormatError(MetadataError):
    pass


class CompatibilityError(ServiceError):
    def __init__(self, message: str, details: str | None = None, recoverable: bool = True):
        super().__init__(
            message=message,
            category=ErrorCategory.COMPATIBILITY,
            details=details,
            recoverable=recoverable,
        )


class UnsupportedCompssVersionError(CompatibilityError):
    pass


class UnsupportedCrateVersionError(CompatibilityError):
    pass


class ExecutionError(ServiceError):
    def __init__(self, message: str, details: str | None = None, recoverable: bool = False):
        super().__init__(
            message=message,
            category=ErrorCategory.EXECUTION,
            details=details,
            recoverable=recoverable,
        )


class CommandBuildError(ExecutionError):
    pass


class WorkflowExecutionError(ExecutionError):
    pass


class ExternalToolError(ExecutionError):
    pass


class ProvenanceError(ServiceError):
    def __init__(self, message: str, details: str | None = None, recoverable: bool = False):
        super().__init__(
            message=message,
            category=ErrorCategory.PROVENANCE,
            details=details,
            recoverable=recoverable,
        )


class UnknownServiceError(ServiceError):
    def __init__(self, message: str, details: str | None = None, recoverable: bool = False):
        super().__init__(
            message=message,
            category=ErrorCategory.UNKNOWN,
            details=details,
            recoverable=recoverable,
        )

__all__ = [
    "CompatibilityError",
    "CommandBuildError",
    "ConfigurationError",
    "ErrorCategory",
    "ExecutionError",
    "ExternalToolError",
    "FileSystemError",
    "InterruptedOperation",
    "MetadataError",
    "MetadataParseError",
    "MissingMetadataError",
    "NetworkError",
    "ProvenanceError",
    "ServiceError",
    "UnknownServiceError",
    "UnsupportedCompssVersionError",
    "UnsupportedCrateVersionError",
    "UnsupportedMetadataFormatError",
    "UserCancellation",
    "UserInputError",
    "ValidationError",
]
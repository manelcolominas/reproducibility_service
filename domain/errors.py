from __future__ import annotations


class ServiceError(Exception):
    def __init__(self, message: str, details: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} ({self.details})"
        return self.message


class ValidationError(ServiceError):
    pass


class FileSystemError(ServiceError):
    pass


class MetadataError(ServiceError):
    pass


class ExecutionError(ServiceError):
    pass


class SourceAcquisitionError(FileSystemError):
    pass


class SourceValidationError(ValidationError):
    pass


class UnsupportedSourceError(ValidationError):
    pass


class MetadataParseError(MetadataError):
    pass


class MissingMetadataError(MetadataError):
    pass


class CommandBuildError(ExecutionError):
    pass


class WorkflowExecutionError(ExecutionError):
    pass
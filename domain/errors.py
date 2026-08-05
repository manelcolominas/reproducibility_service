#!/usr/bin/env python3
#
#  Copyright 2002-2026 Barcelona Supercomputing Center (www.bsc.es)
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#

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
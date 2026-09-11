"""Failure classes (contract §13). Every failure must be visible and classified."""


class ProjectAutoError(Exception):
    code = "PROJECT AUTOMATION ERROR"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


class ConfigError(ProjectAutoError):
    code = "CONFIGURATION ERROR"


class AuthenticationError(ProjectAutoError):
    code = "AUTHENTICATION ERROR"


class MetadataConflict(ProjectAutoError):
    code = "METADATA CONFLICT"


class UnknownIteration(ProjectAutoError):
    code = "UNKNOWN ITERATION"


class ProjectMutationFailure(ProjectAutoError):
    code = "PROJECT MUTATION FAILURE"


class RestorationFailure(ProjectAutoError):
    code = "RESTORATION FAILURE"


class VerificationFailure(ProjectAutoError):
    code = "VERIFICATION FAILURE"

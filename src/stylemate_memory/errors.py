"""Public errors never include provider bodies, credentials, or other users' data."""


# A0 v1 vocabulary. Existing legacy codes and StyleMateError behavior stay intact.
# Domain modules own the checks; never substitute a provider body for a message.
V1_ERROR_CODES = frozenset({
    "invalid_input", "unsupported_contract", "not_found", "version_conflict",
    "idempotency_conflict", "confirmation_required", "consent_required",
    "invalid_user_event", "unsupported_mapping", "registry_unavailable",
    "request_closed", "request_expired", "stale_context", "context_blocked",
    "invalid_extraction", "invalid_output", "catalog_conflict", "cleanup_pending",
    "provider_timeout", "provider_unavailable", "provider_rate_limited",
    "provider_http_error", "provider_invalid_response", "provider_error",
    "provider_incomplete", "provider_refusal", "empty_response",
})


class StyleMateError(Exception):
    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        self.message = message or code
        super().__init__(self.message)

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}

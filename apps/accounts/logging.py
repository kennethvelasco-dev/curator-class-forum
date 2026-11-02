import logging
import re
from collections.abc import Mapping


_VERIFICATION_URL_PATTERN = re.compile(
    r"(?P<prefix>/accounts/(?:verify-registration|verify)/\d+/)"
    r"[^/?\s\"'<>]+"
)


def _redact_verification_tokens(value):
    return _VERIFICATION_URL_PATTERN.sub(r"\g<prefix>[redacted]", value)


class _RedactedMapping(Mapping):
    def __init__(self, mapping):
        self._mapping = mapping

    def __getitem__(self, key):
        value = self._mapping[key]
        if isinstance(value, str):
            return _redact_verification_tokens(value)
        return value

    def __iter__(self):
        return iter(self._mapping)

    def __len__(self):
        return len(self._mapping)


class _RedactedRequest:
    def __init__(self, request):
        self._request = request

    @property
    def META(self):
        return _RedactedMapping(self._request.META)

    @property
    def path(self):
        return _redact_verification_tokens(self._request.path)

    @property
    def path_info(self):
        return _redact_verification_tokens(self._request.path_info)

    def get_full_path(self, *args, **kwargs):
        return _redact_verification_tokens(
            self._request.get_full_path(*args, **kwargs)
        )

    def build_absolute_uri(self, location=None):
        return _redact_verification_tokens(
            self._request.build_absolute_uri(location)
        )

    def __getattr__(self, name):
        return getattr(self._request, name)


class RedactVerificationTokenFilter(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        redacted_message = _redact_verification_tokens(message)
        if redacted_message != message:
            record.msg = redacted_message
            record.args = ()

        request = getattr(record, "request", None)
        if request is not None:
            record.request = _RedactedRequest(request)

        return True

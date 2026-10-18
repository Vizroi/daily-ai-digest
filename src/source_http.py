"""Small GET transport shared by public sources; keep platform access limits intact."""
from contextlib import nullcontext
import ssl
import threading
import time
from urllib.parse import urlparse

import requests

_LOCAL = threading.local()
_STEAM_GATE = threading.BoundedSemaphore(2)
_TRANSIENT_HTTP = {500, 502, 503, 504}


def _session():
    if not hasattr(_LOCAL, "session"):
        # Defaults deliberately retain certificate verification and environment
        # proxy / certificate settings. Sessions are never shared across threads.
        _LOCAL.session = requests.Session()
    return _LOCAL.session


def failure_reason(error):
    """Classify verified exception objects without exposing URLs, headers or tokens."""
    stack, seen, eof = [error], set(), False
    while stack:
        item = stack.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        if isinstance(item, ssl.SSLCertVerificationError):
            return "tls_certificate"
        if isinstance(item, ssl.SSLEOFError) or (
                isinstance(item, ssl.SSLError) and getattr(item, "reason", None) == "UNEXPECTED_EOF_WHILE_READING"):
            eof = True
        if isinstance(item, BaseException):
            stack.extend(arg for arg in item.args if isinstance(arg, BaseException))
            stack.extend(child for child in (item.__cause__, item.__context__, getattr(item, "reason", None))
                         if isinstance(child, BaseException))
    if eof:
        return "tls_eof"
    if isinstance(error, requests.Timeout):
        return "timeout"
    return None


def get_response(url, **kwargs):
    """GET once, with at most one retry for a confirmed transient transport error.

    Return HTTP responses to the caller for source-specific status handling. Rate
    limits, authorization failures and certificate failures are never retried.
    """
    kwargs.setdefault("timeout", (5, 20))
    gate = _STEAM_GATE if urlparse(url).hostname == "api.steampowered.com" else nullcontext()
    with gate:
        for attempt in range(2):
            try:
                response = _session().get(url, **kwargs)
            except requests.RequestException as error:
                if attempt or failure_reason(error) not in {"timeout", "tls_eof"}:
                    raise
                time.sleep(0.5)
                continue
            if not attempt and response.status_code in _TRANSIENT_HTTP:
                response.close()
                time.sleep(0.5)
                continue
            return response

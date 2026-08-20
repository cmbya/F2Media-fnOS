from __future__ import annotations

import re
from collections.abc import Sequence

MASK = "***REDACTED***"

_PATTERNS = [
    # Header / key=value forms.
    re.compile(r"(?i)(authorization\s*[:=]\s*)([^\s,;]+)"),
    re.compile(r"(?i)(x-csrf-token\s*[:=]\s*)([^\s,;]+)"),
    re.compile(r"(?i)((?:cookie|cookies|token|secret|passwd|password)\s*[:=]\s*)([^\r\n]+)"),
    # Python/JSON-like debug dictionaries, e.g. {'cookie': '...'}.
    re.compile(r"(?i)(['\"](?:authorization|x-csrf-token|cookie|cookies|token|secret|passwd|password)['\"]\s*:\s*['\"])(.*?)(['\"])") ,
    # Sensitive URL query parameters.
    re.compile(r"(?i)([?&](?:token|auth|key|signature|session|cookie)=)([^&\s]+)"),
]


def redact_text(value: str) -> str:
    out = value
    for pattern in _PATTERNS:
        if pattern.groups >= 3:
            out = pattern.sub(lambda m: m.group(1) + MASK + m.group(3), out)
        else:
            out = pattern.sub(lambda m: m.group(1) + MASK, out)
    # Common cookie-like identifiers that may appear inside upstream debug output.
    out = re.sub(
        r"(?i)(msToken|ttwid|sessionid|sid_tt|auth_token|ct0)=([^;\s]+)",
        r"\1=" + MASK,
        out,
    )
    return out


def redact_command(cmd: Sequence[str]) -> str:
    safe: list[str] = []
    hide_next = False
    for arg in cmd:
        if hide_next:
            safe.append(MASK)
            hide_next = False
            continue
        if arg in {"-k", "--cookie", "--cookies", "--password", "--token"}:
            safe.append(arg)
            hide_next = True
        else:
            safe.append(redact_text(str(arg)))
    return " ".join(safe)

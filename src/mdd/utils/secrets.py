"""Secret resolution utilities for mdd (1Password op:// references)."""

from __future__ import annotations

import os
import re
import subprocess
from typing import Any

_cache: dict[str, str] = {}

_TOKEN_RE = re.compile(r"[A-Za-z0-9_\-]{20,}")
_OP_REF_RE = re.compile(r"op://[^\s]+")


def _redact(text: str) -> str:
    """Redact op:// references and token-shaped values from text."""
    text = _OP_REF_RE.sub("<redacted-op-ref>", text)
    return _TOKEN_RE.sub("<redacted>", text)


class SecretError(Exception):
    """Raised when a secret cannot be resolved.

    Redacts op:// references and token-shaped values at construction time
    so that secrets are never exposed through __str__, __repr__, or .args —
    which are all used by traceback formatters, structured loggers, and
    wrapping exception chains.
    """

    def __init__(self, *args: object) -> None:
        redacted = tuple(_redact(str(a)) if isinstance(a, str) else a for a in args)
        super().__init__(*redacted)

    def __repr__(self) -> str:
        redacted_args = ", ".join(repr(a) for a in self.args)
        return f"{type(self).__name__}({redacted_args})"


def resolve_secret(value: str, *, account: str | None = None) -> str:
    """Resolve a secret value.

    If *value* does not start with ``op://``, it is returned unchanged.
    Otherwise the 1Password CLI is invoked to read the secret.

    The *account* parameter (or the ``MDD_OP_ACCOUNT`` environment variable)
    is passed to ``op read --account`` when set.  This is useful when the user
    has multiple 1Password accounts and the default account does not contain the
    referenced vault.  Alternatively, the ``OP_ACCOUNT`` environment variable
    understood natively by the op CLI can be used.

    Raises SecretError if the op CLI is unavailable or the read fails.
    """
    if not value.startswith("op://"):
        return value

    resolved_account = account or os.environ.get("MDD_OP_ACCOUNT")

    cache_key = f"{resolved_account}:{value}" if resolved_account else value
    if cache_key in _cache:
        return _cache[cache_key]

    cmd = ["op", "read", value]
    if resolved_account:
        cmd += ["--account", resolved_account]

    try:
        result = subprocess.run(
            cmd,
            timeout=10,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise SecretError("op CLI not installed; see spec S07") from exc

    if result.returncode == 127:
        raise SecretError("op CLI not installed; see spec S07")

    if result.returncode != 0:
        stderr = result.stderr or ""
        if "not signed in" in stderr.lower():
            raise SecretError("op CLI signed out; unlock 1Password and retry")
        hint = (
            "\n  Hint: if you have multiple 1Password accounts, set MDD_OP_ACCOUNT=<shorthand>"
            " or add 'op_account: <shorthand>' to your config."
        )
        if "isn't a vault" in stderr or "not a vault" in stderr.lower():
            raise SecretError(f"op read failed: {_redact(stderr)}{hint}")
        raise SecretError(f"op read failed: {_redact(stderr)}")

    secret = result.stdout.rstrip("\n")
    _cache[cache_key] = secret
    return secret


def parse_secret_ref(value: Any) -> tuple[str, str | None]:  # pyright: ignore[reportExplicitAny]
    """Normalise a secret reference from config to ``(ref, account)``.

    Accepts either:

    - a string — bare reference (``op://...`` or a plain literal). Returned
      with ``account=None`` so the caller falls back to environment defaults.
    - a mapping ``{"ref": "op://...", "account": "<shorthand>"}`` —
      ``ref`` is required and ``account`` is optional. This is the form
      that lets a config target a specific 1Password account when the
      user is signed in to several.

    Raises ``ValueError`` for empty or malformed input and ``TypeError``
    for unsupported value types.
    """
    if isinstance(value, str):
        if not value:
            raise ValueError("secret reference is empty")
        return value, None
    if isinstance(value, dict):
        d: dict[Any, Any] = value  # pyright: ignore[reportUnknownVariableType]
        ref_raw: Any = d.get("ref")  # pyright: ignore[reportAny]
        if not isinstance(ref_raw, str) or not ref_raw:
            raise ValueError("secret reference object missing 'ref'")
        account_raw: Any = d.get("account")  # pyright: ignore[reportAny]
        if account_raw is None:
            return ref_raw, None
        if not isinstance(account_raw, str) or not account_raw:
            raise ValueError("secret reference 'account' must be a non-empty string")
        return ref_raw, account_raw
    raise TypeError(
        f"secret reference must be a string or {{ref, account}} object, got {type(value).__name__}"
    )

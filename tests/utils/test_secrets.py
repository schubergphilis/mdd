"""Tests for mdd.utils.secrets."""

import subprocess
from typing import Any
from unittest.mock import MagicMock

import pytest

import mdd.utils.secrets as secrets_mod
from mdd.utils.secrets import SecretError, parse_secret_ref, resolve_secret


@pytest.fixture(autouse=True)
def clear_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset the module-level cache before each test."""
    monkeypatch.setattr(secrets_mod, "_cache", {})


def _make_run_result(returncode: int, stdout: str, stderr: str) -> MagicMock:
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


class TestResolveSecret:
    def test_plain_value_passes_through(self) -> None:
        assert resolve_secret("plain-value") == "plain-value"

    def test_op_ref_returns_mocked_stdout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        result = _make_run_result(0, "super-secret\n", "")

        def fake_run(*args: Any, **kwargs: Any) -> MagicMock:
            return result

        monkeypatch.setattr(subprocess, "run", fake_run)
        assert resolve_secret("op://Vault/Item/Field") == "super-secret"

    def test_cache_hit_skips_subprocess(self, monkeypatch: pytest.MonkeyPatch) -> None:
        call_count = 0

        def fake_run(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            return _make_run_result(0, "cached-value\n", "")

        monkeypatch.setattr(subprocess, "run", fake_run)

        first = resolve_secret("op://Vault/Item/Field2")
        second = resolve_secret("op://Vault/Item/Field2")
        assert first == second == "cached-value"
        assert call_count == 1

    def test_file_not_found_raises_secret_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_run(*args: Any, **kwargs: Any) -> MagicMock:
            raise FileNotFoundError("op not found")

        monkeypatch.setattr(subprocess, "run", fake_run)

        with pytest.raises(SecretError, match="not installed"):
            resolve_secret("op://Vault/Item/Field")

    def test_not_signed_in_raises_secret_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        result = _make_run_result(1, "", "Error: not signed in to 1Password")

        def fake_run(*args: Any, **kwargs: Any) -> MagicMock:
            return result

        monkeypatch.setattr(subprocess, "run", fake_run)

        with pytest.raises(SecretError, match="signed out"):
            resolve_secret("op://Vault/Item/Field")

    def test_other_failure_redacts_op_ref_in_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        result = _make_run_result(1, "", "could not find op://Vault/Secret/Field in vault")

        def fake_run(*args: Any, **kwargs: Any) -> MagicMock:
            return result

        monkeypatch.setattr(subprocess, "run", fake_run)

        with pytest.raises(SecretError) as exc_info:
            resolve_secret("op://Vault/Secret/Field")

        assert "op://Vault/Secret/Field" not in str(exc_info.value)

    def test_vault_not_in_account_error_includes_hint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = _make_run_result(1, "", "'Employee' isn't a vault in this account")

        def fake_run(*args: Any, **kwargs: Any) -> MagicMock:
            return result

        monkeypatch.setattr(subprocess, "run", fake_run)

        with pytest.raises(SecretError) as exc_info:
            resolve_secret("op://Employee/token/credential")

        assert "MDD_OP_ACCOUNT" in str(exc_info.value)

    def test_account_arg_passed_to_op(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: list[list[str]] = []

        def fake_run(cmd: list[str], **kwargs: Any) -> MagicMock:
            captured.append(cmd)
            return _make_run_result(0, "secret-value\n", "")

        monkeypatch.setattr(subprocess, "run", fake_run)
        resolve_secret("op://Vault/Item/Field", account="my.1password.eu")
        assert "--account" in captured[0]
        assert "my.1password.eu" in captured[0]

    def test_mdd_op_account_env_var_used(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: list[list[str]] = []

        def fake_run(cmd: list[str], **kwargs: Any) -> MagicMock:
            captured.append(cmd)
            return _make_run_result(0, "secret-value\n", "")

        monkeypatch.setattr(subprocess, "run", fake_run)
        monkeypatch.setenv("MDD_OP_ACCOUNT", "example.1password.eu")
        resolve_secret("op://Vault/Item/Field")
        assert "--account" in captured[0]
        assert "example.1password.eu" in captured[0]

    def test_no_account_env_var_not_in_cmd(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: list[list[str]] = []

        def fake_run(cmd: list[str], **kwargs: Any) -> MagicMock:
            captured.append(cmd)
            return _make_run_result(0, "secret-value\n", "")

        monkeypatch.setattr(subprocess, "run", fake_run)
        monkeypatch.delenv("MDD_OP_ACCOUNT", raising=False)
        resolve_secret("op://Vault/Item/Field")
        assert "--account" not in captured[0]


class TestParseSecretRef:
    def test_string_returns_ref_and_none_account(self) -> None:
        assert parse_secret_ref("op://Vault/Item/Field") == ("op://Vault/Item/Field", None)

    def test_plain_string_passes_through(self) -> None:
        assert parse_secret_ref("plain-token") == ("plain-token", None)

    def test_object_with_ref_and_account(self) -> None:
        ref, account = parse_secret_ref(
            {"ref": "op://Employee/confluence-pat/token", "account": "example-org"}
        )
        assert ref == "op://Employee/confluence-pat/token"
        assert account == "example-org"

    def test_object_without_account(self) -> None:
        assert parse_secret_ref({"ref": "op://Vault/Item/Field"}) == (
            "op://Vault/Item/Field",
            None,
        )

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            parse_secret_ref("")

    def test_object_missing_ref_raises(self) -> None:
        with pytest.raises(ValueError, match="missing 'ref'"):
            parse_secret_ref({"account": "example-org"})

    def test_object_empty_account_raises(self) -> None:
        with pytest.raises(ValueError, match="account"):
            parse_secret_ref({"ref": "op://x/y/z", "account": ""})

    def test_unsupported_type_raises(self) -> None:
        with pytest.raises(TypeError, match="string or"):
            parse_secret_ref(42)


class TestSecretErrorRedaction:
    """SecretError must redact secrets from all Python exception surfaces."""

    def test_str_redacts_op_ref(self) -> None:
        exc = SecretError("failed to read op://Vault/Item/Field")
        assert "op://Vault/Item/Field" not in str(exc)
        assert "<redacted-op-ref>" in str(exc)

    def test_args_redacted_at_construction(self) -> None:
        """exc.args[0] must not contain un-redacted secret material."""
        exc = SecretError("failed to read op://Vault/Item/Field")
        assert "op://Vault/Item/Field" not in exc.args[0]

    def test_repr_redacted(self) -> None:
        """repr(exc) must not expose secret material."""
        exc = SecretError("failed to read op://Vault/Item/Field")
        assert "op://Vault/Item/Field" not in repr(exc)
        assert "SecretError" in repr(exc)

    def test_token_shaped_value_redacted_in_args(self) -> None:
        """Long alphanumeric tokens in the message are redacted from .args."""
        long_token = "abcdefghij1234567890abcd"  # > 20 chars
        exc = SecretError(f"op read failed: {long_token}")
        assert long_token not in exc.args[0]

    def test_non_string_args_preserved(self) -> None:
        """Non-string args are passed through unchanged."""
        exc = SecretError("message", 42)
        assert exc.args[1] == 42

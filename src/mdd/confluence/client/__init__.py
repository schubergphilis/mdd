"""Confluence REST API client with retry/backoff.

The dominant public symbol — :class:`ConfluenceClient` — lives in this
``__init__.py``. Topic-grouped helper modules sit alongside:

- ``errors`` — :class:`ConfluenceError`.
- ``paths`` — path validation and download-URL normalisation.

Request/response trace hooks come from :mod:`mdd.utils.http_trace`, and
retry-decision helpers from :mod:`mdd.utils.retry`.
"""

from __future__ import annotations

import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from mdd.utils.http_trace import format_body, make_event_hooks, trace_bodies_enabled
from mdd.utils.logging import TRACE, get_logger
from mdd.utils.retry import backoff_for_response, jittered_delay, should_retry

from .errors import ConfluenceError
from .paths import assert_relative_api_path, rest_attachment_download_path

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
    "MAX_PAGINATION_ITERATIONS",
    "ConfluenceClient",
    "ConfluenceError",
    "PutPageOptions",
    "assert_relative_api_path",
]


@dataclass(frozen=True)
class PutPageOptions:
    """Optional fields for :meth:`ConfluenceClient.put_page`.

    Bundled so that adding ``parent_id`` / ``status`` to ``put_page``'s
    signature does not push it past the project's 6-arg structural limit.
    When both fields are at their defaults the PUT behaves identically to
    the original 5-positional signature.
    """

    parent_id: str | None = None
    status: str = "current"


log = get_logger(__name__)


# 5 attempts total: 1 initial + 4 retries.
_RETRY_DELAYS = (1, 2, 4, 8)  # seconds between retries

# Safety guard against runaway pagination loops.  Set deliberately tight while
# the export/sync code is being hardened — most real Confluence spaces have far
# fewer pages than (page-size * 9).  Raising ConfluenceError when hit makes
# silent infinite loops impossible.
MAX_PAGINATION_ITERATIONS = 9

# Explicit per-phase timeouts — a bare ``timeout=30.0`` did not fire
# during a TLS-level read stall against a real tenant.  All four
# phases get the same 30 s budget so the user sees a clear error within the
# minute instead of an indefinite hang.
_DEFAULT_TIMEOUT = httpx.Timeout(connect=30.0, read=30.0, write=30.0, pool=30.0)


def _log_transport_error(
    method: str, path: str, exc: Exception, attempt: int, max_attempts: int
) -> None:
    """Emit the per-attempt transport-error warning shared by retry loops."""
    log.warning(
        "%s %s: transport error %s: %s (attempt %d/%d)",
        method,
        path,
        type(exc).__name__,
        exc,
        attempt,
        max_attempts,
    )


def _trace_response_body(method: str, url: str, response: httpx.Response) -> None:
    """Log the response body at TRACE level when body tracing is enabled.

    The streaming ``download_attachment_to_file()`` path intentionally skips
    this so it does not slurp the file into memory.
    """
    if trace_bodies_enabled():
        log.log(TRACE, "HTTP %s %s body:\n%s", method, url, format_body(response.text))


def _extract_dict_list(data: dict[str, Any], key: str) -> list[dict[str, Any]]:  # pyright: ignore[reportExplicitAny]
    """Return ``data[key]`` filtered to dict elements, or ``[]`` if shape is wrong.

    The Confluence v2 list endpoints return ``{"results": [{...}, {...}]}`` but the
    JSON arrives untyped; this collapses the isinstance ladder protecting the call
    sites into one defensive read.
    """
    raw: Any = data.get(key, [])  # pyright: ignore[reportAny]
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]  # pyright: ignore[reportUnknownVariableType]


def _extract_next_link(data: dict[str, Any]) -> str | None:  # pyright: ignore[reportExplicitAny]
    """Return ``data["_links"]["next"]`` as a string, or ``None`` if absent.

    Used by paginated v2 endpoints; the call site still has to SSRF-validate the
    URL via :func:`assert_relative_api_path` before following it.
    """
    raw_links: Any = data.get("_links", {})  # pyright: ignore[reportAny]
    if not isinstance(raw_links, dict):
        return None
    nxt: Any = raw_links.get("next")  # pyright: ignore[reportAny, reportUnknownVariableType, reportUnknownMemberType]
    if nxt is None:
        return None
    return str(nxt)  # pyright: ignore[reportUnknownArgumentType]


class ConfluenceClient:
    """Thin httpx-based Confluence REST client with retry/backoff."""

    def __init__(
        self,
        base_url: str,
        username: str,
        token_resolver: Callable[[], str],
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._token_resolver = token_resolver
        self._resolved_token: str | None = None
        self._http: httpx.Client | None = None
        self._user_cache: dict[str, dict[str, Any]] = {}

    @property
    def base_url(self) -> str:
        """Public access to the base URL."""
        return self._base_url

    def _get_http(self) -> httpx.Client:
        if self._http is None:
            if self._resolved_token is None:
                self._resolved_token = self._token_resolver()
            self._http = httpx.Client(
                auth=httpx.BasicAuth(self._username, self._resolved_token),
                headers={
                    "X-Atlassian-Token": "no-check",
                    "Accept": "application/json",
                },
                timeout=_DEFAULT_TIMEOUT,
                event_hooks=make_event_hooks(log),
            )
        return self._http

    def _reset_auth(self) -> None:
        """Clear cached token and HTTP client so they are re-resolved on next request."""
        if self._http is not None:
            self._http.close()
            self._http = None
        self._resolved_token = None

    def _request(self, method: str, path: str, **kw: Any) -> httpx.Response:  # pyright: ignore[reportAny]
        """Send a request with retry/backoff on 429/503/5xx/transport errors.

        On a 401 the token is cleared and re-resolved once before giving up,
        to handle token rotation mid-session.

        Retry delays have up to 10 % jitter to avoid lockstep retry storms
        when multiple processes hit the same rate-limit window.

        :class:`httpx.TimeoutException` (covering ``ReadTimeout``,
        ``ConnectTimeout``, ``WriteTimeout``, ``PoolTimeout``) is caught
        alongside :class:`httpx.ConnectError` so a slow / stuck server
        surfaces a clear ``ConfluenceError`` instead of an opaque traceback.
        """
        url = self._base_url + path
        client = self._get_http()
        last_exc: Exception | None = None
        token_refreshed = False
        max_attempts = len(_RETRY_DELAYS) + 1
        for attempt, delay in enumerate((*_RETRY_DELAYS, None), start=1):
            try:
                response = client.request(method, url, **kw)
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_exc = exc
                _log_transport_error(method, path, exc, attempt, max_attempts)
                if delay is None:
                    break
                time.sleep(jittered_delay(delay))
                continue

            _trace_response_body(method, url, response)

            if response.is_success:
                return response

            # On 401: re-resolve token once and retry immediately.
            if response.status_code == 401 and not token_refreshed:
                token_refreshed = True
                self._reset_auth()
                client = self._get_http()
                url = self._base_url + path
                continue

            if not should_retry(response):
                # 4xx (other than 429 / 401-retried): no retry
                raise ConfluenceError(
                    f"{method} {path} failed with {response.status_code}: {response.text[:200]}"
                )

            last_exc = ConfluenceError(
                f"{method} {path} failed with {response.status_code}: {response.text[:200]}"
            )
            if delay is None:
                break
            time.sleep(backoff_for_response(response, delay))

        exc_summary = f": {type(last_exc).__name__}: {last_exc}" if last_exc is not None else ""
        raise ConfluenceError(
            f"{method} {path} failed after {max_attempts} attempts{exc_summary}"
        ) from last_exc

    def get(self, path: str, **kw: Any) -> dict[str, Any]:  # pyright: ignore[reportAny]
        """GET path and return JSON as dict."""
        response = self._request("GET", path, **kw)
        result: Any = response.json()  # pyright: ignore[reportAny]
        if not isinstance(result, dict):
            raise ConfluenceError(f"Expected JSON object from GET {path}, got {type(result)}")
        return result  # pyright: ignore[reportReturnType, reportUnknownVariableType]

    def get_bytes(self, path: str, **kw: Any) -> bytes:  # pyright: ignore[reportAny]
        """GET path and return raw bytes."""
        response = self._request("GET", path, **kw)
        return response.content

    def head(self, path: str, **kw: Any) -> httpx.Response:  # pyright: ignore[reportAny]
        """HEAD request, returns raw response."""
        return self._request("HEAD", path, **kw)

    @staticmethod
    def _validate_id(value: str, label: str) -> None:
        """Raise ConfluenceError if *value* is not a safe alphanumeric ID.

        Page IDs, folder IDs, and space IDs returned by the API are numeric or
        alphanumeric.  Validating them before path interpolation prevents
        path-traversal attacks (e.g. ``../../admin``) if a caller passes a
        crafted value from untrusted input such as frontmatter.
        """
        if not value.isalnum():
            raise ConfluenceError(f"{label} {value!r} is not a valid alphanumeric identifier")

    def get_page(self, page_id: str, *, body_format: str = "storage") -> dict[str, Any]:
        """Fetch a single page with body, labels, and version.

        The ``body_format`` selects the representation returned in
        ``body.<format>.value``.  ``storage`` (the default) returns the
        Confluence XHTML representation needed to PUT the page back; other
        values (``atlas_doc_format``, ``view``) are accepted by the API but
        not used by mdd today.
        """
        self._validate_id(page_id, "page_id")
        return self.get(
            f"/wiki/api/v2/pages/{page_id}",
            params={
                "body-format": body_format,
                "include-labels": "true",
                "include-version": "true",
            },
        )

    def get_page_ancestors(self, page_id: str) -> list[dict[str, Any]]:
        """Fetch the ancestor chain for a page.

        ``GET /wiki/api/v2/pages/{page_id}/ancestors``

        The Confluence v2 endpoint returns the ancestor chain
        **excluding** the page itself, ordered top-to-bottom: the
        highest ancestor (a space root) is ``results[0]`` and the
        direct parent is ``results[-1]``.  Each entry has at minimum
        ``id``, ``title``, ``parentId``, and ``spaceId``.

        Used by :mod:`mdd.confluence.mutate` (move-page) and
        :mod:`mdd.confluence.tree` (ancestor walk) to materialise
        missing ancestor mirror directories before placing the moved
        file under the new parent.

        Returns ``[]`` when the page has no ancestors (space root).
        """
        self._validate_id(page_id, "page_id")
        data = self.get(f"/wiki/api/v2/pages/{page_id}/ancestors")
        return _extract_dict_list(data, "results")

    def get_space(self, space_key: str) -> dict[str, Any]:
        """Fetch a space by key.

        GET /wiki/api/v2/spaces?keys=<space_key>

        Returns the first matching space dict.
        """
        data = self.get("/wiki/api/v2/spaces", params={"keys": space_key, "limit": 1})
        results_raw: Any = data.get("results")  # pyright: ignore[reportAny]
        if not isinstance(results_raw, list) or not results_raw:
            raise ConfluenceError(f"Space not found: {space_key!r}")
        first: Any = results_raw[0]  # pyright: ignore[reportAny, reportUnknownVariableType]
        if not isinstance(first, dict):
            raise ConfluenceError(f"Unexpected space result format for {space_key!r}")
        return first  # pyright: ignore[reportReturnType, reportUnknownVariableType]

    def get_folder(self, folder_id: str) -> dict[str, Any]:
        """Fetch a folder node by ID.

        GET /wiki/api/v2/folders/{folder_id}
        """
        self._validate_id(folder_id, "folder_id")
        return self.get(f"/wiki/api/v2/folders/{folder_id}")

    def list_page_attachments(self, page_id: str) -> list[dict[str, Any]]:
        """Return all attachments for a page using the v2 API.

        Replaces the deprecated v1 endpoint
        ``/wiki/rest/api/content/{id}/child/attachment`` (Atlassian
        scheduled it for removal — the response carries a ``Warning: 299``
        header and a ``deprecation`` date).

        Each attachment dict has at minimum:

        * ``id`` — attachment ID (e.g. ``att637340870``; the ``att`` prefix
          may or may not be present depending on tenant).
        * ``pageId`` — owning page ID; required for the REST download path.
        * ``title`` — filename.
        * ``fileSize`` — int, top-level (v1 buried it under ``extensions``).
        * ``mediaType`` — MIME type, top-level (v1 had it under ``extensions``).
        * ``version`` — dict with ``number``.
        * ``downloadLink`` — relative URL for the binary.  Not used by
          :meth:`download_attachment` / :meth:`download_attachment_to_file`
          (which build the REST download path from ``pageId`` + ``id``
          instead — see :func:`rest_attachment_download_path`).

        The pagination loop is bounded by ``MAX_PAGINATION_ITERATIONS`` as
        a safety guard against runaway loops.
        """
        self._validate_id(page_id, "page_id")
        results: list[dict[str, Any]] = []
        path = f"/wiki/api/v2/pages/{page_id}/attachments"
        params: dict[str, str | int] | None = {"limit": 250}
        for _ in range(MAX_PAGINATION_ITERATIONS):
            # ``params=None`` on follow-up pages; ``params={}`` would strip
            # the ``_links.next`` cursor.
            data = self.get(path, params=params)
            results.extend(_extract_dict_list(data, "results"))
            next_url = _extract_next_link(data)
            if not next_url:
                return results
            # next_url must be a relative path — reject absolute URLs (SSRF guard)
            assert_relative_api_path(next_url, "_links.next")
            path = next_url
            params = None
        raise ConfluenceError(
            f"list_page_attachments({page_id}): pagination exceeded "
            f"{MAX_PAGINATION_ITERATIONS} iterations — possible runaway loop"
        )

    def download_attachment(self, attachment: dict[str, Any]) -> bytes:
        """Download the raw bytes of an attachment via the REST endpoint.

        Builds the URL from ``pageId`` and ``id`` on the v2 attachment dict
        (see :func:`rest_attachment_download_path`).  The legacy
        ``/wiki/download/attachments/...`` path is gated to OAuth-only on
        some tenants; the REST path accepts Basic auth + API
        token instead.
        """
        download_url = rest_attachment_download_path(attachment)
        # Confluence 302-redirects to a signed CDN URL; httpx follows the
        # redirect and strips the Authorization header on the cross-origin
        # hop (the CDN carries its own JWT in the query string).
        return self.get_bytes(download_url, follow_redirects=True)

    def download_attachment_to_file(self, attachment: dict[str, Any], dest: Path) -> int:
        """Stream-download an attachment directly to *dest*, returning byte count.

        Unlike :meth:`download_attachment`, this method does not buffer the full
        body in memory — it writes chunks to the destination file as they arrive.
        The destination's parent directory must already exist.

        The body is streamed to a ``.<name>.<rand>.part`` sibling file and
        only atomically renamed onto *dest* once the response completes with
        success.  A failed download (4xx/5xx, transport error, partial body)
        therefore leaves *dest* untouched — no 0-byte stub gets left behind.

        Returns:
            Number of bytes written.
        """
        download_url = rest_attachment_download_path(attachment)

        url = self._base_url + download_url
        client = self._get_http()
        total = 0
        # Confluence 302-redirects attachment binaries to a signed CDN URL
        # (typically api.media.atlassian.com).  httpx defaults to NOT
        # following redirects; opt in here.  The Authorization header is
        # stripped automatically on the cross-origin hop — the CDN URL
        # carries its own short-lived JWT in the query string.
        #
        # NamedTemporaryFile keeps the partial download next to dest (same
        # filesystem, so Path.replace() is atomic), and the ``delete=False``
        # + manual cleanup pattern keeps the temp file around only on
        # success-then-rename or on exception cleanup below.
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=dest.parent,
            prefix=f".{dest.name}.",
            suffix=".part",
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)
            try:
                with client.stream("GET", url, follow_redirects=True) as response:
                    if not response.is_success:
                        body_preview = response.read()[:200].decode("utf-8", errors="replace")
                        raise ConfluenceError(
                            f"GET {download_url} failed with {response.status_code}: {body_preview}"
                        )
                    for chunk in response.iter_bytes(chunk_size=65536):
                        tmp.write(chunk)
                        total += len(chunk)
                tmp.flush()
            except BaseException:
                tmp.close()
                tmp_path.unlink(missing_ok=True)
                raise
        tmp_path.replace(dest)
        return total

    def upload_attachment(self, page_id: str, file_path: Path) -> dict[str, Any]:
        """Upload a file as an attachment to a Confluence page.

        Uses the v1 ``/wiki/rest/api/content/{page_id}/child/attachment`` endpoint
        with a multipart POST.  The ``X-Atlassian-Token: no-check`` header is
        already set on the underlying HTTP client.
        """
        self._validate_id(page_id, "page_id")
        path = f"/wiki/rest/api/content/{page_id}/child/attachment"
        url = self._base_url + path
        client = self._get_http()
        filename = file_path.name
        mime_type = "application/octet-stream"
        file_bytes = file_path.read_bytes()

        last_exc: Exception | None = None
        max_attempts = len(_RETRY_DELAYS) + 1
        for attempt, delay in enumerate((*_RETRY_DELAYS, None), start=1):
            try:
                response = client.request(
                    "POST",
                    url,
                    files={"file": (filename, file_bytes, mime_type)},
                )
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_exc = exc
                _log_transport_error("POST", path, exc, attempt, max_attempts)
                if delay is None:
                    break
                time.sleep(jittered_delay(delay))
                continue

            if response.is_success:
                result: Any = response.json()  # pyright: ignore[reportAny]
                if not isinstance(result, dict):
                    raise ConfluenceError(
                        f"Expected JSON object from POST {path}, got {type(result)}"
                    )
                return result  # pyright: ignore[reportReturnType, reportUnknownVariableType]

            if not should_retry(response):
                raise ConfluenceError(
                    f"POST {path} failed with {response.status_code}: {response.text[:200]}"
                )

            last_exc = ConfluenceError(
                f"POST {path} failed with {response.status_code}: {response.text[:200]}"
            )
            if delay is None:
                break
            time.sleep(backoff_for_response(response, delay))

        exc_summary = f": {type(last_exc).__name__}: {last_exc}" if last_exc is not None else ""
        raise ConfluenceError(
            f"POST {path} failed after {max_attempts} attempts{exc_summary}"
        ) from last_exc

    def post_page(
        self,
        *,
        space_id: str,
        parent_id: str | None,
        title: str,
        body: str,
        status: str = "current",
    ) -> dict[str, Any]:
        """Create a new page via POST /wiki/api/v2/pages.

        Returns the created page dict with id, version, _links, etc.
        """
        payload: dict[str, Any] = {
            "spaceId": space_id,
            "status": status,
            "title": title,
            "body": {
                "representation": "storage",
                "value": body,
            },
        }
        if parent_id is not None:
            payload["parentId"] = parent_id

        response = self._request("POST", "/wiki/api/v2/pages", json=payload)
        result: Any = response.json()  # pyright: ignore[reportAny]
        if not isinstance(result, dict):
            raise ConfluenceError(
                f"Expected JSON object from POST /wiki/api/v2/pages, got {type(result)}"
            )
        return result  # pyright: ignore[reportReturnType, reportUnknownVariableType]

    def put_page(
        self,
        page_id: str,
        title: str,
        body_xhtml: str,
        version: int,
        message: str = "",
        *,
        options: PutPageOptions | None = None,
    ) -> dict[str, Any]:
        """Update a page via PUT /wiki/api/v2/pages/{id}.

        ``options`` carries the optional fields move/archive/unarchive need
        (``parent_id`` to reparent the page, ``status`` to flip between
        ``"current"`` and ``"archived"``).  When omitted the call behaves
        exactly like the historic 5-positional signature — the page keeps
        its parent and remains current.  Bundling these in an options
        dataclass keeps :meth:`put_page` within the ``max-args`` quality
        gate while still letting move/archive callers share this primitive.
        """
        opts = options if options is not None else PutPageOptions()
        self._validate_id(page_id, "page_id")
        path = f"/wiki/api/v2/pages/{page_id}"
        payload: dict[str, Any] = {
            "id": page_id,
            "status": opts.status,
            "title": title,
            "body": {
                "representation": "storage",
                "value": body_xhtml,
            },
            "version": {
                "number": version,
                "message": message,
            },
        }
        if opts.parent_id is not None:
            payload["parentId"] = opts.parent_id
        response = self._request("PUT", path, json=payload)
        result: Any = response.json()  # pyright: ignore[reportAny]
        if not isinstance(result, dict):
            raise ConfluenceError(f"Expected JSON object from PUT {path}, got {type(result)}")
        return result  # pyright: ignore[reportReturnType, reportUnknownVariableType]

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST JSON payload to *path* and return the decoded JSON object.

        Helper used by archive/unarchive (and any future POST endpoint that
        returns a single resource).  Mirrors the shape of :meth:`get` so the
        ``_request → json → isinstance check`` ladder doesn't repeat.
        """
        response = self._request("POST", path, json=payload)
        result: Any = response.json()  # pyright: ignore[reportAny]
        if not isinstance(result, dict):
            raise ConfluenceError(f"Expected JSON object from POST {path}, got {type(result)}")
        return result  # pyright: ignore[reportReturnType, reportUnknownVariableType]

    def _put_archive_v1(self, page_id: str, *, status: str, message: str) -> dict[str, Any]:
        """v1 archive / unarchive PUT (fallback path).

        The v1 endpoint ``PUT /wiki/rest/api/content/{id}`` requires the
        page's current ``type`` and a bumped version; archive/unarchive flips
        ``status`` between ``"archived"`` and ``"current"``.
        """
        path = f"/wiki/rest/api/content/{page_id}"
        # Fetch current title + version so the v1 PUT is well-formed.
        current = self.get(f"/wiki/rest/api/content/{page_id}")
        version_raw: Any = current.get("version", {})  # pyright: ignore[reportAny]
        version_no: int = 1
        if isinstance(version_raw, dict):
            n: Any = version_raw.get("number")  # pyright: ignore[reportAny, reportUnknownMemberType, reportUnknownVariableType]
            if isinstance(n, int):
                version_no = n
        title_raw: Any = current.get("title", "")  # pyright: ignore[reportAny]
        title = title_raw if isinstance(title_raw, str) else ""
        payload: dict[str, Any] = {
            "id": page_id,
            "type": "page",
            "status": status,
            "title": title,
            "version": {"number": version_no + 1, "message": message},
        }
        response = self._request("PUT", path, json=payload)
        result: Any = response.json()  # pyright: ignore[reportAny]
        if not isinstance(result, dict):
            raise ConfluenceError(f"Expected JSON object from PUT {path}, got {type(result)}")
        return result  # pyright: ignore[reportReturnType, reportUnknownVariableType]

    def _archive_unarchive(self, page_id: str, *, action: str, message: str) -> dict[str, Any]:
        """Shared dispatch for archive_page / unarchive_page.

        ``action`` is either ``"archive"`` (→ v2 POST .../archive, v1 status
        ``"archived"``) or ``"unarchive"`` (→ v2 POST .../unarchive, v1
        status ``"current"``).  Atlassian has moved the v2 path around
        historically; on 404/405 we fall back to the v1 PUT.
        """
        self._validate_id(page_id, "page_id")
        v2_path = f"/wiki/api/v2/pages/{page_id}/{action}"
        v1_status = "archived" if action == "archive" else "current"
        try:
            return self._post_json(v2_path, {"message": message} if message else {})
        except ConfluenceError as exc:
            msg = str(exc)
            # v1 fallback only on "endpoint not present / not allowed";
            # any other failure (auth, 5xx, retry exhaustion) propagates.
            if "404" not in msg and "405" not in msg:
                raise
        return self._put_archive_v1(page_id, status=v1_status, message=message)

    def archive_page(self, page_id: str, *, message: str = "") -> dict[str, Any]:
        """Archive a page; tries v2 first, falls back to v1 on 404/405.

        Returns the API response dict.  The v2 archive endpoint
        (``POST /wiki/api/v2/pages/{id}/archive``) is preferred; if the
        tenant does not expose it, falls back to the v1 PUT with
        ``status: "archived"``.
        """
        return self._archive_unarchive(page_id, action="archive", message=message)

    def unarchive_page(self, page_id: str, *, message: str = "") -> dict[str, Any]:
        """Unarchive a page; tries v2 first, falls back to v1 on 404/405."""
        return self._archive_unarchive(page_id, action="unarchive", message=message)

    def get_user(self, account_id: str) -> dict[str, Any]:
        """Fetch a user by account ID (cached per client instance)."""
        if account_id in self._user_cache:
            return self._user_cache[account_id]
        result = self.get(
            "/wiki/rest/api/user",
            params={"accountId": account_id},
        )
        self._user_cache[account_id] = result
        return result

    def get_current_user(self) -> dict[str, Any]:
        """Fetch the currently authenticated user.

        GET /wiki/rest/api/user/current
        Returns a dict with at least ``accountId`` and ``displayName``.
        The v2 path ``/wiki/api/v2/users/current`` doesn't exist —
        Confluence routes ``users`` through the GenericContentType
        handler and returns 400.
        """
        return self.get("/wiki/rest/api/user/current")

    def get_page_restrictions(self, page_id: str) -> dict[str, Any]:
        """Fetch restriction info for a page.

        GET /wiki/rest/api/content/{page_id}/restriction
        Returns a dict with ``update`` and ``read`` keys (each containing
        a ``restrictions`` block).  An empty restrictions list means the
        restriction type is unrestricted (everyone can act).
        """
        self._validate_id(page_id, "page_id")
        return self.get(f"/wiki/rest/api/content/{page_id}/restriction")

    def close(self) -> None:
        if self._http is not None:
            self._http.close()
            self._http = None

    def __enter__(self) -> ConfluenceClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

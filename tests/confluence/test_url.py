"""Tests for mdd.confluence.url"""

import pytest

from mdd.confluence.url import PageRef, URLMismatchError, parse


class TestParseBareId:
    def test_bare_numeric_id(self) -> None:
        ref = parse("12345")
        assert ref == PageRef(host=None, space_key=None, page_id="12345")

    def test_bare_id_no_host(self) -> None:
        ref = parse("99")
        assert ref.host is None
        assert ref.space_key is None
        assert ref.page_id == "99"


class TestParseCanonicalUrl:
    def test_canonical_url(self) -> None:
        url = "https://example.atlassian.net/wiki/spaces/SPACE/pages/12345"
        ref = parse(url)
        assert ref.host == "example.atlassian.net"
        assert ref.space_key == "SPACE"
        assert ref.page_id == "12345"

    def test_url_with_slug(self) -> None:
        url = "https://example.atlassian.net/wiki/spaces/SPACE/pages/12345/My-Page-Title"
        ref = parse(url)
        assert ref.host == "example.atlassian.net"
        assert ref.space_key == "SPACE"
        assert ref.page_id == "12345"

    def test_url_with_query_string(self) -> None:
        url = "https://example.atlassian.net/wiki/spaces/SPACE/pages/12345/Slug?focusedCommentId=99"
        ref = parse(url)
        assert ref.page_id == "12345"
        assert ref.space_key == "SPACE"

    def test_url_with_long_slug_and_query(self) -> None:
        url = "https://example.atlassian.net/wiki/spaces/ENG/pages/67890/The+Page?foo=bar&baz=qux"
        ref = parse(url)
        assert ref.page_id == "67890"
        assert ref.space_key == "ENG"


class TestParseShortUrl:
    def test_short_url_returns_empty_page_id(self) -> None:
        url = "https://example.atlassian.net/wiki/x/AbCdEf"
        ref = parse(url)
        assert ref.host == "example.atlassian.net"
        assert ref.space_key is None
        assert ref.page_id == ""

    def test_short_url_different_base62(self) -> None:
        url = "https://example.atlassian.net/wiki/x/ZzZzZz123"
        ref = parse(url)
        assert ref.page_id == ""


class TestExpectedHost:
    def test_matching_host_no_error(self) -> None:
        url = "https://example.atlassian.net/wiki/spaces/SPACE/pages/12345"
        ref = parse(url, expected_host="example.atlassian.net")
        assert ref.page_id == "12345"

    def test_mismatched_host_raises(self) -> None:
        url = "https://other.atlassian.net/wiki/spaces/SPACE/pages/12345"
        with pytest.raises(URLMismatchError, match="other.atlassian.net"):  # noqa: RUF043
            parse(url, expected_host="example.atlassian.net")

    def test_no_expected_host_does_not_raise(self) -> None:
        url = "https://any.atlassian.net/wiki/spaces/SPACE/pages/12345"
        ref = parse(url, expected_host=None)
        assert ref.page_id == "12345"

    def test_bare_id_with_expected_host_no_error(self) -> None:
        # Bare ID has no host — expected_host check is skipped
        ref = parse("12345", expected_host="example.atlassian.net")
        assert ref.page_id == "12345"
        assert ref.host is None


class TestInvalidInput:
    def test_non_confluence_url_raises(self) -> None:
        with pytest.raises(ValueError):  # noqa: PT011
            parse("https://example.com/not-confluence")

    def test_alphanumeric_non_url_raises(self) -> None:
        with pytest.raises(ValueError):  # noqa: PT011
            parse("not-a-number-or-url")

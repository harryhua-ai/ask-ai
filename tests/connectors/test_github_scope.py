"""validate_github_token 单元测试(S4: 最小权限校验)。"""

from unittest.mock import MagicMock, patch

import pytest

from backend.connectors.github import validate_github_token


@pytest.mark.unit
def test_classic_token_readonly_passes() -> None:
    resp = MagicMock()
    resp.headers = {"x-oauth-scopes": "repo:read"}
    resp.raise_for_status = MagicMock()
    with patch("backend.connectors.github.httpx.Client") as m:
        m.return_value.__enter__.return_value.get.return_value = resp
        validate_github_token("token", strict=True)  # 不抛


@pytest.mark.unit
def test_classic_token_write_scope_fails_in_prod() -> None:
    resp = MagicMock()
    resp.headers = {"x-oauth-scopes": "repo, write:org"}
    resp.raise_for_status = MagicMock()
    with patch("backend.connectors.github.httpx.Client") as m:
        m.return_value.__enter__.return_value.get.return_value = resp
        with pytest.raises(RuntimeError):
            validate_github_token("token", strict=True)


@pytest.mark.unit
def test_classic_token_write_scope_warns_in_dev() -> None:
    resp = MagicMock()
    resp.headers = {"x-oauth-scopes": "repo"}
    resp.raise_for_status = MagicMock()
    with patch("backend.connectors.github.httpx.Client") as m:
        m.return_value.__enter__.return_value.get.return_value = resp
        validate_github_token("token", strict=False)  # 不抛,仅 warn


@pytest.mark.unit
def test_fine_grained_token_no_scopes_passes() -> None:
    resp = MagicMock()
    resp.headers = {"x-oauth-scopes": ""}  # fine-grained token 返回空
    resp.raise_for_status = MagicMock()
    with patch("backend.connectors.github.httpx.Client") as m:
        m.return_value.__enter__.return_value.get.return_value = resp
        validate_github_token("token", strict=True)


@pytest.mark.unit
def test_no_token_warns() -> None:
    validate_github_token("", strict=True)  # 不抛,仅 warn

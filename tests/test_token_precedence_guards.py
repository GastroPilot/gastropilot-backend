from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_core_auth_prefers_header_over_cookie_tokens() -> None:
    source = _read("services/core/app/api/routes/auth.py")

    assert "token = header_token or refresh_token_cookie" in source
    assert "token = header_token or access_token_cookie" in source
    assert "token = refresh_token_cookie or header_token" not in source
    assert "token = access_token_cookie or header_token" not in source


def test_orders_auth_prefers_header_over_cookie_tokens() -> None:
    source = _read("services/orders/app/core/deps.py")

    # get_current_user + get_current_user_or_device
    assert source.count("token = header_token or access_token") >= 2
    assert "token = access_token or header_token" not in source

from f2media.core.redact import MASK, redact_command, redact_text


def test_secrets_are_redacted():
    text = "Cookie: sessionid=abc; msToken=xyz Authorization: Bearer-SECRET"
    out = redact_text(text)
    assert "abc" not in out and "xyz" not in out and "Bearer-SECRET" not in out
    assert MASK in out


def test_cookie_arg_is_redacted():
    out = redact_command(["f2", "dy", "-k", "sessionid=secret", "-u", "https://example.com"])
    assert "secret" not in out


def test_dict_style_secrets_are_redacted():
    text = "{'cookie': 'sessionid=abc', 'X-Csrf-Token': 'csrf-secret', 'Authorization': 'Bearer token-secret'}"
    out = redact_text(text)
    assert "abc" not in out
    assert "csrf-secret" not in out
    assert "token-secret" not in out
    assert out.count(MASK) >= 3

from pathlib import Path


def test_facebook_resolver_is_shown_as_always_on_preprocessor_not_route_parser():
    html = Path("f2media/static/index.html").read_text(encoding="utf-8")
    assert "Facebook URL Resolver" in html
    assert "始终开启" in html
    assert "仅 Facebook" in html
    assert "不属于解析器排序" in html

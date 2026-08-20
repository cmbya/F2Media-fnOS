from f2media.core.cookie_format import (
    cookie_header_for_engine,
    header_to_netscape,
    is_netscape_cookie,
    netscape_to_header,
)


def test_header_to_netscape_roundtrip():
    jar = header_to_netscape("douyin", "a=1; b=hello")
    assert is_netscape_cookie(jar)
    back = netscape_to_header(jar)
    assert "a=1" in back and "b=hello" in back


def test_netscape_preserved_for_header():
    jar = "# Netscape HTTP Cookie File\n.douyin.com\tTRUE\t/\tTRUE\t0\tttwid\tabc\n"
    assert cookie_header_for_engine(jar) == "ttwid=abc"

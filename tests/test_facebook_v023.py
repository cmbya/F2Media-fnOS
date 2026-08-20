from f2media.parsers.facebook_resolver import (
    facebook_cli_target,
    facebook_cookie_credentials,
    is_facebook_url,
    normalize_known_facebook_url,
)


def test_facebook_group_multi_permalink_normalizes():
    url = "https://www.facebook.com/groups/851882484849213?multi_permalinks=28938059365804815&hoisted_section_header_type=recently_seen"
    assert normalize_known_facebook_url(url) == "https://www.facebook.com/groups/851882484849213/posts/28938059365804815/"


def test_facebook_reel_uses_reel_command_not_post():
    assert facebook_cli_target("https://www.facebook.com/reel/2300217217408960") == ("reel", "2300217217408960")


def test_facebook_group_post_stays_post_command():
    url = "https://www.facebook.com/groups/851882484849213/posts/28938059365804815/"
    assert facebook_cli_target(url) == ("post", url)


def test_facebook_video_and_photo_use_media_commands():
    assert facebook_cli_target("https://www.facebook.com/someone/videos/123456789/") == ("video", "123456789")
    assert facebook_cli_target("https://www.facebook.com/photo.php?fbid=99887766") == ("photo", "99887766")


def test_facebook_cookie_credentials_from_netscape():
    cookie = "# Netscape HTTP Cookie File\n.facebook.com\tTRUE\t/\tTRUE\t0\tc_user\t12345\n.facebook.com\tTRUE\t/\tTRUE\t0\txs\tabc%3Axyz\n"
    assert facebook_cookie_credentials(cookie) == ("12345", "abc%3Axyz")


def test_resolver_scope_never_accepts_other_platforms():
    assert is_facebook_url("https://www.facebook.com/share/r/19AYvZ9V76/")
    assert not is_facebook_url("https://v.douyin.com/abcdef/")
    assert not is_facebook_url("https://x.com/user/status/123")
    assert normalize_known_facebook_url("https://v.douyin.com/abcdef/") == "https://v.douyin.com/abcdef/"

from f2media.parse_service import ParseService


def test_group_permalink_normalizes_to_posts():
    src = "https://www.facebook.com/groups/851882484849213/permalink/28938059365804815/#"
    assert ParseService._canonicalize_facebook_url(src) == (
        "https://www.facebook.com/groups/851882484849213/posts/28938059365804815/"
    )


def test_group_multi_permalink_normalizes_to_posts():
    src = (
        "https://www.facebook.com/groups/851882484849213"
        "?multi_permalinks=28938059365804815&hoisted_section_header_type=recently_seen"
    )
    assert ParseService._canonicalize_facebook_url(src) == (
        "https://www.facebook.com/groups/851882484849213/posts/28938059365804815/"
    )


def test_reel_normalizes_to_watch_even_with_suffix_noise():
    src = "https://www.facebook.com/reel/2300217217408960z"
    assert ParseService._canonicalize_facebook_url(src) == (
        "https://www.facebook.com/watch/?v=2300217217408960"
    )


def test_watch_keeps_video_id_and_drops_fragment():
    src = "https://www.facebook.com/watch/?v=2300217217408960#"
    assert ParseService._canonicalize_facebook_url(src) == (
        "https://www.facebook.com/watch/?v=2300217217408960"
    )


def test_profile_post_drops_fragment():
    src = "https://www.facebook.com/mookk.thanyachanok.3/posts/pfbid02Y9cMM42BkGjgpsavr1X2RSoYKUxyUVyBSYd7AWU4WLwCKD3gqMBicC79dnU594e4l#"
    assert ParseService._canonicalize_facebook_url(src).endswith(
        "/mookk.thanyachanok.3/posts/pfbid02Y9cMM42BkGjgpsavr1X2RSoYKUxyUVyBSYd7AWU4WLwCKD3gqMBicC79dnU594e4l"
    )


def test_html_candidates_extract_group_post_and_watch():
    body = r'''<html><head>
    <link rel="canonical" href="https://www.facebook.com/groups/851882484849213/permalink/28938059365804815/#">
    </head><script>
    var x={"url":"https:\/\/www.facebook.com\/reel\/2300217217408960"}
    </script></html>'''
    rows = ParseService._facebook_candidates_from_html(body)
    assert "https://www.facebook.com/groups/851882484849213/posts/28938059365804815/" in rows
    assert "https://www.facebook.com/watch/?v=2300217217408960" in rows


def test_permalink_php_keeps_story_and_owner_only():
    src = (
        "https://www.facebook.com/permalink.php?story_fbid=pfbid02Y9cMM42BkGjgpsavr1X2RSoYKUxyUVyBSYd7AWU4WLwCKD3gqMBicC79dnU594e4l"
        "&id=1000123456789&__cft__[0]=abc#fragment"
    )
    assert ParseService._canonicalize_facebook_url(src) == (
        "https://www.facebook.com/permalink.php?"
        "story_fbid=pfbid02Y9cMM42BkGjgpsavr1X2RSoYKUxyUVyBSYd7AWU4WLwCKD3gqMBicC79dnU594e4l"
        "&id=1000123456789"
    )


def test_ytdlp_redirect_output_extracts_group_post_and_reel():
    text = """
    [redirect] Following redirect to https://www.facebook.com/groups/851882484849213/permalink/28938059365804815/?__cft__[0]=abc
    [redirect] Following redirect to https://www.facebook.com/reel/2300217217408960/?mibextid=abc
    """
    rows = ParseService._facebook_candidates_from_ytdlp_output(text)
    assert "https://www.facebook.com/groups/851882484849213/posts/28938059365804815/" in rows
    assert "https://www.facebook.com/watch/?v=2300217217408960" in rows


def test_ytdlp_redirect_output_extracts_permalink_php():
    text = (
        "[redirect] Following redirect to "
        "https://www.facebook.com/permalink.php?story_fbid=pfbidABC123&id=123456789&__cft__[0]=zzz"
    )
    rows = ParseService._facebook_candidates_from_ytdlp_output(text)
    assert (
        "https://www.facebook.com/permalink.php?story_fbid=pfbidABC123&id=123456789"
        in rows
    )

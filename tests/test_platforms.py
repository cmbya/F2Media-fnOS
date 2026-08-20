from f2media.core.platforms import parse_input, platform_for_url


def test_mobile_share_text():
    got = parse_input("复制打开抖音 https://v.douyin.com/abc/ 看视频")
    assert got[0].platform == "douyin"
    assert got[0].url == "https://v.douyin.com/abc/"


def test_platform_aliases():
    assert platform_for_url("https://x.com/a/status/1") == "twitter"
    assert platform_for_url("https://b23.tv/abc") == "bilibili"
    assert platform_for_url("https://xhslink.com/a") == "xiaohongshu"
    assert platform_for_url("https://v.kuaishou.com/a") == "kuaishou"
    assert platform_for_url("https://fb.watch/a") == "facebook"


def test_xiaohongshu_cn_short_link():
    assert platform_for_url("https://xhslink.cn/o/7vXtXs5hr7d") == "xiaohongshu"

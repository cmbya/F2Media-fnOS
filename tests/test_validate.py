from f2media.core.validate import validate_output


def test_no_files_is_failure():
    assert validate_output("douyin", [])[0] == "failed"


def test_douyin_live_pair_success():
    status, _ = validate_output("douyin", ["a_image_1.webp", "a_live_1.mp4"])
    assert status == "success"


def test_douyin_unpaired_dynamic_partial():
    status, _ = validate_output("douyin", ["a_live_1.mp4"])
    assert status == "partial"

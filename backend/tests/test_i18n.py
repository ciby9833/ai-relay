from app import i18n


def test_detect_user_language():
    assert i18n.detect("Jennifer Angelina 需要我做什么？") == "zh"
    assert i18n.detect("Tolong cek email dari Jennifer, apa yang harus saya kerjakan?") == "id"
    assert i18n.detect("Can you check what Jennifer needs from me?") == "en"
    assert i18n.detect("发吧") == "zh"
    assert i18n.detect("ok") is None
    assert i18n.detect("https://jetcargo.feishu.cn/sheets/abc") is None


def test_explicit_setting_wins_over_detected():
    assert i18n.user_language({"language": "auto", "detected_language": "id"}) == "id"
    assert i18n.user_language({"language": "en", "detected_language": "id"}) == "en"
    assert i18n.user_language({}) == "zh"
    assert i18n.learn({"detected_language": "zh"}, "Tolong kirim laporan yang sudah saya minta") == {"detected_language": "id"}
    assert i18n.learn({"detected_language": "zh"}, "好的") is None


def test_ui_strings_follow_current_language():
    token = i18n.current.set("id")
    try:
        assert i18n.ui("approve") == "Setujui"
        assert i18n.ui("things_to_know", n=3) == "Relay | 3 hal yang perlu Anda ketahui"
    finally:
        i18n.current.reset(token)
    assert i18n.ui("approve") == "批准"

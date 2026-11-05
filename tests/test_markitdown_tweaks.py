import app.markitdown_tweaks as tweaks


def test_check_magika_stub_matches_current_markitdown() -> None:
    tweaks.check_magika_stub()


def test_stub_identifies_nothing() -> None:
    if not tweaks._STUBBED:
        return
    result = tweaks._Magika().identify_stream(None)  # type: ignore[arg-type]
    assert result.status == "failed"

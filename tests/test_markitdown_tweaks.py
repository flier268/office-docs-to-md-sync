import pytest

import app.markitdown_tweaks as tweaks


def test_check_magika_stub_matches_current_markitdown() -> None:
    tweaks.check_magika_stub()


def test_check_magika_stub_skips_source_inspection_when_frozen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tweaks.sys, "frozen", True, raising=False)

    def boom(*_args: object, **_kwargs: object) -> str:
        raise OSError("could not get source code")

    monkeypatch.setattr(tweaks.inspect, "getsource", boom)
    tweaks.check_magika_stub()


def test_stub_identifies_nothing() -> None:
    if not tweaks._STUBBED:
        return
    result = tweaks._Magika().identify_stream(None)  # type: ignore[arg-type]
    assert result.status == "failed"

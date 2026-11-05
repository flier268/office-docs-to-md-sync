"""markitdown library tweaks: a stand-in for magika, which markitdown imports but this app does not need.

magika, with the onnxruntime model behind it, sniffs a file's type from its bytes. markitdown imports it
at the top of its main module and loads its model in `MarkItDown()`, about 50 MB held for the life of the
process. Every file this app converts arrives with its extension, which markitdown keeps as its guess
when magika identifies nothing, so magika is excluded from the lock (`exclude-dependencies` in the root
pyproject.toml) and the stub below answers in its place. The stub is registered when this module is
imported, which has to happen before markitdown is.

Making magika optional is requested in https://github.com/microsoft/markitdown/issues/1234 and
implemented, unmerged, in https://github.com/microsoft/markitdown/pull/1355. Once markitdown no longer
needs magika, delete this module and the exclusion.
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
from types import ModuleType, SimpleNamespace
from typing import BinaryIO

# The markitdown code the stub answers: magika constructed in MarkItDown.__init__, and asked to
# identify a stream in _get_stream_info_guesses, whose result is used only when its status is "ok".
_EXPECTED_SOURCE = {
    "__init__": ("magika.Magika()",),
    "_get_stream_info_guesses": ("self._magika.identify_stream(", 'result.status == "ok"'),
}


class _Magika:
    """magika.Magika as markitdown calls it, identifying nothing."""

    def identify_stream(self, stream: BinaryIO) -> SimpleNamespace:
        # Not raising: markitdown calls this inside try/finally, with no except.
        return SimpleNamespace(status="failed")


_STUBBED = importlib.util.find_spec("magika") is None
if _STUBBED:
    _magika = ModuleType("magika")
    _magika.Magika = _Magika  # type: ignore[attr-defined]
    sys.modules["magika"] = _magika


def check_magika_stub() -> None:
    """Fail when markitdown no longer calls magika the way the stub answers. A changed call could
    reach what the stub lacks, and a release that drops magika no longer needs the stub at all."""
    if not _STUBBED:
        return
    from markitdown import MarkItDown

    missing = [
        f"{method}: {snippet}"
        for method, snippets in _EXPECTED_SOURCE.items()
        for snippet in snippets
        if snippet not in inspect.getsource(getattr(MarkItDown, method))
    ]
    if missing:
        raise RuntimeError(
            f"markitdown no longer uses magika as the stub in {__name__} expects ({'; '.join(missing)}). "
            "Revisit the stub, or remove it with the magika exclusion if magika is optional upstream "
            "(https://github.com/microsoft/markitdown/issues/1234)."
        )

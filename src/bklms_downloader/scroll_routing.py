"""Small, Tk-independent primitives for exclusive nested wheel ownership."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ScrollRoute:
    """The chosen scroll owner and whether the original wheel event is consumed."""

    owner: str | None
    consume: bool


def is_descendant_of(widget: Any, ancestor: Any) -> bool:
    """Return whether ``widget`` is ``ancestor`` or one of its Tk descendants."""
    current = widget
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        if current is ancestor:
            return True
        seen.add(id(current))
        current = getattr(current, "master", None)
    return False


def choose_scroll_route(
    widget: Any,
    regions: Iterable[tuple[str, Iterable[Any]]],
    *,
    fallback_owner: str | None = None,
) -> ScrollRoute:
    """Choose the first matching region; caller order encodes child priority.

    The decision deliberately does not inspect a scrollbar position.  A hovered
    child keeps ownership at its top/bottom boundary, preventing scroll chaining
    to the main page.
    """
    for owner, roots in regions:
        if any(root is not None and is_descendant_of(widget, root) for root in roots):
            return ScrollRoute(owner=owner, consume=True)
    return ScrollRoute(owner=fallback_owner, consume=fallback_owner is not None)


class WheelBindingRegistry:
    """Install global wheel bindings once for a GUI lifetime."""

    def __init__(self) -> None:
        self._installed = False

    @property
    def installed(self) -> bool:
        return self._installed

    def install_once(self, toplevel: Any, callback: Any) -> bool:
        if self._installed:
            return False
        # ``add=False`` intentionally replaces CustomTkinter's competing
        # bind_all wheel callbacks.  The application router below explicitly
        # dispatches every supported scroll region instead.
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            toplevel.bind_all(sequence, callback, add=False)
        self._installed = True
        return True

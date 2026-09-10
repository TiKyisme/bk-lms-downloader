"""Small, Tk-independent primitives for exclusive nested wheel ownership."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
import customtkinter as ctk


class RoutedScrollableFrame(ctk.CTkScrollableFrame):
    """Our router owns wheel input; CTk must not accumulate global callbacks."""
    def bind_all(self, sequence=None, func=None, add=None):
        if sequence in {
            "<MouseWheel>", "<KeyPress-Shift_L>", "<KeyPress-Shift_R>",
            "<KeyRelease-Shift_L>", "<KeyRelease-Shift_R>",
        }:
            return None
        return super().bind_all(sequence, func, add)


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
        # A first bindtag consumes input before Text/Scrollbar widget and class
        # handlers; an "all" handler alone is too late to prevent double scroll.
        tag = f"ExclusiveWheel{id(self)}"
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            toplevel.bind_class(tag, sequence, callback)

        def attach(widget):
            tags = widget.bindtags()
            if tag not in tags:
                widget.bindtags((tag, *tags))
            for child in widget.winfo_children():
                attach(child)

        attach(toplevel)
        # Map events cover new rows and modal descendants without installing
        # a callback per widget or retaining references to destroyed rows.
        toplevel.bind_all("<Map>", lambda event: attach(event.widget), add="+")
        self._installed = True
        return True

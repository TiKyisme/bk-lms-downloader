from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UITheme:
    """Small, centralized light-theme palette for the desktop interface."""

    bg: str = "#F7F8FA"
    surface: str = "#FFFFFF"
    surface_muted: str = "#F9FBFD"
    inset: str = "#F5F7FA"
    border: str = "#DDE2E8"
    primary: str = "#0B6FFB"
    primary_hover: str = "#075ED8"
    primary_soft: str = "#EDF5FF"
    success: str = "#14A344"
    success_soft: str = "#EDF9F0"
    danger: str = "#DC3545"
    danger_soft: str = "#FFF1F2"
    text: str = "#172033"
    muted_text: str = "#667085"
    row_hover: str = "#F4F8FE"
    selected_row: str = "#EEF6FF"
    radius: int = 14
    button_radius: int = 11
    spacing: int = 16
    font_family: str = "Segoe UI"


THEME = UITheme()

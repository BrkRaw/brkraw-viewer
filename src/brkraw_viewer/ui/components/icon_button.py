from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from typing import Optional
from ..sharedtypes import Command


@dataclass(frozen=True)
class IconButtonStyle:
    hover_bg: Optional[str] = "#dddddd"
    press_bg: Optional[str] = "#bbbbbb"
    cursor: str = "hand2"


class IconButton(tk.Label):
    """
    Label-based icon button with hover/press feedback.
    - Executes command on ButtonRelease-1 (only if released over the widget).
    - Avoids native Button focus/outline artifacts (esp. macOS).
    """

    def __init__(
        self,
        master: tk.Misc,
        *,
        image: Optional[tk.PhotoImage] = None,
        command: Optional[Command] = None,
        style: Optional[IconButtonStyle] = None,
        enabled: bool = True,
        tooltip: Optional[str] = None,
        **kwargs,
    ) -> None:
        self._style = style or IconButtonStyle()
        self._command: Optional[Command] = command
        self._enabled = bool(enabled)
        self._pressed = False
        self._tooltip_text = tooltip

        # Important: keep a stable base bg for restore.
        # If bg not provided, inherit from master at creation time.
        if "bg" not in kwargs and "background" not in kwargs:
            try:
                kwargs["bg"] = master.cget("bg")
            except Exception:
                pass

        if image is not None:
            kwargs["image"] = image

        super().__init__(
            master,
            bd=0,
            highlightthickness=0,
            takefocus=0,
            **kwargs,
        )

        # Cache base bg for reliable restore.
        self._base_bg = str(self.cget("bg"))

        # Bind events.
        self.bind("<Enter>", self._on_enter, add=True)
        self.bind("<Leave>", self._on_leave, add=True)
        self.bind("<ButtonPress-1>", self._on_press, add=True)
        self.bind("<ButtonRelease-1>", self._on_release, add=True)

        # Optional: simple tooltip hook placeholders (no-op unless you implement).
        # You can wire this later to your own tooltip component.
        if self._tooltip_text:
            self.bind("<Enter>", self._maybe_show_tooltip, add=True)
            self.bind("<Leave>", self._maybe_hide_tooltip, add=True)

        self._apply_enabled_state()

    def set_command(self, command: Optional[Command]) -> None:
        self._command = command

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        self._pressed = False
        self._apply_enabled_state()
        self.configure(bg=self._base_bg)

    def is_enabled(self) -> bool:
        return self._enabled

    def set_style(self, style: IconButtonStyle) -> None:
        self._style = style
        self._apply_enabled_state()

    def _apply_enabled_state(self) -> None:
        if self._enabled:
            self.configure(cursor=self._style.cursor)
        else:
            self.configure(cursor="arrow")

    def _is_over_self(self, e: tk.Event) -> bool:
        try:
            x_root = int(getattr(e, "x_root"))
            y_root = int(getattr(e, "y_root"))
            wx = self.winfo_rootx()
            wy = self.winfo_rooty()
            return (wx <= x_root < wx + self.winfo_width()) and (wy <= y_root < wy + self.winfo_height())
        except Exception:
            return False

    def _set_bg(self, color: Optional[str]) -> None:
        if not color:
            return
        try:
            self.configure(bg=color)
        except Exception:
            pass

    def _on_enter(self, e: tk.Event) -> None:
        if not self._enabled:
            return
        if not self._pressed:
            self._set_bg(self._style.hover_bg)

    def _on_leave(self, e: tk.Event) -> None:
        if not self._enabled:
            return
        if not self._pressed:
            self._set_bg(self._base_bg)

    def _on_press(self, e: tk.Event) -> None:
        if not self._enabled:
            return
        self._pressed = True
        self._set_bg(self._style.press_bg)

    def _on_release(self, e: tk.Event) -> None:
        if not self._enabled:
            return

        was_pressed = self._pressed
        self._pressed = False

        over = self._is_over_self(e)
        if over:
            self._set_bg(self._style.hover_bg)
        else:
            self._set_bg(self._base_bg)

        if was_pressed and over and self._command:
            # Important for popup focus weirdness: execute on release.
            try:
                self._command()
            except Exception:
                # Do not raise inside Tk callback.
                pass

    # Tooltip placeholders - implement later when needed.
    def _maybe_show_tooltip(self, e: tk.Event) -> None:
        return

    def _maybe_hide_tooltip(self, e: tk.Event) -> None:
        return
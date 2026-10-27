"""Три ползунка с единым интерфейсом получения и выставления значений."""

import tkinter as tk
from tkinter import ttk
from typing import Callable

# Диапазоны совпадают с engine.workflow.normalize_spec.
SLIDER_CONFIG = {
    "width": ("Ширина", 0.55, 1.40),
    "slant": ("Наклон", -20.0, 20.0),
    "spacing": ("Интервал", 0.0, 100.0),
}


class SliderPanel(ttk.LabelFrame):
    """Сам интерфейс не сохраняет состояние — этим занимается FontSession."""

    def __init__(self, parent, on_release: Callable[[], None]):
        super().__init__(parent, text="Параметры шрифта", padding=12)
        self.variables = {}
        self.scales = {}
        self.labels = {}
        self._loading = False

        for row, (field, (title, start, end)) in enumerate(SLIDER_CONFIG.items()):
            ttk.Label(self, text=title).grid(row=row * 2, column=0, sticky="w", pady=(9, 0))
            value_text = ttk.Label(self, width=9, anchor="e")
            value_text.grid(row=row * 2, column=1, sticky="e", pady=(9, 0))

            variable = tk.DoubleVar(value=1.0 if field == "width" else 0.0)
            scale = ttk.Scale(
                self,
                variable=variable,
                from_=start,
                to=end,
                command=lambda _v, f=field: self._update_label(f),
            )
            scale.grid(row=row * 2 + 1, column=0, columnspan=2, sticky="ew", pady=(0, 9))
            scale.bind("<ButtonRelease-1>", lambda _event: on_release())
            # Позволяет менять значения с клавиатуры, а не только мышкой.
            scale.bind("<KeyRelease>", lambda _event: on_release())
            self.variables[field] = variable
            self.scales[field] = scale
            self.labels[field] = value_text

        self.columnconfigure(0, weight=1)
        self.set_values({"width": 1.0, "slant": 0.0, "spacing": 0})
        self.set_enabled(False)

    def _update_label(self, field: str):
        if self._loading:
            return
        value = self.get_values()[field]
        if field == "width":
            text = f"{value:.2f}×"
        elif field == "slant":
            text = f"{value:+.1f}°"
        else:
            text = str(value)
        self.labels[field].configure(text=text)

    def get_values(self) -> dict:
        """Округляем дробные значения и приводим spacing к int."""
        return {
            "width": round(self.variables["width"].get(), 2),
            "slant": round(self.variables["slant"].get(), 1),
            "spacing": int(round(self.variables["spacing"].get())),
        }

    def set_values(self, params: dict):
        self._loading = True
        for field in SLIDER_CONFIG:
            self.variables[field].set(params[field])
        self._loading = False
        for field in SLIDER_CONFIG:
            self._update_label(field)

    def set_enabled(self, enabled: bool):
        for slider in self.scales.values():
            slider.configure(state="normal" if enabled else "disabled")

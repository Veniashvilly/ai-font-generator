"""Панель отображения PNG, полученного из настоящего TTF."""

import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageOps, ImageTk


class PreviewPanel(ttk.LabelFrame):
    def __init__(self, parent):
        super().__init__(parent, text="Предпросмотр шрифта", padding=9)
        self.image = None           # Исходный PIL Image
        self.tk_image = None        # Ссылка нужна, чтобы Tkinter не удалил картинку
        self._resize_id = None
        self.image_label = tk.Label(
            self, text="Опиши шрифт и нажми «Создать»", bg="#f6f7f9",
            fg="#4b5563", font=("Segoe UI", 12),
        )
        self.image_label.pack(fill="both", expand=True)
        self.image_label.bind("<Configure>", self._schedule_resize)
        self.note = ttk.Label(
            self, text="Пока нет результата", anchor="w", wraplength=700
        )
        self.note.pack(fill="x", pady=(8, 1))

    def set_picture(self, image: Image.Image, description: str):
        self.image = image
        self.note.configure(text=description)
        self._resize()

    def set_note(self, description: str):
        self.note.configure(text=description)

    def _schedule_resize(self, _event=None):
        if self._resize_id is not None:
            self.after_cancel(self._resize_id)
        self._resize_id = self.after(120, self._resize)

    def _resize(self):
        self._resize_id = None
        if self.image is None:
            return
        available_width = max(120, self.image_label.winfo_width() - 12)
        available_height = max(120, self.image_label.winfo_height() - 12)
        scaled = ImageOps.contain(
            self.image, (available_width, available_height), Image.Resampling.LANCZOS
        )
        self.tk_image = ImageTk.PhotoImage(scaled)
        self.image_label.configure(image=self.tk_image, text="")

"""Главное окно локального редактора шрифтов.

Архитектура:
- Tkinter работает ТОЛЬКО в главном потоке;
- GigaChat и генерация TTF выполняются в фоновых daemon-потоках;
- результаты передаются в GUI через Queue, без вызовов Tk из потоков;
- FontSession отвечает за сохранение параметров, снимки и историю версий;
- ползунок создаёт черновик, а ИИ получает актуальные значения.
"""

from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from PIL import Image

from engine.session_state import FontSession
from gui.controls import SliderPanel
from gui.preview_panel import PreviewPanel
from gui.tasks import make_draft_preview, read_preview, revise_from_prompt, start_from_prompt


class FontEditorWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AI Font Editor — локальное тестирование")
        self.geometry("1180x790")
        self.minsize(860, 600)

        self.session: FontSession | None = None
        self.busy = False
        self.notifications: queue.Queue = queue.Queue()
        self.preview_serial = 0        # Версии запросов предпросмотра; устаревшие игнорируем.
        self.preview_after_id = None

        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TButton", padding=7)
        style.configure("TLabel", font=("Segoe UI", 10))
        style.configure("TLabelframe.Label", font=("Segoe UI", 10, "bold"))

        self._build_ui()
        self._set_busy(False)
        self.after(100, self._drain_results)
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _build_ui(self):
        self.columnconfigure(0, weight=4)
        self.columnconfigure(1, weight=2)
        self.rowconfigure(0, weight=1)

        # СЛЕВА: настоящий предпросмотр + история сессии.
        left = ttk.Frame(self, padding=(12, 12, 6, 8))
        left.grid(row=0, column=0, sticky="nsew")
        left.rowconfigure(0, weight=4)
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)

        self.preview = PreviewPanel(left)
        self.preview.grid(row=0, column=0, sticky="nsew")

        history_frame = ttk.LabelFrame(left, text="История сохранений", padding=8)
        history_frame.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        history_frame.rowconfigure(0, weight=1)
        history_frame.columnconfigure(0, weight=1)
        self.history_box = tk.Text(
            history_frame, height=6, state="disabled", wrap="word",
            bg="#f6f7f9", fg="#17212b", font=("Consolas", 9)
        )
        self.history_box.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(history_frame, command=self.history_box.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.history_box.configure(yscrollcommand=scrollbar.set)

        # СПРАВА: ползунки, чат, управление сессией.
        right = ttk.Frame(self, padding=(6, 12, 12, 8))
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)

        self.sliders = SliderPanel(right, on_release=self._sliders_released)
        self.sliders.grid(row=0, column=0, sticky="ew")

        self.font_label = ttk.Label(
            right, text="Исходный шрифт: —", wraplength=340, foreground="#495361"
        )
        self.font_label.grid(row=1, column=0, sticky="ew", pady=(9, 6))

        input_frame = ttk.LabelFrame(right, text="Запрос к GigaChat", padding=10)
        input_frame.grid(row=2, column=0, sticky="nsew")
        input_frame.columnconfigure(0, weight=1)
        input_frame.rowconfigure(1, weight=1)
        ttk.Label(
            input_frame,
            text="Сначала опиши шрифт. Потом пиши изменения: «убери наклон».",
            wraplength=320,
        ).grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.prompt_box = tk.Text(input_frame, height=6, wrap="word", font=("Segoe UI", 11))
        self.prompt_box.grid(row=1, column=0, sticky="nsew", pady=(0, 9))
        self.send_button = ttk.Button(input_frame, text="Создать шрифт", command=self._send_prompt)
        self.send_button.grid(row=2, column=0, sticky="ew")

        actions = ttk.Frame(right)
        actions.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        self.new_button = ttk.Button(actions, text="Новая сессия", command=self._new_session)
        self.new_button.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        self.open_button = ttk.Button(actions, text="Папка с TTF", command=self._open_output)
        self.open_button.grid(row=0, column=1, sticky="ew", padx=(3, 0))

        resume_box = ttk.LabelFrame(right, text="Продолжить сессию по ID", padding=9)
        resume_box.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        resume_box.columnconfigure(0, weight=1)
        self.resume_entry = ttk.Entry(resume_box)
        self.resume_entry.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.resume_button = ttk.Button(resume_box, text="Открыть", command=self._resume_session)
        self.resume_button.grid(row=0, column=1)
        self.session_label = ttk.Label(resume_box, text="ID: —", foreground="#495361")
        self.session_label.grid(row=1, column=0, columnspan=2, sticky="w", pady=(5, 0))

        self.status = tk.StringVar(value="Напиши запрос, чтобы получить первый TTF.")
        status_frame = ttk.Frame(self, padding=(13, 6))
        status_frame.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.status_label = ttk.Label(status_frame, textvariable=self.status, wraplength=1050)
        self.status_label.pack(side="left", fill="x", expand=True)

    def _set_busy(self, value: bool):
        """Блокируем редактирование, пока ИИ работает со снимком состояния."""
        self.busy = value
        self.sliders.set_enabled(self.session is not None and not value)
        self.send_button.configure(state="disabled" if value else "normal")
        self.send_button.configure(text="Применить правку ИИ" if self.session else "Создать шрифт")
        self.new_button.configure(state="disabled" if value else "normal")
        self.resume_button.configure(state="disabled" if value else "normal")
        self.open_button.configure(state="normal" if self.session else "disabled")

    def _run_background(self, kind: str, fn, *args, **kwargs):
        """Все тяжёлые операции — в фоновом потоке, никогда в Tkinter."""
        def runner():
            try:
                result = fn(*args, **kwargs)
                self.notifications.put((kind, result, None))
            except Exception as error:
                self.notifications.put((kind, None, error))
        threading.Thread(target=runner, daemon=True).start()

    def _send_prompt(self):
        if self.busy:
            return
        prompt = self.prompt_box.get("1.0", "end").strip()
        if not prompt:
            messagebox.showinfo("Нет запроса", "Напиши пожелания к шрифту.")
            return

        # Если ползунок ещё перетаскивали, берём его ПОСЛЕДНЕЕ значение.
        if self.session:
            try:
                self._save_sliders(schedule_preview=False)
                snapshot, revision = self.session.prepare_ai_request()
            except (ValueError, RuntimeError, OSError) as error:
                self._error(error)
                return
            self.status.set("GigaChat получает актуальные значения ползунков…")
            self._set_busy(True)
            self._invalidate_previews()
            self._update_history()
            self._run_background(
                "revise", revise_from_prompt, self.session, prompt, snapshot, revision
            )
        else:
            self.status.set("GigaChat выбирает исходный TTF и параметры…")
            self._set_busy(True)
            self._invalidate_previews()
            self._run_background("initial", start_from_prompt, prompt)

    def _sliders_released(self):
        if not self.session or self.busy:
            return
        try:
            self._save_sliders(schedule_preview=True)
        except (ValueError, RuntimeError, OSError) as error:
            self._error(error)
            self.sliders.set_values(self.session.params)

    def _save_sliders(self, schedule_preview: bool):
        """Сохраняем только JSON-черновик в sessions/.../state.json."""
        assert self.session is not None
        values = self.sliders.get_values()
        changed = False
        for field, value in values.items():
            changed = self.session.set_slider(field, value) or changed
        self.sliders.set_values(self.session.params)

        if changed:
            self._update_history()
            self.status.set("Ползунки сохранены в черновик. Версия TTF не создавалась.")
            if schedule_preview:
                self._schedule_draft_preview()
        return changed

    def _invalidate_previews(self):
        self.preview_serial += 1
        if self.preview_after_id is not None:
            self.after_cancel(self.preview_after_id)
            self.preview_after_id = None

    def _schedule_draft_preview(self):
        """После отпускания ползунка ждём 550 мс и строим точный TTF-превью."""
        self._invalidate_previews()
        serial = self.preview_serial
        self.preview.set_note("Обновляем предпросмотр после изменения ползунка…")
        self.preview_after_id = self.after(
            550, lambda: self._run_draft_preview(serial)
        )

    def _run_draft_preview(self, serial: int):
        self.preview_after_id = None
        if self.busy or not self.session or serial != self.preview_serial:
            return
        snapshot = self.session.params
        self._run_background("draft", self._produce_draft_preview, snapshot, serial)

    @staticmethod
    def _produce_draft_preview(snapshot: dict, serial: int):
        """Возвращаем serial вместе с изображением для отсечения старых задач."""
        return serial, make_draft_preview(snapshot)

    @staticmethod
    def _read_saved_preview(ttf_path: Path, serial: int):
        return serial, read_preview(ttf_path)

    def _drain_results(self):
        """Обновляет Tkinter ТОЛЬКО из GUI-потока."""
        try:
            while True:
                kind, payload, error = self.notifications.get_nowait()
                if kind == "draft":
                    # payload: (serial, PIL Image) — оформляется в _run_draft_preview.
                    if error is not None:
                        self.status.set(f"Ошибка предпросмотра черновика: {error}")
                    else:
                        serial, picture = payload
                        if serial == self.preview_serial and not self.busy:
                            self.preview.set_picture(picture, "Черновик ползунков — TTF в историю не сохранён")
                elif kind == "saved":
                    if error is not None:
                        self.status.set(f"Не получилось открыть прошлый предпросмотр: {error}")
                    else:
                        serial, picture = payload
                        if serial == self.preview_serial and self.session and not self.busy:
                            self.preview.set_picture(
                                picture, "Последний созданный TTF: " + str(self.session.latest_ttf)
                            )
                elif kind == "initial":
                    self._set_busy(False)
                    if error:
                        self._error(error)
                    else:
                        session, picture, message = payload
                        self.session = session
                        self._load_from_session(picture)
                        self.status.set("Шрифт создан! Можно менять ползунки или писать правки.")
                        self.prompt_box.delete("1.0", "end")
                elif kind == "revise":
                    self._set_busy(False)
                    if error:
                        self._error(error)
                        self._update_history()
                    else:
                        picture, message, generated = payload
                        self._load_from_session(picture)
                        self.status.set("ИИ применил изменения и обновил TTF." if generated else "ИИ вернул уже имеющиеся настройки.")
                        self.prompt_box.delete("1.0", "end")
        except queue.Empty:
            pass
        self.after(120, self._drain_results)

    def _load_from_session(self, picture: Image.Image):
        assert self.session is not None
        self.sliders.set_values(self.session.params)
        self.font_label.configure(text="Исходный: " + self.session.params["base_font"])
        self.session_label.configure(text="ID: " + self.session.data["session_id"])
        self.resume_entry.delete(0, "end")
        self.resume_entry.insert(0, self.session.data["session_id"])
        self._update_history()
        self._set_busy(False)
        self.preview.set_picture(picture, "Последний созданный TTF: " + str(self.session.latest_ttf))

    def _update_history(self):
        if not self.session:
            return
        lines = []
        for version in self.session.history:
            p = version["params"]
            action = {
                "initial": "ИИ создал",
                "manual_snapshot": "Ползунки сохранены",
                "ai_revision": "ИИ изменил",
            }.get(version["kind"], version["kind"])
            lines.append(
                f"{version['id']} · {action} · ширина {p['width']}, "
                f"наклон {p['slant']}°, интервал {p['spacing']}"
            )
        if self.session.is_dirty:
            lines.append("Черновик · ручные изменения, ещё не зафиксированы как версия")
        self.history_box.configure(state="normal")
        self.history_box.delete("1.0", "end")
        self.history_box.insert("1.0", "\n".join(lines))
        self.history_box.configure(state="disabled")
        self.history_box.see("end")

    def _resume_session(self):
        if self.busy:
            return
        session_id = self.resume_entry.get().strip()
        try:
            session = FontSession.load(session_id)
            if not session.latest_ttf.is_file():
                raise FileNotFoundError("TTF последней версии не найден")
        except (ValueError, OSError) as error:
            self._error(error)
            return
        self.session = session
        self._invalidate_previews()
        self.sliders.set_values(session.params)
        self.font_label.configure(text="Исходный: " + session.params["base_font"])
        self.session_label.configure(text="ID: " + session_id)
        self._update_history()
        self._set_busy(False)
        self.status.set("Сессия восстановлена из sessions/.../state.json")
        if session.is_dirty:
            self._schedule_draft_preview()
        else:
            self._run_background("saved", self._read_saved_preview, session.latest_ttf, self.preview_serial)

    def _new_session(self):
        if self.busy:
            return
        self._invalidate_previews()
        self.session = None
        self.preview.image = None
        self.preview.tk_image = None
        self.preview.image_label.configure(image="", text="Опиши новый шрифт")
        self.preview.set_note("Пока нет результата")
        self.sliders.set_values({"width": 1.0, "slant": 0.0, "spacing": 0})
        self.font_label.configure(text="Исходный шрифт: —")
        self.session_label.configure(text="ID: —")
        self.history_box.configure(state="normal")
        self.history_box.delete("1.0", "end")
        self.history_box.configure(state="disabled")
        self._set_busy(False)
        self.status.set("Новая сессия. Предыдущие версии остались на диске.")

    def _open_output(self):
        if not self.session:
            return
        folder = self.session.latest_ttf.parent
        if os.name == "nt":
            os.startfile(str(folder))
        else:
            messagebox.showinfo("Путь к TTF", str(folder))

    def _error(self, error: Exception):
        self.status.set("Ошибка: " + str(error))
        messagebox.showerror("Не удалось выполнить действие", str(error))

    def _close(self):
        self._invalidate_previews()
        self.destroy()

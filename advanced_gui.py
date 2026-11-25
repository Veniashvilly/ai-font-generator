"""Небольшой локальный редактор новых параметров. Без серверов и GigaChat.

Запуск на Windows: python advanced_gui.py
Старые gui/, ai/, engine/session_state.py и прочее не изменяются.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tkinter as tk
from dataclasses import asdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from engine.advanced_generator import AdvancedConfig, ROOT

FONT_FOLDER = ROOT / "fonts" / "base"
CONFIG_FILE = ROOT / "advanced_config.json"

# Даже если кривые декоративного TTF вызовут зависание внешней библиотеки,
# интерфейс освободится после тайм-аута. Отдельный дочерний Python
# завершится, а не останется зависшим потоком внутри Tkinter.
GENERATION_TIMEOUT_SECONDS = 40
LARGE_FONT_TIMEOUT_SECONDS = 90


class AdvancedEditor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AI Font Generator — новые параметры (эксперимент)")
        self.geometry("1330x800")
        self.minsize(900, 620)
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.pending = None
        self.picture = None  # PhotoImage необходимо хранить, иначе Tkinter удалит рисунок

        self.font_paths = sorted(FONT_FOLDER.rglob("*.ttf"))
        self.font_names = [str(p.relative_to(FONT_FOLDER)).replace("\\", "/") for p in self.font_paths]
        self.font_name = tk.StringVar()
        if self.font_names:
            preferred = next((p for p in self.font_names if "tuffy-regular" in p.lower()), None)
            preferred = preferred or next((p for p in self.font_names if "inter" in p.lower() and "regular" in p.lower() and "variable" not in p.lower()), None)
            self.font_name.set(preferred or self.font_names[0])

        defaults = {}
        if CONFIG_FILE.exists():
            try:
                defaults = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                defaults = {}
        self.vars = {}
        for name in AdvancedConfig.__dataclass_fields__:
            value = defaults.get(name, getattr(AdvancedConfig(), name))
            self.vars[name] = tk.StringVar(value=value) if name == "serif_style" else tk.DoubleVar(value=float(value))

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _build_ui(self):
        main = ttk.PanedWindow(self, orient="horizontal")
        main.pack(fill="both", expand=True, padx=12, pady=12)
        left = ttk.Frame(main, width=350)
        right = ttk.Frame(main)
        main.add(left, weight=1)
        main.add(right, weight=3)

        # Скролл с ползунками: на маленьком экране настройки не исчезают.
        scroll = tk.Canvas(left, borderwidth=0, highlightthickness=0)
        bar = ttk.Scrollbar(left, orient="vertical", command=scroll.yview)
        scroll.configure(yscrollcommand=bar.set)
        scroll.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        form = ttk.Frame(scroll, padding=(9, 8))
        window_id = scroll.create_window((0, 0), window=form, anchor="nw")
        form.bind("<Configure>", lambda _: scroll.configure(scrollregion=scroll.bbox("all")))
        scroll.bind("<Configure>", lambda e: scroll.itemconfigure(window_id, width=e.width))

        ttk.Label(form, text="Исходный TTF", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 6))
        if not self.font_names:
            ttk.Label(form, text="Нет TTF в fonts/base!", foreground="red").pack(anchor="w")
        else:
            ttk.Combobox(form, textvariable=self.font_name, values=self.font_names, state="readonly", width=44).pack(fill="x")

        ttk.Separator(form).pack(fill="x", pady=12)
        ttk.Label(form, text="Геометрия", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        self._slider(form, "Ширина букв", "width", 0.55, 1.40, 0.01)
        self._slider(form, "Наклон, градусы", "slant", -20, 20, 1)
        self._slider(form, "Межбуквенный интервал", "spacing", -20, 100, 1)

        ttk.Separator(form).pack(fill="x", pady=12)
        ttk.Label(form, text="Штрихи и углы", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        self._slider(form, "Жирность", "weight_scale", 0.75, 1.35, 0.01)
        self._slider(form, "Скругление углов", "corner_roundness", 0.00, 0.45, 0.01)
        ttk.Label(
            form,
            text=("Жирность меняет толщину штрихов. Скругление смягчает острые углы.\n"
                  "Оба параметра потом можно будет отдавать в GigaChat."),
            foreground="#555555", wraplength=330, justify="left"
        ).pack(anchor="w", pady=(0, 5))

        ttk.Separator(form).pack(fill="x", pady=12)
        ttk.Label(form, text="Внутренние просветы", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        self._slider(form, "Размер отверстий в А, О, В...", "counter_scale", .7, 1.3, .01)
        ttk.Label(
            form, text="1.00 — оригинал. На тонких штрихах увеличение ограничивается автоматически.",
            foreground="#555555", wraplength=330, justify="left"
        ).pack(anchor="w", pady=(0, 5))

        ttk.Separator(form).pack(fill="x", pady=12)
        ttk.Label(form, text="Засечки (эксперимент)", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(form, text="Форма").pack(anchor="w", pady=(5, 0))
        ttk.Combobox(form, textvariable=self.vars["serif_style"], values=["none", "slab", "wedge", "bracket"], state="readonly").pack(fill="x")
        self._slider(form, "Длина засечек (доля em)", "serif_length", .005, .12, .005)
        self._slider(form, "Толщина засечек (доля em)", "serif_thickness", .005, .09, .005)
        self._slider(form, "Сопряжение (bracket)", "serif_bracket", 0, .09, .005)
        self._slider(form, "Угол торца, градусы", "serif_angle", -25, 25, 1)

        ttk.Label(form, text="Засечки: H I L E F T / Н П Г Т Ш.\nДля других букв — пока без эффекта.", foreground="#555555", justify="left").pack(anchor="w", pady=9)

        # Панель предпросмотра справа.
        ttk.Label(right, text="Сравнение исходного и изменённого шрифта", font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=12, pady=(4, 8))
        self.image_label = ttk.Label(right, text="Выбери параметры и нажми «Сгенерировать»", anchor="center")
        self.image_label.pack(fill="both", expand=True, padx=12, pady=8)
        self.status_var = tk.StringVar(value="Готов к генерации")
        ttk.Label(right, textvariable=self.status_var, wraplength=830).pack(anchor="w", padx=12, pady=5)
        row = ttk.Frame(right)
        row.pack(fill="x", padx=12, pady=12)
        self.generate_button = ttk.Button(row, text="Сгенерировать и сравнить", command=self._start)
        self.generate_button.pack(side="left", padx=(0, 12))
        ttk.Button(row, text="Сохранить JSON настроек", command=self._save_config).pack(side="left")

    def _slider(self, form, label, name, minimum, maximum, resolution):
        ttk.Label(form, text=label).pack(anchor="w", pady=(10, 0))
        # tk.Scale позволяет задавать точное разрешение шага.
        tk.Scale(
            form, from_=minimum, to=maximum, orient="horizontal",
            resolution=resolution, variable=self.vars[name], showvalue=True,
            length=290, borderwidth=0, highlightthickness=0,
        ).pack(fill="x", padx=0, pady=0)

    def _values(self) -> AdvancedConfig:
        values = {k: float(v.get()) for k, v in self.vars.items() if k != "serif_style"}
        values["serif_style"] = self.vars["serif_style"].get()
        values["spacing"] = round(values["spacing"])
        return AdvancedConfig.from_dict(values)

    def _save_config(self):
        try:
            data = {key: getattr(self._values(), key) for key in AdvancedConfig.__dataclass_fields__}
            filename = filedialog.asksaveasfilename(
                initialdir=ROOT, initialfile="advanced_config.json",
                defaultextension=".json", filetypes=[("JSON", "*.json")],
            )
            if filename:
                Path(filename).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                self.status_var.set("Сохранены параметры: " + filename)
        except Exception as error:
            messagebox.showerror("Не удалось сохранить", str(error))

    def _start(self):
        if self.pending is not None:
            return
        if not self.font_name.get():
            messagebox.showerror("Нет шрифта", "Добавь TTF в папку fonts/base")
            return
        try:
            config = self._values()
            source = FONT_FOLDER / self.font_name.get()
        except Exception as error:
            messagebox.showerror("Неверные параметры", str(error))
            return
        self.generate_button.configure(state="disabled")
        self.status_var.set("Генерируем TTF и PNG в отдельном процессе...")
        self.pending = self.executor.submit(self._work, source, config)
        self.after(150, self._check)

    @staticmethod
    def _work(source, config):
        # Запускаем тяжёлую геометрию в отдельном ПРОЦЕССЕ, а не в потоке.
        # subprocess.run(timeout=...) позволяет реально прервать зависание.
        command = [
            sys.executable, "-X", "utf8", str(ROOT / "advanced_worker.py"),
            str(source), json.dumps(asdict(config), ensure_ascii=False),
        ]
        timeout = GENERATION_TIMEOUT_SECONDS
        if source.is_file():
            from fontTools.ttLib import TTFont
            try:
                with TTFont(source, lazy=True) as metadata:
                    if metadata["maxp"].numGlyphs > 2500:
                        timeout = LARGE_FONT_TIMEOUT_SECONDS
            except Exception:
                pass  # The worker reports invalid TTF files itself.
        try:
            finished = subprocess.run(
                command, cwd=ROOT, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                timeout=timeout, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Генерация остановлена после {timeout} секунд. "
                "У выбранного декоративного шрифта слишком сложные контуры. "
                "Попробуй другой шрифт или настройки без засечек."
            ) from exc
        if finished.returncode != 0:
            detail = (finished.stderr or finished.stdout).strip()
            raise RuntimeError("Ошибка генератора:\n" + detail[-1600:])
        try:
            payload = json.loads(finished.stdout)
            return Path(payload["ttf"]), Path(payload["preview"]), payload["report"]
        except (ValueError, KeyError) as exc:
            raise RuntimeError("Генератор вернул некорректный результат") from exc

    def _check(self):
        if not self.pending.done():
            self.after(150, self._check)
            return
        task = self.pending
        self.pending = None
        self.generate_button.configure(state="normal")
        try:
            result, image, report = task.result()
            with Image.open(image) as image_file:
                view = image_file.copy()
            view.thumbnail((935, 590), Image.Resampling.LANCZOS)
            self.picture = ImageTk.PhotoImage(view)
            self.image_label.configure(image=self.picture, text="")
            limited = report.get("counter_safety_limited", 0)
            skipped_complex = report.get("counter_complexity_skipped", 0)
            skipped_effects = report.get("effect_complexity_skipped", {})
            missing_union = report.get("serifs_added", 0) and not report.get("serif_overlaps_merged", False)
            extra = (
                f"\nЖирность: изменены контуры ({report.get('weight_changed_contours', 0)}); "
                f"углов скруглено: {report.get('rounded_points', 0)}."
                f"\nЗащита тонких штрихов: {limited} ограничений; "
                f"неоднозначных окончаний: {report.get('serif_ambiguous_stems', 0)}."
            )
            # Диагностика: теперь видны A / B / O / e / q / я,
            # а не только три заглавные кириллические буквы.
            # Это НЕ новые настройки: все буквы управляются ОДНИМ ползунком.
            examples = report.get("counter_examples", {})
            if examples:
                for group in (("A", "B", "O", "e", "q", "я"), ("А", "В", "О", "8")):
                    display = []
                    for letter in group:
                        data = examples.get(letter)
                        if data is None:
                            continue  # символ отсутствует в исходном TTF
                        if data.get("holes", 0) > 0:
                            found = data["effective_scale"]
                            note = "*" if data.get("recovery_used") else ""
                            display.append(f"{letter}: {found:.2f}{note}")
                        else:
                            display.append(f"{letter}: нет распознанного отверстия")
                    if display:
                        extra += "\nПросветы: " + ", ".join(display)
                if any(d.get("recovery_used") for d in examples.values()):
                    extra += "\n* Контуры восстановлены по залитой области или через skia-pathops."
            filled = report.get("filled_geometry_v8", {})
            if filled:
                extra += (f"\nV8: сложных глифов изменено — жирность {filled.get('weight_glyphs', 0)}, "
                          f"просветы {filled.get('counter_glyphs', 0)}; ошибок {filled.get('errors', 0)}.")
            timings = report.get("timing_seconds", {})
            if timings:
                extra += (
                    f"\nВремя: TTF {timings.get('total', 0):.1f} с "
                    f"(глифы {timings.get('glyph_processing', 0):.1f}, "
                    f"засечки {timings.get('overlap_removal', 0):.1f}), "
                    f"PNG {report.get('preview_seconds', 0):.1f} с"
                )
            if skipped_complex or any(skipped_effects.values()):
                extra += (
                    f"\nСложная геометрия: просветы пропущены у {skipped_complex} глифов; "
                    f"другие эффекты ограничены у {sum(skipped_effects.values())} глифов. "
                    "Это защита от зависания и повреждения декоративного рисунка."
                )
            elif report.get("counter_contours_changed", 0) == 0 and self.vars["counter_scale"].get() != 1:
                extra += "\nПросветы не изменились: у этого шрифта могут отсутствовать отдельные замкнутые отверстия."
            if missing_union:
                extra += "\nСовет: установи skia-pathops для склеивания пересекающихся засечек."
            self.status_var.set(
                f"TTF: {result}\n"
                f"Изменено внутренних контуров: {report['counter_contours_changed']}; "
                f"засечек добавлено: {report['serifs_added']}" + extra
            )
        except Exception as error:
            self.status_var.set("Ошибка генерации: " + str(error))
            messagebox.showerror("Генерация не удалась", str(error))

    def _close(self):
        # Не блокируем окно ожиданием чужого потока.
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.destroy()


if __name__ == "__main__":
    app = AdvancedEditor()
    app.mainloop()

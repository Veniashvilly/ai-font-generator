"""All advanced controls, compact notebook layout."""
import tkinter as tk
from tkinter import ttk
from engine.workflow import DEFAULTS

SLIDER_CONFIG = {
    'width': ('Ширина', .55, 1.4), 'slant': ('Наклон', -20, 20),
    'spacing': ('Интервал', -20, 100), 'weight_scale': ('Жирность', .75, 1.35),
    'counter_scale': ('Размер очка', .7, 1.3), 'corner_roundness': ('Скругление', 0, .45),
    'serif_length': ('Длина', .005, .12), 'serif_thickness': ('Толщина', .005, .09),
    'serif_bracket': ('Сопряжение', 0, .09), 'serif_angle': ('Угол', -25, 25),
}

class SliderPanel(ttk.LabelFrame):
    def __init__(self, parent, on_release):
        super().__init__(parent, text='Параметры шрифта', padding=6)
        self.variables, self.scales, self.labels = {}, {}, {}
        self._loading = False
        self.columnconfigure(0, weight=1)
        tabs = ttk.Notebook(self)
        tabs.grid(row=0, column=0, sticky='ew')
        for title, fields in [('Основные', list(SLIDER_CONFIG)[:3]), ('Форма', list(SLIDER_CONFIG)[3:6]), ('Засечки', list(SLIDER_CONFIG)[6:])]:
            frame = ttk.Frame(tabs, padding=4)
            frame.columnconfigure(0, weight=1)
            tabs.add(frame, text=title)
            offset = 0
            if title == 'Засечки':
                ttk.Label(frame, text='Тип засечек').grid(row=0,column=0,sticky='w')
                self.variables['serif_style'] = tk.StringVar(value='none')
                self.style_choice = ttk.Combobox(frame, textvariable=self.variables['serif_style'], values=('none','slab','wedge','bracket'), state='readonly', width=12)
                self.style_choice.grid(row=0,column=1,sticky='e')
                self.style_choice.bind('<<ComboboxSelected>>', lambda e:on_release())
                offset = 1
            for i, field in enumerate(fields):
                label, low, high = SLIDER_CONFIG[field]
                row = offset+i*2
                ttk.Label(frame,text=label).grid(row=row,column=0,sticky='w')
                self.labels[field] = ttk.Label(frame,width=8,anchor='e')
                self.labels[field].grid(row=row,column=1,sticky='e')
                var = self.variables[field] = tk.DoubleVar(value=DEFAULTS[field])
                scale = self.scales[field] = ttk.Scale(frame,variable=var,from_=low,to=high,command=lambda v,f=field:self._update_label(f))
                scale.grid(row=row+1,column=0,columnspan=2,sticky='ew',pady=(0,3))
                scale.bind('<ButtonRelease-1>',lambda e:on_release())
                scale.bind('<KeyRelease>',lambda e:on_release())
        self.set_values(DEFAULTS)
        self.set_enabled(False)

    def _update_label(self, field):
        if not self._loading and field in self.labels:
            self.labels[field].configure(text=f'{self._value(field):.4g}')

    def _value(self, field):
        v = self.variables[field].get()
        if field == 'serif_style': return v
        if field == 'spacing': return int(round(v))
        return v

    def get_values(self):
        return {f:self._value(f) for f in self.variables}

    def set_values(self, params):
        self._loading = True
        for f,var in self.variables.items(): var.set(params.get(f, DEFAULTS[f]))
        self._loading = False
        for f in self.labels:self._update_label(f)

    def set_enabled(self, enabled):
        for s in self.scales.values():s.configure(state='normal' if enabled else 'disabled')
        self.style_choice.configure(state='readonly' if enabled else 'disabled')

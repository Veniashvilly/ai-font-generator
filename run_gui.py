"""Запуск локального редактора (Windows): python run_gui.py."""

from gui.window import FontEditorWindow


if __name__ == "__main__":
    app = FontEditorWindow()
    app.mainloop()

"""Состояние одной сессии редактирования шрифта.

Не зависит от GUI и GigaChat: работает с уже готовыми параметрами и патчами.

Три события в истории:
  1) initial        — первый успешный TTF от ИИ;
  2) manual_snapshot — снимок ползунков перед запросом к ИИ (без TTF);
  3) ai_revision    — новый успешный TTF после ответа ИИ.

Движение ползунка обновляет current_params и черновик на диске,
но НЕ создаёт новую версию и НЕ запускает генератор.
"""

from __future__ import annotations

import copy
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from engine.catalog import ROOT
from engine.workflow import generate_from_spec, normalize_spec

SESSIONS_DIR = ROOT / "sessions"
SLIDER_FIELDS = {"width", "slant", "spacing"}
SPEC_FIELDS = ("base_font", "width", "slant", "spacing", "script")


def _timestamp() -> str:
    """Время UTC для записей истории."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_json(path: Path, data: dict) -> None:
    """Сначала записываем временный файл, потом заменяем JSON целиком."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def _read_json(path: Path) -> dict:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"Ожидался JSON-объект: {path}")
    return obj


def _stored_path(path: Path) -> str:
    """Пути внутри проекта храним относительными: так удобнее переносить проект."""
    path = Path(path).resolve()
    try:
        return path.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def _resolved_path(stored: str) -> Path:
    path = Path(stored)
    return path if path.is_absolute() else ROOT / path


def _params_only(raw: dict) -> dict:
    """Отбрасываем служебные поля генератора, оставляем только настройки."""
    return normalize_spec({key: raw[key] for key in SPEC_FIELDS if key in raw})


class StateConflictError(RuntimeError):
    """Состояние изменилось после отправки запроса к ИИ."""


class FontSession:
    """Одна сессия: актуальные параметры, история и последний созданный TTF."""

    def __init__(self, path: Path, data: dict):
        self.path = Path(path)
        self.data = data

    @classmethod
    def start(
        cls,
        spec: dict,
        ttf_path: Path,
        message: str = "",
        sessions_dir: Path = SESSIONS_DIR,
    ) -> "FontSession":
        """Событие 1: сохраняем первый успешный результат ИИ."""
        spec = _params_only(spec)
        ttf_path = Path(ttf_path)
        if not ttf_path.is_file():
            raise FileNotFoundError(f"TTF не найден: {ttf_path}")

        session_id = uuid.uuid4().hex[:12]
        state_file = Path(sessions_dir) / session_id / "state.json"
        data = {
            "session_id": session_id,
            "revision": 1,
            "current_params": copy.deepcopy(spec),
            "draft_dirty": False,
            "latest_ttf": _stored_path(ttf_path),
            "versions": [{
                "id": "v1",
                "kind": "initial",
                "created_at": _timestamp(),
                "parent": None,
                "params": copy.deepcopy(spec),
                "ttf": _stored_path(ttf_path),
                "message": message,
            }],
        }
        _write_json(state_file, data)
        return cls(state_file, data)

    @classmethod
    def load(cls, session_id: str, sessions_dir: Path = SESSIONS_DIR) -> "FontSession":
        """Продолжаем редактирование после закрытия терминала."""
        # Защита от произвольных путей в ID сессии.
        if not session_id or any(c not in "0123456789abcdef" for c in session_id):
            raise ValueError("Неверный ID сессии")
        path = Path(sessions_dir) / session_id / "state.json"
        return cls(path, _read_json(path))

    @property
    def params(self) -> dict:
        """Актуальные параметры: всегда включают последние изменения ползунков."""
        return copy.deepcopy(self.data["current_params"])

    @property
    def latest_ttf(self) -> Path:
        """Последний УСПЕШНО созданный TTF, даже если есть новый черновик."""
        return _resolved_path(self.data["latest_ttf"])

    @property
    def history(self) -> list[dict]:
        return copy.deepcopy(self.data["versions"])

    @property
    def is_dirty(self) -> bool:
        return bool(self.data["draft_dirty"])

    def _save(self) -> None:
        _write_json(self.path, self.data)

    def _assert_revision(self, expected: int) -> None:
        """Не применяем запоздалый ответ ИИ поверх более свежих изменений."""
        disk = _read_json(self.path)
        if disk.get("revision") != expected or self.data["revision"] != expected:
            raise StateConflictError(
                "Параметры изменились, пока отвечал ИИ. "
                "Обнови состояние и повтори запрос."
            )

    def set_slider(self, field: str, value: int | float) -> bool:
        """Ползунок отпущен: сохраняем черновик, не генерируя новый TTF.

        Возвращает True, только если значение реально изменилось.
        """
        if field not in SLIDER_FIELDS:
            raise ValueError(f"Ползунок {field!r} не поддерживается")
        # Запрещаем менять устаревший снимок после внешней записи.
        self._assert_revision(self.data["revision"])
        updated = _params_only({**self.params, field: value})
        if updated == self.data["current_params"]:
            return False
        self.data["current_params"] = updated
        # Если пользователь вернул все значения назад, черновик не отличается.
        self.data["draft_dirty"] = updated != self.data["versions"][-1]["params"]
        self.data["revision"] += 1
        self._save()
        return True

    def prepare_ai_request(self) -> tuple[dict, int]:
        """Событие 2: фиксируем ручные правки ПЕРЕД запросом модели.

        Если ручных изменений не было, не создаём лишнюю версию.
        Возвращаем снимок параметров и номер ревизии (для защиты от гонок).
        """
        self._assert_revision(self.data["revision"])
        if self.is_dirty:
            previous = self.data["versions"][-1]
            new_id = f"v{len(self.data['versions']) + 1}"
            self.data["versions"].append({
                "id": new_id,
                "kind": "manual_snapshot",
                "created_at": _timestamp(),
                "parent": previous["id"],
                "params": self.params,
                "ttf": None,  # Сохраняем только JSON; TTF пока старый.
                "message": "Настройки ползунков перед запросом к ИИ",
            })
            self.data["draft_dirty"] = False
            self.data["revision"] += 1
            self._save()
        return self.params, self.data["revision"]

    def apply_ai_patch(
        self,
        patch: dict,
        expected_revision: int,
        message: str = "",
    ) -> tuple[Path, bool]:
        """Событие 3: применяем ответ модели поверх текущих настроек.

        TTF всегда создаётся из ИСХОДНОГО шрифта через generate_from_spec.
        При ошибке генерации история не меняется.
        Возвращает (путь_к_TTF, был_ли_создан_новый_файл).
        """
        self._assert_revision(expected_revision)
        if not isinstance(patch, dict) or not patch or set(patch) - SLIDER_FIELDS:
            raise ValueError("От ИИ допускаются только width, slant, spacing")

        merged = _params_only({**self.params, **patch})
        last_generated = next(
            version for version in reversed(self.data["versions"]) if version["ttf"]
        )

        # Можно повторно использовать уже готовый TTF, если вернулись к его
        # точным параметрам. Но событие ИИ всё равно фиксируем в истории,
        # когда перед ним был ручной снимок ползунков.
        if merged == last_generated["params"]:
            previous = self.data["versions"][-1]
            if merged != previous["params"]:
                self.data["versions"].append({
                    "id": f"v{len(self.data['versions']) + 1}",
                    "kind": "ai_revision",
                    "created_at": _timestamp(),
                    "parent": previous["id"],
                    "params": copy.deepcopy(merged),
                    "ttf": self.data["latest_ttf"],
                    "message": message,
                })
                self.data["revision"] += 1
                self.data["current_params"] = merged
                self.data["draft_dirty"] = False
                self._save()
            return self.latest_ttf, False

        parent_ttf_id = self.latest_ttf.parent.name
        new_ttf = generate_from_spec(merged, parent_version=parent_ttf_id)
        if not new_ttf.is_file():
            raise RuntimeError("Генератор не создал TTF")

        # Проверяем ещё раз после долгой генерации (актуально для будущего GUI).
        self._assert_revision(expected_revision)
        previous = self.data["versions"][-1]
        self.data["versions"].append({
            "id": f"v{len(self.data['versions']) + 1}",
            "kind": "ai_revision",
            "created_at": _timestamp(),
            "parent": previous["id"],
            "params": copy.deepcopy(merged),
            "ttf": _stored_path(new_ttf),
            "message": message,
        })
        self.data["current_params"] = merged
        self.data["latest_ttf"] = _stored_path(new_ttf)
        self.data["draft_dirty"] = False
        self.data["revision"] += 1
        self._save()
        return new_ttf, True

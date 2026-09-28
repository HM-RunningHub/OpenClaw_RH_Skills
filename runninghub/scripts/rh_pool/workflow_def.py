"""Workflow task-type definitions: loading, lookup, and validation.

Loads the unified config/task-types.json (real) or .example, exposes task
types by id, and validates each type's parameter mapping against the raw
workflow export archived at config/workflows/<workflowId>.json.

A task-type describes the *callable contract* (a small whitelist of input
params); the raw export is the *graph truth source* used to verify that every
nodeId/fieldName actually exists and matches its declared type.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parents[1]                 # runninghub/
CONFIG_DIR = SKILL_DIR / "config"
WORKFLOWS_DIR = CONFIG_DIR / "workflows"

SCHEMA_VERSION = "rh-task-types/1"

# Param value kinds
SCALAR_TYPES = {"text", "string", "int", "float", "bool", "enum", "json"}
FILE_TYPES = {"image", "audio", "video"}
ALL_TYPES = SCALAR_TYPES | FILE_TYPES

# Raw node class_type hints for cross-checking file params.
_IMAGE_CLASSES = {"LoadImage"}
_AUDIO_CLASSES = {"LoadAudio"}
# field name is not class-restricted for video; only existence is checked.


class DefinitionError(Exception):
    """A task-type definition is malformed or fails validation."""


@dataclass
class Param:
    name: str
    label: str
    type: str
    nodeId: str
    fieldName: str
    required: bool = False
    default: Any = None
    accept: list[str] = field(default_factory=list)
    enum: list[Any] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "Param":
        for key in ("name", "type", "nodeId", "fieldName"):
            if not d.get(key):
                raise DefinitionError(f"param missing '{key}': {d}")
        if d["type"] not in ALL_TYPES:
            raise DefinitionError(
                f"param '{d['name']}' has unknown type '{d['type']}'"
            )
        return cls(
            name=str(d["name"]),
            label=str(d.get("label") or d["name"]),
            type=str(d["type"]),
            nodeId=str(d["nodeId"]),
            fieldName=str(d["fieldName"]),
            required=bool(d.get("required", False)),
            default=d.get("default"),
            accept=list(d.get("accept") or []),
            enum=list(d.get("enum") or []),
        )


@dataclass
class TaskType:
    typeId: str
    version: int
    displayName: str
    description: str
    workflowId: str
    instanceType: str
    params: list[Param]
    fixedOverrides: list[dict] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "TaskType":
        for key in ("typeId", "workflowId"):
            if not d.get(key):
                raise DefinitionError(f"task type missing '{key}': {d}")
        return cls(
            typeId=str(d["typeId"]),
            version=int(d.get("version", 1)),
            displayName=str(d.get("displayName") or d["typeId"]),
            description=str(d.get("description", "")),
            workflowId=str(d["workflowId"]),
            instanceType=str(d.get("instanceType") or "default"),
            params=[Param.from_dict(p) for p in d.get("params") or []],
            fixedOverrides=list(d.get("fixedOverrides") or []),
        )

    def param(self, name: str) -> Param | None:
        return next((p for p in self.params if p.name == name), None)


# --------------------------------------------------------------------- loading
def _candidate_paths() -> list[Path]:
    env = CONFIG_DIR  # symmetry with config.py; explicit env override:
    import os
    override = os.environ.get("RH_TASK_TYPES")
    if override:
        return [Path(override)]
    return [CONFIG_DIR / "task-types.json", CONFIG_DIR / "task-types.json.example"]


def load_task_types(path: Path | None = None) -> list[TaskType]:
    """Load and parse all task types. Raises DefinitionError on malformed data."""
    candidates = [path] if path else _candidate_paths()
    raw: dict | None = None
    for candidate in candidates:
        if candidate and candidate.exists():
            raw = json.loads(candidate.read_text(encoding="utf-8"))
            break
    if raw is None:
        raise DefinitionError(
            "no task-types config found (config/task-types.json or .example)"
        )
    if raw.get("schemaVersion") != SCHEMA_VERSION:
        raise DefinitionError(
            f"unexpected schemaVersion '{raw.get('schemaVersion')}', "
            f"expected '{SCHEMA_VERSION}'"
        )
    types = [TaskType.from_dict(d) for d in raw.get("types") or []]
    if not types:
        raise DefinitionError("task-types config defines no types")
    _ensure_unique_ids(types)
    return types


def _ensure_unique_ids(types: list[TaskType]) -> None:
    seen: set[str] = set()
    for t in types:
        if t.typeId in seen:
            raise DefinitionError(f"duplicate typeId '{t.typeId}'")
        seen.add(t.typeId)
        pnames: set[str] = set()
        for p in t.params:
            if p.name in pnames:
                raise DefinitionError(
                    f"type '{t.typeId}' has duplicate param name '{p.name}'"
                )
            pnames.add(p.name)


def get_task_type(type_id: str) -> TaskType:
    for t in load_task_types():
        if t.typeId == type_id:
            return t
    raise DefinitionError(f"task type '{type_id}' not found")


# ------------------------------------------------------------------ raw graph
def load_raw_workflow(workflow_id: str) -> dict | None:
    """Return the archived export graph, or None if not archived."""
    path = WORKFLOWS_DIR / f"{workflow_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# ----------------------------------------------------------------- validation
@dataclass
class ValidationReport:
    typeId: str
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)


def validate_type(task_type: TaskType) -> ValidationReport:
    """Validate one task type against its raw export. Always returns a report."""
    report = ValidationReport(typeId=task_type.typeId, ok=True)
    graph = load_raw_workflow(task_type.workflowId)
    if graph is None:
        report.add_warning(
            f"raw export not archived (workflows/{task_type.workflowId}.json); "
            "node existence not verified"
        )
        # Placeholder workflow ids (templates) cannot be validated.
        if task_type.workflowId.startswith("<"):
            report.add_warning("template with placeholder workflowId")
        return _finalize(report)

    for p in task_type.params:
        node = graph.get(p.nodeId)
        if node is None:
            report.add_error(f"param '{p.name}': nodeId '{p.nodeId}' not in export")
            continue
        inputs = node.get("inputs") or {}
        if p.fieldName not in inputs:
            report.add_error(
                f"param '{p.name}': fieldName '{p.fieldName}' missing on node "
                f"'{p.nodeId}' (available: {sorted(inputs)})"
            )
        class_type = node.get("class_type", "")
        if p.type == "image" and class_type not in _IMAGE_CLASSES:
            report.add_warning(
                f"param '{p.name}' is image but node '{p.nodeId}' class_type is "
                f"'{class_type}' (expected one of {sorted(_IMAGE_CLASSES)})"
            )
        if p.type == "audio" and class_type not in _AUDIO_CLASSES:
            report.add_warning(
                f"param '{p.name}' is audio but node '{p.nodeId}' class_type is "
                f"'{class_type}' (expected one of {sorted(_AUDIO_CLASSES)})"
            )
        if p.type == "enum" and not p.enum:
            report.add_error(f"enum param '{p.name}' declares no 'enum' values")
        if not p.required and p.default is not None:
            _typecheck_default(report, p)
    return _finalize(report)


def _typecheck_default(report: ValidationReport, p: Param) -> None:
    value = p.default
    if p.type in ("int",) and not isinstance(value, int):
        report.add_error(f"param '{p.name}' default not int: {value!r}")
    if p.type == "float" and not isinstance(value, (int, float)):
        report.add_error(f"param '{p.name}' default not number: {value!r}")
    if p.type == "bool" and not isinstance(value, bool):
        report.add_error(f"param '{p.name}' default not bool: {value!r}")
    if p.type == "json" and not isinstance(value, (list, dict)):
        report.add_error(f"param '{p.name}' default not list/dict: {value!r}")


def _finalize(report: ValidationReport) -> ValidationReport:
    report.ok = not report.errors
    return report


def validate_all() -> list[ValidationReport]:
    return [validate_type(t) for t in load_task_types()]

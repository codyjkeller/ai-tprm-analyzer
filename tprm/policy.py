"""Loads and validates the policy file (policies/vendor_standards.yaml).

The policy is the single source of truth for what is checked and how it is
scored. A typo in it must stop the run with a clear message, never quietly
weaken an assessment, so unknown keys and missing frameworks are errors.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class PolicyError(Exception):
    """The policy file is missing, unreadable, or invalid."""


class Control(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    domain: str
    description: str
    weight: int = Field(ge=0, le=100)
    required: bool = True
    acceptable_answers: list[str] = []
    forbidden_terms: list[str] = []
    # Any non-empty value marks the control as critical. The text is shown in
    # the report as the reason.
    critical_flag: Optional[Union[str, bool]] = None

    # Filled in by load_policy, not written in the YAML.
    key: str = ""
    framework: str = ""

    @field_validator("id", mode="before")
    @classmethod
    def _id_as_text(cls, value):
        # YAML reads an unquoted 5.6 as a number.
        return str(value)

    @property
    def critical(self) -> bool:
        return bool(self.critical_flag)


class Threshold(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min: int = Field(ge=0)
    label: str


class Thresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    low_risk: Threshold
    medium_risk: Threshold
    high_risk: Threshold


class ScoringMatrix(BaseModel):
    model_config = ConfigDict(extra="forbid")

    starting_score: int = Field(default=100, gt=0)
    thresholds: Thresholds
    critical_override: bool = True


class Policy(BaseModel):
    scoring: ScoringMatrix
    active_frameworks: list[str]
    controls: list[Control]
    path: str
    sha256: str

    @property
    def scored_controls(self) -> list[Control]:
        return [c for c in self.controls if c.required]

    def control(self, key: str) -> Optional[Control]:
        return next((c for c in self.controls if c.key == key), None)


def _explain(error: ValidationError, where: str) -> str:
    problems = []
    for item in error.errors():
        location = ".".join(str(part) for part in item["loc"])
        problems.append(f"  - {where}{'.' + location if location else ''}: {item['msg']}")
    return "\n".join(problems)


def load_policy(path: Union[str, Path]) -> Policy:
    """Reads the policy file and returns the controls of the active frameworks."""
    path = Path(path)
    if not path.is_file():
        raise PolicyError(f"Policy file not found: {path}")

    raw_bytes = path.read_bytes()
    try:
        document = yaml.safe_load(raw_bytes)
    except yaml.YAMLError as error:
        raise PolicyError(f"{path} is not valid YAML: {error}") from error
    if not isinstance(document, dict):
        raise PolicyError(f"{path} must contain a YAML mapping at the top level.")

    unknown = set(document) - {"scoring_matrix", "active_frameworks", "frameworks"}
    if unknown:
        raise PolicyError(f"{path} has unknown top-level keys: {', '.join(sorted(unknown))}")

    try:
        scoring = ScoringMatrix.model_validate(document.get("scoring_matrix") or {})
    except ValidationError as error:
        raise PolicyError(f"{path} has an invalid scoring_matrix:\n{_explain(error, 'scoring_matrix')}") from error
    if not (scoring.thresholds.low_risk.min > scoring.thresholds.medium_risk.min >= scoring.thresholds.high_risk.min):
        raise PolicyError(f"{path}: thresholds must descend: low_risk.min > medium_risk.min >= high_risk.min.")

    active = document.get("active_frameworks") or []
    frameworks = document.get("frameworks") or {}
    if not isinstance(active, list) or not active:
        raise PolicyError(f"{path}: active_frameworks must list at least one framework.")
    if not isinstance(frameworks, dict):
        raise PolicyError(f"{path}: frameworks must be a mapping.")

    controls: list[Control] = []
    for name in active:
        if name not in frameworks:
            available = ", ".join(sorted(frameworks)) or "none"
            raise PolicyError(
                f"{path}: active framework '{name}' is not defined under frameworks. Available: {available}."
            )
        definitions = frameworks[name] or {}
        if not isinstance(definitions, dict):
            raise PolicyError(f"{path}: framework '{name}' must be a mapping of controls.")
        for control_name, fields in definitions.items():
            where = f"frameworks.{name}.{control_name}"
            if not isinstance(fields, dict):
                raise PolicyError(f"{path}: {where} must be a mapping.")
            try:
                control = Control.model_validate(fields)
            except ValidationError as error:
                raise PolicyError(f"{path} has an invalid control:\n{_explain(error, where)}") from error
            # Namespaced so two frameworks can use the same control name.
            control.key = f"{name}.{control_name}"
            control.framework = name
            controls.append(control)

    if sum(c.weight for c in controls if c.required) <= 0:
        raise PolicyError(f"{path}: the active frameworks have no required control with a weight above 0.")

    return Policy(
        scoring=scoring,
        active_frameworks=list(active),
        controls=controls,
        path=str(path),
        sha256=hashlib.sha256(raw_bytes).hexdigest(),
    )

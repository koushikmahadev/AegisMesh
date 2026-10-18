"""Configuration module for HighWater Module 3 (Risk & Prioritization Engine).

Centralizes scoring weights, normalization ceilings, isolation penalties,
priority thresholds, and data-quality configurations into validated,
reproducible, and auditable configuration objects.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.resources as pkg_resources
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants & Defaults
# ---------------------------------------------------------------------------

DEFAULT_CONFIG_VERSION = "1.0"

REQUIRED_BASE_WEIGHT_KEYS = {
    "flood_percent",
    "exposure",
    "isolation",
    "flood_area_density",
}
ALLOWED_WEIGHT_KEYS = REQUIRED_BASE_WEIGHT_KEYS | {"exposure_fraction"}

ACCESSIBILITY_VALUES = {"ACCESSIBLE", "PARTIAL", "BLOCKED", "UNKNOWN"}

DEFAULT_WEIGHTS = {
    "flood_percent": 0.35,
    "exposure": 0.40,
    "isolation": 0.15,
    "flood_area_density": 0.10,
    "exposure_fraction": 0.0,
}

DEFAULT_NORMALIZATION = {
    "flood_percent_max": 30.0,
    "exposed_buildings_max": 75.0,
    "flood_area_m2_max": 15000.0,
}

DEFAULT_ISOLATION_SCORES = {
    "ACCESSIBLE": 0.0,
    "PARTIAL": 0.5,
    "BLOCKED": 1.0,
    "UNKNOWN": 0.5,
}

DEFAULT_PRIORITY_THRESHOLDS = {
    "CRITICAL": 70.0,
    "HIGH": 45.0,
    "MEDIUM": 20.0,
    "LOW": 0.0,
}


class ConfigError(ValueError, FileNotFoundError):
    """Raised when engine configuration fails validation or cannot be loaded."""
    pass


def _strip_comments(d: dict[str, Any]) -> dict[str, Any]:
    """Return dictionary with all keys starting with '_' removed."""
    return {k: v for k, v in d.items() if not k.startswith("_")}


def weights_fingerprint(weights: dict[str, float]) -> str:
    """Generate a deterministic 16-character hexadecimal fingerprint for scoring weights."""
    clean = _strip_comments(weights)
    canonical = {
        "flood_percent": round(float(clean.get("flood_percent", 0.0)), 6),
        "exposure": round(float(clean.get("exposure", 0.0)), 6),
        "isolation": round(float(clean.get("isolation", 0.0)), 6),
        "flood_area_density": round(float(clean.get("flood_area_density", 0.0)), 6),
        "exposure_fraction": round(float(clean.get("exposure_fraction", 0.0)), 6),
    }
    for k, v in clean.items():
        if k not in canonical:
            canonical[k] = round(float(v), 6)
    payload = json.dumps(canonical, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Validated Configuration Data Classes
# ---------------------------------------------------------------------------

@dataclass
class ScoringWeights:
    """Configurable scoring component weights for the risk engine.

    The sum of active weights must equal 1.0 (within relative tolerance 1e-6).
    All weights must be non-negative finite numbers.
    """
    flood_percent: float = 0.35
    exposure: float = 0.40
    isolation: float = 0.15
    flood_area_density: float = 0.10
    exposure_fraction: float = 0.0

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        """Validate weight types, finite bounds, non-negativity, and sum to 1.0."""
        fields = {
            "flood_percent": self.flood_percent,
            "exposure": self.exposure,
            "isolation": self.isolation,
            "flood_area_density": self.flood_area_density,
            "exposure_fraction": self.exposure_fraction,
        }
        for k, v in fields.items():
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise ConfigError(f"scoring.weights['{k}'] must be a finite number; got {v!r}")
            if v < 0.0:
                raise ConfigError(f"scoring.weights['{k}'] must be non-negative; got {v}")

        total_w = sum(fields.values())
        if not math.isclose(total_w, 1.0, rel_tol=1e-6):
            raise ConfigError(f"scoring.weights must sum to 1.0; got {total_w:.6f}")

    def to_dict(self) -> dict[str, float]:
        """Convert weights to clean dictionary."""
        return {
            "flood_percent": float(self.flood_percent),
            "exposure": float(self.exposure),
            "isolation": float(self.isolation),
            "flood_area_density": float(self.flood_area_density),
            "exposure_fraction": float(self.exposure_fraction),
        }

    def fingerprint(self) -> str:
        """Compute 16-character deterministic fingerprint."""
        return weights_fingerprint(self.to_dict())

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ScoringWeights:
        """Construct and validate ScoringWeights from dictionary."""
        if not isinstance(d, dict):
            raise ConfigError("scoring.weights must be a dictionary")
        clean = _strip_comments(d)
        keys = set(clean.keys())

        missing = REQUIRED_BASE_WEIGHT_KEYS - keys
        if missing:
            raise ConfigError(f"scoring.weights missing required keys: {sorted(missing)}")

        extra = keys - ALLOWED_WEIGHT_KEYS
        if extra:
            raise ConfigError(f"scoring.weights contains unexpected extra keys: {sorted(extra)}")

        return cls(
            flood_percent=clean["flood_percent"],
            exposure=clean["exposure"],
            isolation=clean["isolation"],
            flood_area_density=clean["flood_area_density"],
            exposure_fraction=clean.get("exposure_fraction", 0.0),
        )

    @classmethod
    def from_unnormalized(cls, d: dict[str, Any]) -> ScoringWeights:
        """Construct normalized ScoringWeights from unnormalized positive values."""
        clean = _strip_comments(d)
        missing = REQUIRED_BASE_WEIGHT_KEYS - set(clean.keys())
        if missing:
            raise ConfigError(f"scoring.weights missing required keys: {sorted(missing)}")
        extra = set(clean.keys()) - ALLOWED_WEIGHT_KEYS
        if extra:
            raise ConfigError(f"scoring.weights contains unexpected extra keys: {sorted(extra)}")

        for k, v in clean.items():
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise ConfigError(f"scoring.weights['{k}'] must be a finite number; got {v!r}")
            if v < 0.0:
                raise ConfigError(f"scoring.weights['{k}'] must be non-negative; got {v}")

        total = sum(clean.values())
        if total <= 0.0:
            raise ConfigError("scoring.weights sum is 0; cannot normalize zero weights: at least one weight must be positive")

        normalized = {k: v / total for k, v in clean.items()}
        return cls.from_dict(normalized)


@dataclass
class NormalizationCeilings:
    """Ceilings used to normalize raw metrics to [0, 1]."""
    flood_percent_max: float = 30.0
    exposed_buildings_max: float = 75.0
    flood_area_m2_max: float = 15000.0

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        fields = {
            "flood_percent_max": self.flood_percent_max,
            "exposed_buildings_max": self.exposed_buildings_max,
            "flood_area_m2_max": self.flood_area_m2_max,
        }
        for k, v in fields.items():
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0:
                raise ConfigError(f"scoring.normalization['{k}'] must be a positive finite number; got {v!r}")

    def to_dict(self) -> dict[str, float]:
        return {
            "flood_percent_max": float(self.flood_percent_max),
            "exposed_buildings_max": float(self.exposed_buildings_max),
            "flood_area_m2_max": float(self.flood_area_m2_max),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> NormalizationCeilings:
        if not isinstance(d, dict):
            raise ConfigError("scoring.normalization must be a dictionary")
        clean = _strip_comments(d)
        required = {"flood_percent_max", "exposed_buildings_max", "flood_area_m2_max"}
        for k in required:
            if k not in clean:
                raise ConfigError(f"scoring.normalization missing required ceiling '{k}'")
        return cls(
            flood_percent_max=clean["flood_percent_max"],
            exposed_buildings_max=clean["exposed_buildings_max"],
            flood_area_m2_max=clean["flood_area_m2_max"],
        )


@dataclass
class IsolationScores:
    """Additive isolation penalty per accessibility category."""
    ACCESSIBLE: float = 0.0
    PARTIAL: float = 0.5
    BLOCKED: float = 1.0
    UNKNOWN: float = 0.5

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        scores = {
            "ACCESSIBLE": self.ACCESSIBLE,
            "PARTIAL": self.PARTIAL,
            "BLOCKED": self.BLOCKED,
            "UNKNOWN": self.UNKNOWN,
        }
        for cat, v in scores.items():
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not (0.0 <= v <= 1.0):
                raise ConfigError(f"scoring.isolation_score['{cat}'] must be a number in [0.0, 1.0]; got {v!r}")

        if not (self.ACCESSIBLE <= self.PARTIAL <= self.BLOCKED):
            raise ConfigError(
                f"Isolation ordering constraint violated: expected ACCESSIBLE ({self.ACCESSIBLE}) <= "
                f"PARTIAL ({self.PARTIAL}) <= BLOCKED ({self.BLOCKED})"
            )
        if not (self.UNKNOWN >= self.PARTIAL):
            raise ConfigError(
                f"Isolation ordering constraint violated: expected UNKNOWN ({self.UNKNOWN}) >= "
                f"PARTIAL ({self.PARTIAL})"
            )

    def to_dict(self) -> dict[str, float]:
        return {
            "ACCESSIBLE": float(self.ACCESSIBLE),
            "PARTIAL": float(self.PARTIAL),
            "BLOCKED": float(self.BLOCKED),
            "UNKNOWN": float(self.UNKNOWN),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> IsolationScores:
        if not isinstance(d, dict):
            raise ConfigError("scoring.isolation_score must be a dictionary")
        clean = _strip_comments(d)
        for cat in ACCESSIBILITY_VALUES:
            if cat not in clean:
                raise ConfigError(f"scoring.isolation_score missing required entry for '{cat}'")
        return cls(
            ACCESSIBLE=clean["ACCESSIBLE"],
            PARTIAL=clean["PARTIAL"],
            BLOCKED=clean["BLOCKED"],
            UNKNOWN=clean["UNKNOWN"],
        )


@dataclass
class PriorityThresholds:
    """Priority threshold score boundaries (inclusive lower bound)."""
    CRITICAL: float = 70.0
    HIGH: float = 45.0
    MEDIUM: float = 20.0
    LOW: float = 0.0

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        levels = {
            "CRITICAL": self.CRITICAL,
            "HIGH": self.HIGH,
            "MEDIUM": self.MEDIUM,
            "LOW": self.LOW,
        }
        for level, v in levels.items():
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise ConfigError(f"priority_thresholds['{level}'] must be a finite number; got {v!r}")

        if not (self.CRITICAL > self.HIGH > self.MEDIUM > self.LOW >= 0):
            raise ConfigError(
                f"Priority thresholds ordering violated: expected CRITICAL ({self.CRITICAL}) > "
                f"HIGH ({self.HIGH}) > MEDIUM ({self.MEDIUM}) > LOW ({self.LOW}) >= 0"
            )

    def to_dict(self) -> dict[str, float]:
        return {
            "CRITICAL": float(self.CRITICAL),
            "HIGH": float(self.HIGH),
            "MEDIUM": float(self.MEDIUM),
            "LOW": float(self.LOW),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PriorityThresholds:
        if not isinstance(d, dict):
            raise ConfigError("priority_thresholds must be a dictionary")
        clean = _strip_comments(d)
        for level in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
            if level not in clean:
                raise ConfigError(f"priority_thresholds missing '{level}'")
        return cls(
            CRITICAL=clean["CRITICAL"],
            HIGH=clean["HIGH"],
            MEDIUM=clean["MEDIUM"],
            LOW=clean["LOW"],
        )


@dataclass
class DataQualityConfig:
    on_negative_exposure: str = "error"
    warn_on_unknown_accessibility: bool = True
    warn_on_null_flooded_area_m2: bool = True
    warn_on_zero_exposure_with_high_flood_percent_threshold: float = 5.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "on_negative_exposure": self.on_negative_exposure,
            "warn_on_unknown_accessibility": self.warn_on_unknown_accessibility,
            "warn_on_null_flooded_area_m2": self.warn_on_null_flooded_area_m2,
            "warn_on_zero_exposure_with_high_flood_percent_threshold": self.warn_on_zero_exposure_with_high_flood_percent_threshold,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DataQualityConfig:
        if not isinstance(d, dict):
            return cls()
        clean = _strip_comments(d)
        return cls(
            on_negative_exposure=clean.get("on_negative_exposure", "error"),
            warn_on_unknown_accessibility=clean.get("warn_on_unknown_accessibility", True),
            warn_on_null_flooded_area_m2=clean.get("warn_on_null_flooded_area_m2", True),
            warn_on_zero_exposure_with_high_flood_percent_threshold=clean.get(
                "warn_on_zero_exposure_with_high_flood_percent_threshold", 5.0
            ),
        )


@dataclass
class ScoringConfig:
    weights: ScoringWeights = field(default_factory=ScoringWeights)
    normalization: NormalizationCeilings = field(default_factory=NormalizationCeilings)
    isolation_score: IsolationScores = field(default_factory=IsolationScores)

    def validate(self) -> None:
        self.weights.validate()
        self.normalization.validate()
        self.isolation_score.validate()

    def to_dict(self) -> dict[str, Any]:
        return {
            "weights": self.weights.to_dict(),
            "normalization": self.normalization.to_dict(),
            "isolation_score": self.isolation_score.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ScoringConfig:
        if not isinstance(d, dict):
            raise ConfigError("scoring must be a dictionary")
        if "weights" not in d or not isinstance(d["weights"], dict):
            raise ConfigError("Configuration missing 'scoring.weights' section")
        if "normalization" not in d or not isinstance(d["normalization"], dict):
            raise ConfigError("Configuration missing 'scoring.normalization' section")
        if "isolation_score" not in d or not isinstance(d["isolation_score"], dict):
            raise ConfigError("Configuration missing 'scoring.isolation_score' section")

        return cls(
            weights=ScoringWeights.from_dict(d["weights"]),
            normalization=NormalizationCeilings.from_dict(d["normalization"]),
            isolation_score=IsolationScores.from_dict(d["isolation_score"]),
        )


@dataclass
class RiskEngineConfig:
    config_version: str = DEFAULT_CONFIG_VERSION
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    priority_thresholds: PriorityThresholds = field(default_factory=PriorityThresholds)
    data_quality: DataQualityConfig = field(default_factory=DataQualityConfig)
    disclaimer_context: str | None = None

    def validate(self) -> None:
        self.scoring.validate()
        self.priority_thresholds.validate()

    def to_dict(self) -> dict[str, Any]:
        res: dict[str, Any] = {
            "config_version": self.config_version,
            "scoring": self.scoring.to_dict(),
            "priority_thresholds": self.priority_thresholds.to_dict(),
            "data_quality": self.data_quality.to_dict(),
        }
        if self.disclaimer_context is not None:
            res["disclaimer_context"] = self.disclaimer_context
        return res

    def fingerprint(self) -> str:
        """SHA-256 hash of entire effective configuration."""
        clean = {
            "config_version": self.config_version,
            "scoring": self.scoring.to_dict(),
            "priority_thresholds": self.priority_thresholds.to_dict(),
        }
        return hashlib.sha256(json.dumps(clean, sort_keys=True).encode("utf-8")).hexdigest()

    def weights_fingerprint(self) -> str:
        """Deterministic 16-hex fingerprint of the scoring weights alone."""
        return self.scoring.weights.fingerprint()

    def with_weights(self, weights_dict: dict[str, float] | None = None, **kwargs: float) -> RiskEngineConfig:
        """Return a new RiskEngineConfig with updated weights."""
        current = self.scoring.weights.to_dict()
        if weights_dict is not None:
            current.update(weights_dict)
        current.update(kwargs)
        new_weights = ScoringWeights.from_dict(current)
        new_scoring = ScoringConfig(
            weights=new_weights,
            normalization=copy.deepcopy(self.scoring.normalization),
            isolation_score=copy.deepcopy(self.scoring.isolation_score),
        )
        return RiskEngineConfig(
            config_version=self.config_version,
            scoring=new_scoring,
            priority_thresholds=copy.deepcopy(self.priority_thresholds),
            data_quality=copy.deepcopy(self.data_quality),
            disclaimer_context=self.disclaimer_context,
        )

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RiskEngineConfig:
        if not isinstance(d, dict):
            raise ConfigError("Configuration must be a JSON object")
        if "scoring" not in d or not isinstance(d["scoring"], dict):
            raise ConfigError("Configuration missing 'scoring' section")
        # Validate scoring (including weights) before priority thresholds
        scoring_obj = ScoringConfig.from_dict(d["scoring"])
        if "priority_thresholds" not in d or not isinstance(d["priority_thresholds"], dict):
            raise ConfigError("Configuration missing 'priority_thresholds' section")

        return cls(
            config_version=d.get("config_version", DEFAULT_CONFIG_VERSION),
            scoring=scoring_obj,
            priority_thresholds=PriorityThresholds.from_dict(d["priority_thresholds"]),
            data_quality=DataQualityConfig.from_dict(d.get("data_quality", {})),
            disclaimer_context=d.get("disclaimer_context"),
        )


# ---------------------------------------------------------------------------
# Validation & Loading Functions
# ---------------------------------------------------------------------------

def validate_config(cfg: dict[str, Any] | RiskEngineConfig) -> dict[str, Any]:
    """Validate full configuration structure and value constraints.

    Accepts either a dict or RiskEngineConfig, validates all sections,
    and returns a clean validated configuration dictionary.
    """
    if isinstance(cfg, RiskEngineConfig):
        cfg.validate()
        return cfg.to_dict()

    if not isinstance(cfg, dict):
        raise ConfigError("Configuration must be a JSON object")

    parsed = RiskEngineConfig.from_dict(cfg)
    parsed.validate()

    # Mutate in-place if dictionary provided for backward compatibility
    if "scoring" in cfg and isinstance(cfg["scoring"], dict):
        cfg["scoring"]["weights"] = parsed.scoring.weights.to_dict()
        cfg["scoring"]["normalization"] = parsed.scoring.normalization.to_dict()
        cfg["scoring"]["isolation_score"] = parsed.scoring.isolation_score.to_dict()
    if "priority_thresholds" in cfg and isinstance(cfg["priority_thresholds"], dict):
        cfg["priority_thresholds"] = parsed.priority_thresholds.to_dict()

    return cfg


def load_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load and validate scoring config from path or package defaults.

    First checks explicit config_path, then importlib.resources, then repository-relative fallbacks.
    Returns a validated configuration dictionary.
    """
    if config_path is not None:
        path = Path(config_path)
        if not path.is_file():
            raise ConfigError(f"Configuration file not found: {path}")
        with open(path, encoding="utf-8") as fh:
            try:
                raw_cfg = json.load(fh)
            except json.JSONDecodeError as exc:
                raise ConfigError(f"Configuration file {path} contains invalid JSON: {exc}") from exc
        return validate_config(raw_cfg)

    # Try importlib.resources
    raw_cfg = None
    try:
        ref = pkg_resources.files("risk_engine") / "weights.json"
        if ref.is_file():
            raw_cfg = json.loads(ref.read_text(encoding="utf-8"))
    except Exception:
        raw_cfg = None

    if raw_cfg is None:
        candidates = [
            Path(__file__).resolve().parent.parent.parent / "config" / "weights.json",
            Path(__file__).resolve().parent / "weights.json",
            Path("config/weights.json"),
            Path("modules/risk_engine/config/weights.json"),
        ]
        for c in candidates:
            if c.is_file():
                with open(c, encoding="utf-8") as fh:
                    raw_cfg = json.load(fh)
                break

    if raw_cfg is None:
        raise ConfigError("Default weights.json configuration could not be located")

    return validate_config(raw_cfg)


def load_config_object(config_path: Path | None = None) -> RiskEngineConfig:
    """Load scoring config as a validated RiskEngineConfig object."""
    cfg_dict = load_config(config_path)
    return RiskEngineConfig.from_dict(cfg_dict)


def parse_weights_arg(val: str | dict[str, Any]) -> dict[str, float]:
    """Parse weights from a dict, inline JSON string, or comma-separated key=value string.

    Examples:
        parse_weights_arg({"flood_percent": 0.5, "exposure": 0.5})
        parse_weights_arg('{"flood_percent": 0.35, "exposure": 0.40, ...}')
        parse_weights_arg("flood_percent=0.35,exposure=0.40,isolation=0.15,flood_area_density=0.10")
    """
    if isinstance(val, dict):
        return {k: float(v) for k, v in val.items()}
    if not isinstance(val, str):
        raise ConfigError(f"--weights must be a dict or string; got {type(val).__name__}")
    val = val.strip()
    if val.startswith("{"):
        try:
            parsed = json.loads(val)
            if not isinstance(parsed, dict):
                raise ValueError("Weights JSON must be an object")
            return {k: float(v) for k, v in parsed.items()}
        except (json.JSONDecodeError, ValueError) as exc:
            raise ConfigError(f"Failed to parse --weights JSON: {exc}") from exc

    result: dict[str, float] = {}
    items = [x for x in re.split(r"[,;\s]+", val) if x]
    for item in items:
        if "=" not in item:
            raise ConfigError(f"Invalid weight format: '{item}'. Expected 'key=value'")
        k, v_str = item.split("=", 1)
        k = k.strip()
        try:
            v = float(v_str.strip())
        except ValueError:
            raise ConfigError(f"Invalid weight value for '{k}': '{v_str}'. Must be a number")
        result[k] = v
    return result

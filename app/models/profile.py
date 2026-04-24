from dataclasses import dataclass, field
from typing import Any

@dataclass
class PageFingerprint:
    url_pattern: str
    scrollable_container_count: int
    container_geometry_ratios: list[float]
    landmark_words: list[str]
    field_label_signature: list[str]
    section_header_tokens: list[str]
    layout_region_count: int

    def as_dict(self) -> dict:
        return {
            "url_pattern": self.url_pattern,
            "scrollable_container_count": self.scrollable_container_count,
            "container_geometry_ratios": self.container_geometry_ratios,
            "landmark_words": self.landmark_words,
            "field_label_signature": self.field_label_signature,
            "section_header_tokens": self.section_header_tokens,
            "layout_region_count": self.layout_region_count,
        }

@dataclass
class ProfileMatchResult:
    profile_matched: bool
    profile_name: str
    profile_match_confidence: float
    profile_match_reason: list[str]
    mode: str                       # "assisted" | "none"

    def as_dict(self) -> dict:
        return {
            "profile_matched": self.profile_matched,
            "profile_name": self.profile_name,
            "profile_match_confidence": self.profile_match_confidence,
            "profile_match_reason": self.profile_match_reason,
            "mode": self.mode,
        }

@dataclass
class SectionDefinition:
    section_type: str
    detection_hints: list[str]
    position_hint: str              # "top" | "middle" | "bottom" | "any"
    min_width_ratio: float
    min_height_px: int

    def as_dict(self) -> dict:
        return {
            "section_type": self.section_type,
            "detection_hints": self.detection_hints,
            "position_hint": self.position_hint,
            "min_width_ratio": self.min_width_ratio,
            "min_height_px": self.min_height_px,
        }

@dataclass
class CaptureProfile:
    name: str
    created_at: str
    fingerprint: PageFingerprint
    section_definitions: list[SectionDefinition]
    capture_params: dict
    expander_triggers: list[str]
    protected_patterns: list[str]
    proficiency_score: float = 0.0
    successful_sessions: int = 0
    total_sessions: int = 0
    is_proficient: bool = False
    notes: str = ""

    PROFICIENCY_SCORE_THRESHOLD: float = 0.85
    PROFICIENCY_SESSION_MINIMUM: int = 5

    def check_proficiency(self) -> bool:
        self.is_proficient = (
            self.proficiency_score >= self.PROFICIENCY_SCORE_THRESHOLD
            and self.successful_sessions >= self.PROFICIENCY_SESSION_MINIMUM
        )
        return self.is_proficient

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "created_at": self.created_at,
            "fingerprint": self.fingerprint.as_dict(),
            "section_definitions": [s.as_dict() for s in
                                     self.section_definitions],
            "capture_params": self.capture_params,
            "expander_triggers": self.expander_triggers,
            "protected_patterns": self.protected_patterns,
            "proficiency_score": self.proficiency_score,
            "successful_sessions": self.successful_sessions,
            "total_sessions": self.total_sessions,
            "is_proficient": self.is_proficient,
            "notes": self.notes,
        }

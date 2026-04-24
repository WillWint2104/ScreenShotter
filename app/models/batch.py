from dataclasses import dataclass, field

VALID_SECTION_GROUPS = frozenset({
    "instructions",
    "prompt",
    "conversation_history",
    "response_a",
    "response_b",
    "examples",
    "ui_fields",
    "buttons",
    "unknown",
})

@dataclass
class SectionGroup:
    group_name: str
    screenshots: list[str] = field(default_factory=list)
    confidence: float = 0.0
    contamination_flags: list[str] = field(default_factory=list)
    missing: bool = False

    def as_dict(self) -> dict:
        return {
            "group_name": self.group_name,
            "screenshots": self.screenshots,
            "confidence": self.confidence,
            "contamination_flags": self.contamination_flags,
            "missing": self.missing,
        }

@dataclass
class BatchResult:
    session_id: str
    created_at: str
    groups: dict[str, SectionGroup] = field(default_factory=dict)
    unresolved: list[str] = field(default_factory=list)
    contamination_detected: bool = False
    missing_sections: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "groups": {k: v.as_dict() for k, v in self.groups.items()},
            "unresolved": self.unresolved,
            "contamination_detected": self.contamination_detected,
            "missing_sections": self.missing_sections,
        }

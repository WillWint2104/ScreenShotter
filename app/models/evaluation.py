from dataclasses import dataclass, field

RecommendedAction = str
# Valid values: "accept" | "review" | "retry"

@dataclass
class SectionScore:
    found: bool
    confidence: float
    screenshot_count: int
    ocr_quality: float
    issues: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "found": self.found,
            "confidence": self.confidence,
            "screenshot_count": self.screenshot_count,
            "ocr_quality": self.ocr_quality,
            "issues": self.issues,
        }

@dataclass
class OcrQualitySummary:
    overall: float
    by_section: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "overall": self.overall,
            "by_section": self.by_section,
        }

@dataclass
class CaptureEvaluation:
    """
    Capture quality assessment only.
    This model must never contain task scores,
    response comparisons, or content-level judgements.
    See ARCHITECTURE.md: Capture Validator is not a Task Evaluator.
    """
    session_id: str
    evaluated_at: str
    capture_complete: bool
    section_scores: dict[str, SectionScore] = field(default_factory=dict)
    missing_sections: list[str] = field(default_factory=list)
    duplicate_sections: list[str] = field(default_factory=list)
    ocr_quality: OcrQualitySummary = field(
        default_factory=lambda: OcrQualitySummary(overall=0.0)
    )
    overall_capture_confidence: float = 0.0
    recommended_action: RecommendedAction = "review"

    def as_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "evaluated_at": self.evaluated_at,
            "capture_complete": self.capture_complete,
            "section_scores": {k: v.as_dict()
                                for k, v in self.section_scores.items()},
            "missing_sections": self.missing_sections,
            "duplicate_sections": self.duplicate_sections,
            "ocr_quality": self.ocr_quality.as_dict(),
            "overall_capture_confidence": self.overall_capture_confidence,
            "recommended_action": self.recommended_action,
        }

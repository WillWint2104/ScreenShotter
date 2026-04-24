from dataclasses import dataclass, field

RecommendationType = str
# Valid values: "capture_param" | "classification_rule" |
#               "expander_trigger" | "profile_edit" |
#               "uia_search_depth"

ApprovalStatus = str
# Valid values: "pending" | "approved" | "rejected"

@dataclass
class ImprovementRecommendation:
    recommendation_id: str
    type: RecommendationType
    issue: str
    pattern_evidence: list[str]
    suggestion: str
    current_value: str
    recommended_value: str
    affected_sessions: list[str]
    approval_status: ApprovalStatus = "pending"
    approved_by: str = ""
    applied_at: str = ""
    notes: str = ""

    def as_dict(self) -> dict:
        return {
            "recommendation_id": self.recommendation_id,
            "type": self.type,
            "issue": self.issue,
            "pattern_evidence": self.pattern_evidence,
            "suggestion": self.suggestion,
            "current_value": self.current_value,
            "recommended_value": self.recommended_value,
            "affected_sessions": self.affected_sessions,
            "approval_status": self.approval_status,
            "approved_by": self.approved_by,
            "applied_at": self.applied_at,
            "notes": self.notes,
        }

@dataclass
class ImprovementReport:
    """
    Improvement Engine output.
    Contains recommendations only.
    No automatic changes. Human approval required for all entries.
    See ARCHITECTURE.md: Improvement Engine Constraints.
    """
    report_id: str
    generated_at: str
    sessions_analysed: int
    recommendations: list[ImprovementRecommendation] = field(
        default_factory=list
    )
    patterns_detected: list[str] = field(default_factory=list)
    summary: str = ""

    def as_dict(self) -> dict:
        return {
            "report_id": self.report_id,
            "generated_at": self.generated_at,
            "sessions_analysed": self.sessions_analysed,
            "recommendations": [r.as_dict() for r in
                                  self.recommendations],
            "patterns_detected": self.patterns_detected,
            "summary": self.summary,
        }

from __future__ import annotations

from pydantic import BaseModel, Field


class WorkExperienceExtract(BaseModel):
    seq: int = 0
    company_name: str = ""
    date_start: str = ""
    date_end: str = ""
    duration: str = ""
    industry: str = ""
    company_size: str = ""
    job_category: str = ""
    management_responsibility: str = ""
    job_title: str = ""
    job_description: str = ""
    job_skills: str = ""


class EducationExtract(BaseModel):
    seq: int = 0
    school: str = ""
    department: str = ""
    degree_level: str = ""
    date_start: str = ""
    date_end: str = ""
    region: str = ""
    status: str = ""


class ReferenceExtract(BaseModel):
    ref_name: str = ""
    ref_email: str = ""
    ref_org: str = ""
    ref_title: str = ""


class AttachmentExtract(BaseModel):
    attachment_type: str = ""
    seq: int = 0
    name: str = ""
    description: str = ""
    url: str = ""


class ResumeExtract(BaseModel):
    name: str = ""
    english_name: str = ""
    code_104: str = ""
    birth_year: str = ""
    age: str = ""
    nationality: str = ""
    current_status: str = ""
    earliest_start: str = ""
    education_level: str = ""
    school: str = ""
    major: str = ""
    military_status: str = ""
    desired_salary: str = ""
    desired_job_categories: list[str] = Field(default_factory=list)
    desired_locations: list[str] = Field(default_factory=list)
    desired_industry: str = ""
    ideal_positions: list[str] = Field(default_factory=list)
    years_of_experience: str = ""
    linkedin_url: str = ""
    photo_path: str = ""
    email: str = ""
    mobile1: str = ""
    mobile2: str = ""
    phone_home: str = ""
    phone_work: str = ""
    district: str = ""
    mailing_address: str = ""
    work_type: str = ""
    shift_preference: str = ""
    remote_work_preference: str = ""
    skills_text: str = ""
    skill_tags: list[str] = Field(default_factory=list)
    self_introduction: str = ""
    personal_motto: str = ""
    personal_traits: str = ""
    autobiography: str = ""

    work_experiences: list[WorkExperienceExtract] = Field(default_factory=list)
    education: list[EducationExtract] = Field(default_factory=list)
    references: list[ReferenceExtract] = Field(default_factory=list)
    attachments: list[AttachmentExtract] = Field(default_factory=list)


class MatchResultExtract(BaseModel):
    overall_score: float = 0.0
    education_score: float = 0.0
    experience_score: float = 0.0
    skills_score: float = 0.0
    analysis_text: str = ""
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)


# --- Enhanced Scoring Models (SPEC: Smart LLM Engineer Screening Funnel) ---


class EducationLevelDetail(BaseModel):
    school: str = ""
    school_tier: str = ""          # "A" / "B" / "C"
    school_points: float = 0.0     # A=10, B=3, C=0
    major: str = ""
    major_relevance: str = ""      # "Tier1" / "Tier2" / "Other"
    major_points: float = 0.0      # Tier1=10, Tier2=3, Other=0
    base_score: float = 0.0        # school_points + major_points (max 20)


class EducationScoreDetail(BaseModel):
    bachelor: EducationLevelDetail | None = None
    master: EducationLevelDetail | None = None
    thesis_bonus: float = 0.0
    score: float = 0.0             # hybrid weighted score (0-100)


class ExperienceTierDetail(BaseModel):
    tier: int = 0                  # 0-3 (Non-AI → AI Expert)
    tier_label: str = ""           # "Non-AI" / "Wrapper" / "RAG Architect" / "AI Expert"
    confidence: float = 1.0        # LLM self-reported confidence (0-1)
    tier_source: str = "keyword"   # "llm" | "keyword" | "llm+keyword-floor"
    evidence: list[str] = Field(default_factory=list)
    tech_stack_score: float = 0.0  # S_stack
    complexity_score: float = 0.0  # S_complexity
    metric_score: float = 0.0     # S_metric
    score: float = 0.0


class EngineeringMaturityDetail(BaseModel):
    backend_level: int = 0         # 0-3
    backend_score: float = 0.0
    database_level: int = 0        # 0-3
    database_score: float = 0.0
    frontend_level: int = 0        # 0-3
    frontend_score: float = 0.0
    m_eng: float = 0.0             # Total engineering multiplier


class SkillVerification(BaseModel):
    skill_ecosystem: str = ""      # "Traditional ML" / "Deep Learning" / "LLM Stack"
    suspicious_flags: list[str] = Field(default_factory=list)
    score: float = 0.0


class EnhancedMatchResult(BaseModel):
    # Final scores
    overall_score: float = 0.0
    s_ai: float = 0.0             # AI pyramid score (0-100)
    m_eng: float = 0.0            # Engineering coefficient (0-0.7)
    s_total: float = 0.0          # Legacy: S_AI * (1 + M_Eng)

    # Legacy scores for backward compat
    education_score: float = 0.0
    experience_score: float = 0.0
    skills_score: float = 0.0

    # Dimension breakdowns
    education_detail: EducationScoreDetail = Field(default_factory=EducationScoreDetail)
    experience_detail: ExperienceTierDetail = Field(default_factory=ExperienceTierDetail)
    engineering_detail: EngineeringMaturityDetail = Field(default_factory=EngineeringMaturityDetail)
    skill_detail: SkillVerification = Field(default_factory=SkillVerification)

    # Capability-matrix breakdown when a domain profile is in use. The legacy
    # engineering_detail keeps the first three axes so old consumers still work,
    # but a non-engineering profile's axes are only truthful here.
    competency_axes: list[dict] = Field(default_factory=list)

    # Which scoring standard produced this result. Empty means the built-in
    # AI-engineer path.
    profile_id: str = ""
    profile_name: str = ""

    # Funnel results
    passed_hard_filter: bool = True
    hard_filter_failures: list[str] = Field(default_factory=list)
    semantic_similarity: float = 0.0

    # Scorecard output
    tags: list[str] = Field(default_factory=list)
    analysis_text: str = ""
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    interview_suggestions: list[str] = Field(default_factory=list)

    # --- Provenance ---
    # Which path actually produced this score.  Without it a result written
    # while LM Studio was down is indistinguishable from a good one, so nobody
    # can tell afterwards which rows deserve a re-run.
    scoring_mode: str = "full"                 # "full" | "degraded"
    degraded_reasons: list[str] = Field(default_factory=list)
    scoring_config_version: str = ""           # app.scoring.config.config_version()
    tier_prompt_md5: str = ""                  # app.llm.TIER_CLASSIFY_PROMPT_MD5

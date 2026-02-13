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

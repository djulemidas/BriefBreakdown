from typing import Literal
from pydantic import BaseModel, Field

Role = Literal["designer", "developer", "pm", "qa", "strategist"]
Phase = Literal["discovery", "design", "build", "qa", "launch", "training"]
Severity = Literal["low", "medium", "high"]


class Task(BaseModel):
    id: str = Field(description="Short stable id like 't1', 't2'.")
    title: str
    description: str
    role: Role
    phase: Phase
    estimate_hours: int = Field(ge=1, le=400)
    depends_on: list[str] = Field(default_factory=list, description="Task ids this depends on.")


class Milestone(BaseModel):
    name: str
    phase: Phase


class Risk(BaseModel):
    risk: str
    severity: Severity
    mitigation: str


class ProjectPlan(BaseModel):
    project_summary: str
    estimated_total_hours: int = Field(ge=1)
    phases: list[Phase]
    tasks: list[Task]
    milestones: list[Milestone]
    risks: list[Risk]

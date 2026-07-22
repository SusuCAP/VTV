from decimal import Decimal

import pytest
from pydantic import ValidationError
from vtv_schemas.projects import Budget, ProjectCreate


def test_project_defaults_match_research_profile() -> None:
    project = ProjectCreate(name="Drama-US-001", target_market="US", locale="en-US")

    assert project.output.width == 1080
    assert project.output.height == 1920
    assert project.quality_profile == "research_best"
    assert project.budget.hard_limit == Decimal("350.00")


def test_budget_warning_cannot_exceed_hard_limit() -> None:
    with pytest.raises(ValidationError):
        Budget(warning_at=Decimal("400"), hard_limit=Decimal("350"))

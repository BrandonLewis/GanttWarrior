"""Tests for calendar import/export."""

import tempfile
from datetime import date
from pathlib import Path

import pytest

from ganttwarrior.calendar_io import export_ical, import_ical
from ganttwarrior.models import (
    Dependency,
    DependencyType,
    Project,
    Task,
    TaskColor,
    TaskStatus,
)


class TestCalendarIO:
    def _make_project(self) -> Project:
        project = Project(name="Cal Test", start_date=date(2026, 3, 1))
        t1 = project.add_task(Task(
            name="Design Phase", wbs="1", duration_days=5,
            color=TaskColor.GREEN, assigned_to="Alice",
        ))
        t2 = project.add_task(Task(
            name="Build Phase", wbs="2", duration_days=10,
            color=TaskColor.RED, assigned_to="Bob",
            dependencies=[Dependency(t1.id, DependencyType.FINISH_TO_START, lag_days=1)],
        ))
        return project

    def test_export_ical(self):
        project = self._make_project()
        with tempfile.NamedTemporaryFile(suffix=".ics", delete=False) as f:
            path = f.name

        try:
            result = export_ical(project, path)
            assert Path(result).exists()
            content = Path(result).read_text()
            assert "VCALENDAR" in content
            assert "Design Phase" in content
            assert "Build Phase" in content
        finally:
            Path(path).unlink(missing_ok=True)

    def test_roundtrip(self):
        project = self._make_project()
        with tempfile.NamedTemporaryFile(suffix=".ics", delete=False) as f:
            path = f.name

        try:
            export_ical(project, path)
            imported = import_ical(path)

            assert len(imported.tasks) == 2
            names = {t.name for t in imported.tasks}
            assert "Design Phase" in names
            assert "Build Phase" in names
        finally:
            Path(path).unlink(missing_ok=True)

    def test_import_preserves_metadata(self):
        project = self._make_project()
        with tempfile.NamedTemporaryFile(suffix=".ics", delete=False) as f:
            path = f.name

        try:
            export_ical(project, path)
            imported = import_ical(path)

            design = next(t for t in imported.tasks if t.name == "Design Phase")
            assert design.wbs == "1"
            assert design.color == TaskColor.GREEN
            assert design.assigned_to == "Alice"
        finally:
            Path(path).unlink(missing_ok=True)

# Gantt Grid Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the Gantt chart from a read-only visualization into an editable cell-grid with text-editor-like keyboard interaction — fill, erase, cut, copy, paste, split, merge, undo/redo, zoom, and work calendar support.

**Architecture:** The data model gains `work_days: set[date]` as the single source of truth for task scheduling (replacing `duration_days`). A new `WorkCalendar` helper resolves project-level and task-level working day rules. The `GanttChart` widget is rewritten to render a cell grid with cursor/selection state, and a new `GridEditor` class encapsulates all editing operations (clipboard, undo stack). The scheduler is updated to read `work_days` and respect the `manually_edited` flag.

**Tech Stack:** Python 3.10+, Textual 8.x, Rich, pytest

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `ganttwarrior/models.py` | Modify | Add `work_days`, `work_weekdays`, `manually_edited` to Task. Add `default_work_weekdays`, `holidays` to Project. Update serialization. Migration from old format. |
| `ganttwarrior/work_calendar.py` | Create | `WorkCalendar` class: expand duration into work days, check if a date is a working day, resolve project+task calendar rules. |
| `ganttwarrior/undo.py` | Create | `UndoStack` class: push/pop/redo snapshots of task `work_days`. Clears on save. |
| `ganttwarrior/grid_editor.py` | Create | `GridEditor` class: clipboard (copy/cut/paste), fill, erase, split, merge, duplicate operations. Owns the `UndoStack`. Pure logic, no TUI dependencies. |
| `ganttwarrior/views/gantt.py` | Rewrite | `GanttChart` gains cursor_col (date), selection_start/end, zoom level. `GanttTaskRow.render()` draws cells with cursor/selection highlights. New bindings for all keyboard shortcuts. |
| `ganttwarrior/app.py` | Modify | Wire new grid editor actions. Update info panel for cursor context. Clear undo on save. |
| `ganttwarrior/scheduler.py` | Modify | Use `work_days` for scheduling. Skip `work_days` regeneration for `manually_edited` tasks. |
| `ganttwarrior/export.py` | Modify | Use `task.work_days` properties instead of `task.duration_days` / `task.start_date` / `task.end_date` where needed. |
| `ganttwarrior/calendar_io.py` | Modify | Populate `work_days` on import. Export `work_days` metadata. |
| `tests/test_work_calendar.py` | Create | Tests for `WorkCalendar`. |
| `tests/test_undo.py` | Create | Tests for `UndoStack`. |
| `tests/test_grid_editor.py` | Create | Tests for `GridEditor` operations. |
| `tests/test_models.py` | Modify | Update for new fields, migration, serialization. |
| `tests/test_scheduler.py` | Modify | Update to use `work_days` in test fixtures. |

---

### Task 1: Add work_days and calendar fields to data models

**Files:**
- Modify: `ganttwarrior/models.py:69-170` (Task class)
- Modify: `ganttwarrior/models.py:173-303` (Project class)
- Modify: `tests/test_models.py`

- [ ] **Step 1: Write failing tests for new Task fields**

Add to `tests/test_models.py`:

```python
class TestTaskWorkDays:
    def test_work_days_default_empty(self):
        task = Task(name="Test")
        assert task.work_days == set()

    def test_work_days_duration_computed(self):
        task = Task(name="Test")
        task.work_days = {date(2026, 3, 25), date(2026, 3, 26), date(2026, 3, 28)}
        assert task.duration_days == 3

    def test_work_days_start_end_computed(self):
        task = Task(name="Test")
        task.work_days = {date(2026, 3, 25), date(2026, 3, 26), date(2026, 3, 28)}
        assert task.start_date == date(2026, 3, 25)
        assert task.end_date == date(2026, 3, 28)

    def test_work_days_empty_returns_none_dates(self):
        task = Task(name="Test")
        task.work_days = set()
        assert task.start_date is None
        assert task.end_date is None
        assert task.duration_days == 0

    def test_work_weekdays_default_none(self):
        task = Task(name="Test")
        assert task.work_weekdays is None

    def test_manually_edited_default_false(self):
        task = Task(name="Test")
        assert task.manually_edited is False

    def test_work_days_serialization(self):
        task = Task(name="Test", wbs="1")
        task.work_days = {date(2026, 3, 25), date(2026, 3, 26)}
        task.work_weekdays = {5, 6}
        task.manually_edited = True
        data = task.to_dict()
        assert data["work_days"] == ["2026-03-25", "2026-03-26"]
        assert data["work_weekdays"] == [5, 6]
        assert data["manually_edited"] is True

    def test_work_days_deserialization(self):
        data = {
            "id": "abc",
            "name": "Test",
            "wbs": "1",
            "work_days": ["2026-03-25", "2026-03-28"],
            "work_weekdays": [5, 6],
            "manually_edited": True,
        }
        task = Task.from_dict(data)
        assert task.work_days == {date(2026, 3, 25), date(2026, 3, 28)}
        assert task.work_weekdays == {5, 6}
        assert task.manually_edited is True

    def test_legacy_migration_no_work_days(self):
        """Old format without work_days should expand from start_date + duration_days."""
        data = {
            "id": "abc",
            "name": "Test",
            "wbs": "1",
            "start_date": "2026-03-25",
            "duration_days": 3,
        }
        task = Task.from_dict(data)
        # Should have 3 work days starting from Mar 25 (Wed)
        assert len(task.work_days) == 3
        assert date(2026, 3, 25) in task.work_days
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_models.py::TestTaskWorkDays -v`
Expected: FAIL — `Task` has no `work_days` attribute, no `work_weekdays`, etc.

- [ ] **Step 3: Add new fields to Task dataclass**

In `ganttwarrior/models.py`, add after line 85 (`parent_wbs`):

```python
    work_days: set[date] = field(default_factory=set)
    work_weekdays: Optional[set[int]] = None  # Override project weekdays; e.g. {5,6} for Sat-Sun
    manually_edited: bool = False
```

Convert `start_date`, `end_date`, and `duration_days` from stored fields to computed properties. Remove the old field declarations and replace with:

```python
    _start_date: Optional[date] = field(default=None, repr=False)
    _end_date: Optional[date] = field(default=None, repr=False)
    _duration_days: int = field(default=1, repr=False)
```

Add properties:

```python
    @property
    def start_date(self) -> Optional[date]:
        if self.work_days:
            return min(self.work_days)
        return self._start_date

    @start_date.setter
    def start_date(self, value: Optional[date]) -> None:
        self._start_date = value

    @property
    def end_date(self) -> Optional[date]:
        if self.work_days:
            return max(self.work_days)
        return self._end_date

    @end_date.setter
    def end_date(self, value: Optional[date]) -> None:
        self._end_date = value

    @property
    def duration_days(self) -> int:
        if self.work_days:
            return len(self.work_days)
        return self._duration_days

    @duration_days.setter
    def duration_days(self, value: int) -> None:
        self._duration_days = value
```

- [ ] **Step 4: Update Task.to_dict() serialization**

In `Task.to_dict()`, add after the existing fields:

```python
        "work_days": sorted(d.isoformat() for d in self.work_days),
        "work_weekdays": sorted(self.work_weekdays) if self.work_weekdays is not None else None,
        "manually_edited": self.manually_edited,
```

- [ ] **Step 5: Update Task.from_dict() deserialization with migration**

In `Task.from_dict()`, after constructing the task, add work_days handling:

```python
        # Load work_days if present, otherwise migrate from legacy format
        raw_work_days = data.get("work_days")
        if raw_work_days is not None:
            task.work_days = {date.fromisoformat(d) for d in raw_work_days}
        elif task.start_date and task.duration_days > 0:
            # Legacy migration: expand start_date + duration_days into work_days
            # Default to Mon-Fri working days
            days = set()
            current = task.start_date
            added = 0
            while added < task.duration_days:
                if current.weekday() < 5:  # Mon-Fri
                    days.add(current)
                    added += 1
                current += timedelta(days=1)
            task.work_days = days

        raw_weekdays = data.get("work_weekdays")
        task.work_weekdays = set(raw_weekdays) if raw_weekdays is not None else None
        task.manually_edited = data.get("manually_edited", False)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_models.py -v`
Expected: ALL PASS (both old and new tests)

- [ ] **Step 7: Write failing tests for Project calendar fields**

Add to `tests/test_models.py`:

```python
class TestProjectCalendar:
    def test_default_work_weekdays(self):
        project = Project(name="Test")
        assert project.default_work_weekdays == {0, 1, 2, 3, 4}

    def test_holidays_default_empty(self):
        project = Project(name="Test")
        assert project.holidays == set()

    def test_project_calendar_serialization(self):
        project = Project(name="Test", start_date=date(2026, 1, 1))
        project.holidays = {date(2026, 12, 25)}
        project.default_work_weekdays = {0, 1, 2, 3}  # Mon-Thu
        data = project.to_dict()
        assert data["default_work_weekdays"] == [0, 1, 2, 3]
        assert data["holidays"] == ["2026-12-25"]

    def test_project_calendar_deserialization(self):
        data = {
            "name": "Test",
            "start_date": "2026-01-01",
            "default_work_weekdays": [0, 1, 2, 3],
            "holidays": ["2026-12-25"],
        }
        project = Project.from_dict(data)
        assert project.default_work_weekdays == {0, 1, 2, 3}
        assert project.holidays == {date(2026, 12, 25)}

    def test_project_legacy_no_calendar_fields(self):
        data = {"name": "Old Project", "start_date": "2026-01-01"}
        project = Project.from_dict(data)
        assert project.default_work_weekdays == {0, 1, 2, 3, 4}
        assert project.holidays == set()
```

- [ ] **Step 8: Run tests to verify they fail**

Run: `pytest tests/test_models.py::TestProjectCalendar -v`
Expected: FAIL — `Project` has no `default_work_weekdays` attribute

- [ ] **Step 9: Add calendar fields to Project**

In `ganttwarrior/models.py`, add to `Project` dataclass after `file_path`:

```python
    default_work_weekdays: set[int] = field(default_factory=lambda: {0, 1, 2, 3, 4})
    holidays: set[date] = field(default_factory=set)
```

Update `Project.to_dict()`:

```python
        "default_work_weekdays": sorted(self.default_work_weekdays),
        "holidays": sorted(d.isoformat() for d in self.holidays),
```

Update `Project.from_dict()`:

```python
        project = cls(
            # ... existing fields ...
            default_work_weekdays=set(data.get("default_work_weekdays", [0, 1, 2, 3, 4])),
            holidays={date.fromisoformat(d) for d in data.get("holidays", [])},
        )
```

- [ ] **Step 10: Run all model tests**

Run: `pytest tests/test_models.py -v`
Expected: ALL PASS

- [ ] **Step 11: Commit**

```bash
git add ganttwarrior/models.py tests/test_models.py
git commit -m "feat: add work_days, work_weekdays, and calendar fields to models"
```

---

### Task 2: Create WorkCalendar helper

**Files:**
- Create: `ganttwarrior/work_calendar.py`
- Create: `tests/test_work_calendar.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_work_calendar.py`:

```python
"""Tests for work calendar logic."""

from datetime import date

import pytest

from ganttwarrior.models import Project, Task
from ganttwarrior.work_calendar import WorkCalendar


class TestWorkCalendar:
    def test_is_working_day_weekday(self):
        project = Project(name="Test", default_work_weekdays={0, 1, 2, 3, 4})
        cal = WorkCalendar(project)
        # 2026-03-25 is Wednesday
        assert cal.is_working_day(date(2026, 3, 25)) is True

    def test_is_working_day_weekend(self):
        project = Project(name="Test", default_work_weekdays={0, 1, 2, 3, 4})
        cal = WorkCalendar(project)
        # 2026-03-28 is Saturday
        assert cal.is_working_day(date(2026, 3, 28)) is False

    def test_is_working_day_holiday(self):
        project = Project(name="Test", default_work_weekdays={0, 1, 2, 3, 4})
        project.holidays = {date(2026, 3, 25)}
        cal = WorkCalendar(project)
        assert cal.is_working_day(date(2026, 3, 25)) is False

    def test_is_working_day_task_override(self):
        project = Project(name="Test", default_work_weekdays={0, 1, 2, 3, 4})
        cal = WorkCalendar(project)
        task = Task(name="Weekend Work", work_weekdays={5, 6})
        # Saturday is a work day for this task
        assert cal.is_working_day(date(2026, 3, 28), task=task) is True
        # Wednesday is NOT a work day for this task
        assert cal.is_working_day(date(2026, 3, 25), task=task) is False

    def test_expand_duration(self):
        project = Project(name="Test", default_work_weekdays={0, 1, 2, 3, 4})
        cal = WorkCalendar(project)
        # Start on Wednesday 2026-03-25, 5 work days
        days = cal.expand_duration(date(2026, 3, 25), 5)
        assert len(days) == 5
        # Wed, Thu, Fri, (skip Sat Sun), Mon, Tue
        assert days == {
            date(2026, 3, 25),  # Wed
            date(2026, 3, 26),  # Thu
            date(2026, 3, 27),  # Fri
            date(2026, 3, 30),  # Mon
            date(2026, 3, 31),  # Tue
        }

    def test_expand_duration_with_holiday(self):
        project = Project(name="Test", default_work_weekdays={0, 1, 2, 3, 4})
        project.holidays = {date(2026, 3, 26)}  # Thursday is a holiday
        cal = WorkCalendar(project)
        days = cal.expand_duration(date(2026, 3, 25), 3)
        # Wed, (skip Thu holiday), Fri, Mon
        assert days == {
            date(2026, 3, 25),  # Wed
            date(2026, 3, 27),  # Fri
            date(2026, 3, 30),  # Mon
        }

    def test_expand_duration_task_override(self):
        project = Project(name="Test", default_work_weekdays={0, 1, 2, 3, 4})
        cal = WorkCalendar(project)
        task = Task(name="Weekend", work_weekdays={5, 6})
        # Start on Saturday 2026-03-28, 2 work days
        days = cal.expand_duration(date(2026, 3, 28), 2, task=task)
        assert days == {
            date(2026, 3, 28),  # Sat
            date(2026, 3, 29),  # Sun
        }

    def test_expand_duration_zero(self):
        project = Project(name="Test")
        cal = WorkCalendar(project)
        days = cal.expand_duration(date(2026, 3, 25), 0)
        assert days == set()

    def test_get_week_dates(self):
        project = Project(name="Test", default_work_weekdays={0, 1, 2, 3, 4})
        cal = WorkCalendar(project)
        # Get work days for the week containing 2026-03-25 (Wed)
        days = cal.get_week_work_days(date(2026, 3, 25))
        assert days == {
            date(2026, 3, 23),  # Mon
            date(2026, 3, 24),  # Tue
            date(2026, 3, 25),  # Wed
            date(2026, 3, 26),  # Thu
            date(2026, 3, 27),  # Fri
        }

    def test_get_half_week_dates_first_half(self):
        project = Project(name="Test", default_work_weekdays={0, 1, 2, 3, 4})
        cal = WorkCalendar(project)
        # Monday is in first half (Mon-Wed)
        days = cal.get_half_week_work_days(date(2026, 3, 23))
        assert days == {
            date(2026, 3, 23),  # Mon
            date(2026, 3, 24),  # Tue
            date(2026, 3, 25),  # Wed
        }

    def test_get_half_week_dates_second_half(self):
        project = Project(name="Test", default_work_weekdays={0, 1, 2, 3, 4})
        cal = WorkCalendar(project)
        # Thursday is in second half (Thu-Fri)
        days = cal.get_half_week_work_days(date(2026, 3, 26))
        assert days == {
            date(2026, 3, 26),  # Thu
            date(2026, 3, 27),  # Fri
        }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_work_calendar.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ganttwarrior.work_calendar'`

- [ ] **Step 3: Implement WorkCalendar**

Create `ganttwarrior/work_calendar.py`:

```python
"""Work calendar logic for project and task scheduling."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from .models import Project, Task


class WorkCalendar:
    """Resolves working day rules for a project, with optional per-task overrides."""

    def __init__(self, project: Project):
        self.project = project

    def _effective_weekdays(self, task: Optional[Task] = None) -> set[int]:
        if task and task.work_weekdays is not None:
            return task.work_weekdays
        return self.project.default_work_weekdays

    def is_working_day(self, d: date, task: Optional[Task] = None) -> bool:
        weekdays = self._effective_weekdays(task)
        if d.weekday() not in weekdays:
            return False
        if d in self.project.holidays:
            return False
        return True

    def expand_duration(
        self, start: date, duration: int, task: Optional[Task] = None
    ) -> set[date]:
        if duration <= 0:
            return set()
        days: set[date] = set()
        current = start
        while len(days) < duration:
            if self.is_working_day(current, task):
                days.add(current)
            current += timedelta(days=1)
        return days

    def get_week_work_days(
        self, d: date, task: Optional[Task] = None
    ) -> set[date]:
        monday = d - timedelta(days=d.weekday())
        return {
            monday + timedelta(days=i)
            for i in range(7)
            if self.is_working_day(monday + timedelta(days=i), task)
        }

    def get_half_week_work_days(
        self, d: date, task: Optional[Task] = None
    ) -> set[date]:
        monday = d - timedelta(days=d.weekday())
        if d.weekday() <= 2:  # Mon-Wed = first half
            day_range = range(0, 3)
        else:  # Thu-Sun = second half
            day_range = range(3, 7)
        return {
            monday + timedelta(days=i)
            for i in day_range
            if self.is_working_day(monday + timedelta(days=i), task)
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_work_calendar.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add ganttwarrior/work_calendar.py tests/test_work_calendar.py
git commit -m "feat: add WorkCalendar for project/task work day resolution"
```

---

### Task 3: Create UndoStack

**Files:**
- Create: `ganttwarrior/undo.py`
- Create: `tests/test_undo.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_undo.py`:

```python
"""Tests for undo/redo stack."""

from datetime import date

import pytest

from ganttwarrior.undo import UndoEntry, UndoStack


class TestUndoStack:
    def test_push_and_undo(self):
        stack = UndoStack()
        entry = UndoEntry(
            task_ids=["t1"],
            before={"t1": frozenset({date(2026, 3, 25)})},
            after={"t1": frozenset({date(2026, 3, 25), date(2026, 3, 26)})},
            description="fill",
        )
        stack.push(entry)
        assert stack.can_undo
        undone = stack.undo()
        assert undone is entry
        assert not stack.can_undo

    def test_undo_then_redo(self):
        stack = UndoStack()
        entry = UndoEntry(
            task_ids=["t1"],
            before={"t1": frozenset({date(2026, 3, 25)})},
            after={"t1": frozenset({date(2026, 3, 25), date(2026, 3, 26)})},
            description="fill",
        )
        stack.push(entry)
        stack.undo()
        assert stack.can_redo
        redone = stack.redo()
        assert redone is entry

    def test_new_edit_clears_redo(self):
        stack = UndoStack()
        e1 = UndoEntry(task_ids=["t1"], before={}, after={}, description="e1")
        e2 = UndoEntry(task_ids=["t1"], before={}, after={}, description="e2")
        stack.push(e1)
        stack.undo()
        assert stack.can_redo
        stack.push(e2)
        assert not stack.can_redo

    def test_clear(self):
        stack = UndoStack()
        stack.push(UndoEntry(task_ids=["t1"], before={}, after={}, description="x"))
        stack.clear()
        assert not stack.can_undo
        assert not stack.can_redo

    def test_undo_empty_returns_none(self):
        stack = UndoStack()
        assert stack.undo() is None

    def test_redo_empty_returns_none(self):
        stack = UndoStack()
        assert stack.redo() is None

    def test_multiple_undos(self):
        stack = UndoStack()
        e1 = UndoEntry(task_ids=["t1"], before={}, after={}, description="e1")
        e2 = UndoEntry(task_ids=["t1"], before={}, after={}, description="e2")
        e3 = UndoEntry(task_ids=["t1"], before={}, after={}, description="e3")
        stack.push(e1)
        stack.push(e2)
        stack.push(e3)
        assert stack.undo() is e3
        assert stack.undo() is e2
        assert stack.undo() is e1
        assert stack.undo() is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_undo.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ganttwarrior.undo'`

- [ ] **Step 3: Implement UndoStack**

Create `ganttwarrior/undo.py`:

```python
"""Undo/redo stack for Gantt grid editor operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class UndoEntry:
    task_ids: list[str]
    before: dict[str, frozenset[date]]  # task_id -> work_days snapshot before
    after: dict[str, frozenset[date]]   # task_id -> work_days snapshot after
    description: str
    # For structural changes (split/merge), store full task list snapshots
    before_tasks: Optional[list] = None  # list of Task dicts
    after_tasks: Optional[list] = None


class UndoStack:
    def __init__(self) -> None:
        self._undo: list[UndoEntry] = []
        self._redo: list[UndoEntry] = []

    @property
    def can_undo(self) -> bool:
        return len(self._undo) > 0

    @property
    def can_redo(self) -> bool:
        return len(self._redo) > 0

    def push(self, entry: UndoEntry) -> None:
        self._undo.append(entry)
        self._redo.clear()

    def undo(self) -> Optional[UndoEntry]:
        if not self._undo:
            return None
        entry = self._undo.pop()
        self._redo.append(entry)
        return entry

    def redo(self) -> Optional[UndoEntry]:
        if not self._redo:
            return None
        entry = self._redo.pop()
        self._undo.append(entry)
        return entry

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_undo.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add ganttwarrior/undo.py tests/test_undo.py
git commit -m "feat: add UndoStack for grid editor operations"
```

---

### Task 4: Create GridEditor with fill, erase, clipboard, split, merge

**Files:**
- Create: `ganttwarrior/grid_editor.py`
- Create: `tests/test_grid_editor.py`

- [ ] **Step 1: Write failing tests for fill and erase**

Create `tests/test_grid_editor.py`:

```python
"""Tests for grid editor operations."""

from datetime import date

import pytest

from ganttwarrior.grid_editor import Clipboard, GridEditor
from ganttwarrior.models import Dependency, DependencyType, Project, Task


def _make_project() -> Project:
    project = Project(name="Test", start_date=date(2026, 3, 23))
    t1 = Task(id="t1", name="Task A", wbs="1")
    t1.work_days = {
        date(2026, 3, 23), date(2026, 3, 24), date(2026, 3, 25),
        date(2026, 3, 26), date(2026, 3, 27),
    }
    project.tasks.append(t1)
    t2 = Task(id="t2", name="Task B", wbs="2")
    t2.work_days = {date(2026, 3, 30), date(2026, 3, 31)}
    project.tasks.append(t2)
    return project


class TestFillErase:
    def test_fill_empty_cell(self):
        project = _make_project()
        editor = GridEditor(project)
        task = project.get_task("t1")
        editor.fill(task, date(2026, 3, 30))
        assert date(2026, 3, 30) in task.work_days
        assert task.manually_edited is True

    def test_fill_already_filled_is_noop(self):
        project = _make_project()
        editor = GridEditor(project)
        task = project.get_task("t1")
        before_count = len(task.work_days)
        editor.fill(task, date(2026, 3, 25))
        assert len(task.work_days) == before_count

    def test_fill_range(self):
        project = _make_project()
        editor = GridEditor(project)
        task = project.get_task("t1")
        editor.fill_range(task, date(2026, 3, 30), date(2026, 4, 1))
        assert date(2026, 3, 30) in task.work_days
        assert date(2026, 3, 31) in task.work_days
        assert date(2026, 4, 1) in task.work_days

    def test_erase_filled_cell(self):
        project = _make_project()
        editor = GridEditor(project)
        task = project.get_task("t1")
        editor.erase(task, date(2026, 3, 25))
        assert date(2026, 3, 25) not in task.work_days
        assert task.manually_edited is True
        assert task.duration_days == 4

    def test_erase_empty_cell_is_noop(self):
        project = _make_project()
        editor = GridEditor(project)
        task = project.get_task("t1")
        before_count = len(task.work_days)
        editor.erase(task, date(2026, 4, 5))
        assert len(task.work_days) == before_count

    def test_erase_range(self):
        project = _make_project()
        editor = GridEditor(project)
        task = project.get_task("t1")
        editor.erase_range(task, date(2026, 3, 24), date(2026, 3, 26))
        assert date(2026, 3, 24) not in task.work_days
        assert date(2026, 3, 25) not in task.work_days
        assert date(2026, 3, 26) not in task.work_days
        assert task.duration_days == 2

    def test_fill_creates_undo_entry(self):
        project = _make_project()
        editor = GridEditor(project)
        task = project.get_task("t1")
        editor.fill(task, date(2026, 3, 30))
        assert editor.undo_stack.can_undo

    def test_undo_fill(self):
        project = _make_project()
        editor = GridEditor(project)
        task = project.get_task("t1")
        editor.fill(task, date(2026, 3, 30))
        editor.undo()
        assert date(2026, 3, 30) not in task.work_days

    def test_redo_fill(self):
        project = _make_project()
        editor = GridEditor(project)
        task = project.get_task("t1")
        editor.fill(task, date(2026, 3, 30))
        editor.undo()
        editor.redo()
        assert date(2026, 3, 30) in task.work_days


class TestClipboard:
    def test_copy_selection(self):
        project = _make_project()
        editor = GridEditor(project)
        task = project.get_task("t1")
        editor.copy(task, date(2026, 3, 23), date(2026, 3, 27))
        assert editor.clipboard is not None
        assert editor.clipboard.offsets == [0, 1, 2, 3, 4]
        assert editor.clipboard.source_task_name == "Task A"

    def test_copy_with_gap(self):
        project = _make_project()
        task = project.get_task("t1")
        task.work_days.discard(date(2026, 3, 25))  # Remove Wednesday
        editor = GridEditor(project)
        editor.copy(task, date(2026, 3, 23), date(2026, 3, 27))
        # Offsets: Mon=0, Tue=1, (no Wed), Thu=3, Fri=4
        assert editor.clipboard.offsets == [0, 1, 3, 4]

    def test_cut_removes_days(self):
        project = _make_project()
        editor = GridEditor(project)
        task = project.get_task("t1")
        editor.cut(task, date(2026, 3, 24), date(2026, 3, 26))
        assert date(2026, 3, 24) not in task.work_days
        assert date(2026, 3, 25) not in task.work_days
        assert date(2026, 3, 26) not in task.work_days
        assert editor.clipboard is not None

    def test_paste_same_task(self):
        project = _make_project()
        editor = GridEditor(project)
        task = project.get_task("t1")
        # Copy Mon-Wed, paste starting at next Monday
        editor.copy(task, date(2026, 3, 23), date(2026, 3, 25))
        editor.paste(task, date(2026, 3, 30))
        assert date(2026, 3, 30) in task.work_days
        assert date(2026, 3, 31) in task.work_days
        assert date(2026, 4, 1) in task.work_days

    def test_paste_cross_task(self):
        project = _make_project()
        editor = GridEditor(project)
        t1 = project.get_task("t1")
        t2 = project.get_task("t2")
        editor.copy(t1, date(2026, 3, 23), date(2026, 3, 25))
        editor.paste(t2, date(2026, 4, 1))
        assert date(2026, 4, 1) in t2.work_days
        assert date(2026, 4, 2) in t2.work_days
        assert date(2026, 4, 3) in t2.work_days

    def test_paste_as_new_task(self):
        project = _make_project()
        editor = GridEditor(project)
        task = project.get_task("t1")
        editor.copy(task, date(2026, 3, 23), date(2026, 3, 25))
        new_task = editor.paste_as_new_task(date(2026, 4, 1), after_task=task)
        assert new_task.name == "Task (from Task A)"
        assert date(2026, 4, 1) in new_task.work_days
        assert new_task in project.tasks


class TestSplitMerge:
    def test_split_at_cursor(self):
        project = _make_project()
        editor = GridEditor(project)
        task = project.get_task("t1")
        # Split at Wednesday (day 3 of 5)
        task_a, task_b = editor.split(task, date(2026, 3, 25))
        assert task_a.work_days == {date(2026, 3, 23), date(2026, 3, 24)}
        assert task_b.work_days == {date(2026, 3, 25), date(2026, 3, 26), date(2026, 3, 27)}
        assert task_b.name == "Task A (continued)"
        # Task B has FS dependency on Task A
        assert len(task_b.dependencies) == 1
        assert task_b.dependencies[0].predecessor_id == task_a.id

    def test_merge(self):
        project = _make_project()
        editor = GridEditor(project)
        t1 = project.get_task("t1")
        t2 = project.get_task("t2")
        merged = editor.merge(t1, t2)
        assert merged.work_days == t1.work_days | t2.work_days
        assert merged.name == "Task A"
        assert t2 not in project.tasks

    def test_duplicate(self):
        project = _make_project()
        editor = GridEditor(project)
        task = project.get_task("t1")
        dup = editor.duplicate(task)
        assert dup.name == "Task A (copy)"
        assert dup.work_days == task.work_days
        assert dup.id != task.id
        assert dup in project.tasks
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_grid_editor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ganttwarrior.grid_editor'`

- [ ] **Step 3: Implement GridEditor**

Create `ganttwarrior/grid_editor.py`:

```python
"""Grid editor operations: fill, erase, clipboard, split, merge, undo."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from .models import Dependency, DependencyType, Project, Task
from .undo import UndoEntry, UndoStack


@dataclass
class Clipboard:
    offsets: list[int]  # Relative day offsets that have work
    source_task_name: str


class GridEditor:
    def __init__(self, project: Project):
        self.project = project
        self.undo_stack = UndoStack()
        self.clipboard: Optional[Clipboard] = None

    def _snapshot(self, task: Task) -> frozenset[date]:
        return frozenset(task.work_days)

    def _push_undo(
        self, task_ids: list[str], before: dict[str, frozenset[date]],
        after: dict[str, frozenset[date]], description: str,
    ) -> None:
        self.undo_stack.push(UndoEntry(
            task_ids=task_ids, before=before, after=after, description=description,
        ))

    def fill(self, task: Task, d: date) -> None:
        if d in task.work_days:
            return
        before = self._snapshot(task)
        task.work_days.add(d)
        task.manually_edited = True
        self._push_undo(
            [task.id], {task.id: before}, {task.id: self._snapshot(task)}, "fill",
        )

    def fill_range(self, task: Task, start: date, end: date) -> None:
        before = self._snapshot(task)
        current = start
        changed = False
        while current <= end:
            if current not in task.work_days:
                task.work_days.add(current)
                changed = True
            current += timedelta(days=1)
        if changed:
            task.manually_edited = True
            self._push_undo(
                [task.id], {task.id: before}, {task.id: self._snapshot(task)}, "fill range",
            )

    def erase(self, task: Task, d: date) -> None:
        if d not in task.work_days:
            return
        before = self._snapshot(task)
        task.work_days.discard(d)
        task.manually_edited = True
        self._push_undo(
            [task.id], {task.id: before}, {task.id: self._snapshot(task)}, "erase",
        )

    def erase_range(self, task: Task, start: date, end: date) -> None:
        before = self._snapshot(task)
        current = start
        changed = False
        while current <= end:
            if current in task.work_days:
                task.work_days.discard(current)
                changed = True
            current += timedelta(days=1)
        if changed:
            task.manually_edited = True
            self._push_undo(
                [task.id], {task.id: before}, {task.id: self._snapshot(task)}, "erase range",
            )

    def copy(self, task: Task, start: date, end: date) -> None:
        base = start
        offsets = []
        current = start
        while current <= end:
            if current in task.work_days:
                offsets.append((current - base).days)
            current += timedelta(days=1)
        self.clipboard = Clipboard(offsets=offsets, source_task_name=task.name)

    def cut(self, task: Task, start: date, end: date) -> None:
        self.copy(task, start, end)
        self.erase_range(task, start, end)

    def paste(self, task: Task, cursor_date: date) -> None:
        if not self.clipboard:
            return
        before = self._snapshot(task)
        for offset in self.clipboard.offsets:
            task.work_days.add(cursor_date + timedelta(days=offset))
        task.manually_edited = True
        self._push_undo(
            [task.id], {task.id: before}, {task.id: self._snapshot(task)}, "paste",
        )

    def paste_as_new_task(self, cursor_date: date, after_task: Task) -> Task:
        if not self.clipboard:
            raise ValueError("Nothing in clipboard")
        new_task = Task(name=f"Task (from {self.clipboard.source_task_name})")
        for offset in self.clipboard.offsets:
            new_task.work_days.add(cursor_date + timedelta(days=offset))
        new_task.manually_edited = True
        # Insert after the given task
        idx = self.project.tasks.index(after_task) + 1
        new_task.wbs = self.project.next_wbs(after_task.parent_wbs)
        self.project.tasks.insert(idx, new_task)
        return new_task

    def split(self, task: Task, cursor_date: date) -> tuple[Task, Task]:
        if cursor_date not in task.work_days:
            raise ValueError("Cannot split on a non-work day")
        before_days = {d for d in task.work_days if d < cursor_date}
        after_days = {d for d in task.work_days if d >= cursor_date}

        # Task A keeps the original
        task.work_days = before_days
        task.manually_edited = True

        # Task B is new
        task_b = Task(
            name=f"{task.name} (continued)",
            wbs="",  # Will be reassigned
            color=task.color,
            assigned_to=task.assigned_to,
            priority=task.priority,
            parent_wbs=task.parent_wbs,
            manually_edited=True,
        )
        task_b.work_days = after_days
        task_b.dependencies = [Dependency(task.id, DependencyType.FINISH_TO_START)]

        # Insert after original
        idx = self.project.tasks.index(task) + 1
        task_b.wbs = self.project.next_wbs(task.parent_wbs)
        self.project.tasks.insert(idx, task_b)

        return task, task_b

    def merge(self, task_a: Task, task_b: Task) -> Task:
        before_a = self._snapshot(task_a)
        task_a.work_days = task_a.work_days | task_b.work_days
        task_a.manually_edited = True
        # Absorb dependencies from task_b (skip self-referencing)
        existing_pred_ids = {d.predecessor_id for d in task_a.dependencies}
        for dep in task_b.dependencies:
            if dep.predecessor_id != task_a.id and dep.predecessor_id not in existing_pred_ids:
                task_a.dependencies.append(dep)
        self.project.remove_task(task_b.id)
        self._push_undo(
            [task_a.id], {task_a.id: before_a}, {task_a.id: self._snapshot(task_a)}, "merge",
        )
        return task_a

    def duplicate(self, task: Task) -> Task:
        new_task = Task(
            name=f"{task.name} (copy)",
            color=task.color,
            assigned_to=task.assigned_to,
            priority=task.priority,
            parent_wbs=task.parent_wbs,
        )
        new_task.work_days = set(task.work_days)
        idx = self.project.tasks.index(task) + 1
        new_task.wbs = self.project.next_wbs(task.parent_wbs)
        self.project.tasks.insert(idx, new_task)
        return new_task

    def undo(self) -> bool:
        entry = self.undo_stack.undo()
        if not entry:
            return False
        for tid, snapshot in entry.before.items():
            task = self.project.get_task(tid)
            if task:
                task.work_days = set(snapshot)
        return True

    def redo(self) -> bool:
        entry = self.undo_stack.redo()
        if not entry:
            return False
        for tid, snapshot in entry.after.items():
            task = self.project.get_task(tid)
            if task:
                task.work_days = set(snapshot)
        return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_grid_editor.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add ganttwarrior/grid_editor.py tests/test_grid_editor.py
git commit -m "feat: add GridEditor with fill, erase, clipboard, split, merge, undo"
```

---

### Task 5: Rewrite GanttChart with cell-grid cursor, selection, and editing bindings

**Files:**
- Modify: `ganttwarrior/views/gantt.py`

- [ ] **Step 1: Add cursor and selection state to GanttChart**

In `ganttwarrior/views/gantt.py`, update imports and `GanttChart` class. Add `cursor_col` (a date), `selection_start`, `selection_end`, and `zoom_level` reactives:

```python
from enum import Enum

from ..grid_editor import GridEditor
from ..work_calendar import WorkCalendar


class ZoomLevel(str, Enum):
    DAY = "day"
    HALF_WEEK = "half_week"
    WEEK = "week"
```

Update `GanttChart.__init__`:

```python
    def __init__(self, project: Project, editor: GridEditor, day_width: int = 2, **kwargs):
        super().__init__(**kwargs)
        self.project = project
        self.editor = editor
        self.calendar = WorkCalendar(project)
        self.day_width = day_width
        self.label_width = 35
        self._task_rows: list[GanttTaskRow] = []
        self._chart_start: date = date.today()
        self._chart_end: date = date.today() + timedelta(days=30)
        self.zoom_level = ZoomLevel.DAY
```

Add reactives:

```python
    selected_index: reactive[int] = reactive(0)
    cursor_col: reactive[Optional[date]] = reactive(None)
    selection_start: reactive[Optional[date]] = reactive(None)
    selection_end: reactive[Optional[date]] = reactive(None)
```

- [ ] **Step 2: Update GanttChart bindings**

Replace the existing `BINDINGS` list with the full keyboard map:

```python
    BINDINGS = [
        Binding("up", "cursor_up", "Up"),
        Binding("down", "cursor_down", "Down"),
        Binding("left", "cursor_left", "Left"),
        Binding("right", "cursor_right", "Right"),
        Binding("ctrl+left", "jump_week_left", "Week Left", show=False),
        Binding("ctrl+right", "jump_week_right", "Week Right", show=False),
        Binding("home", "jump_bar_start", "Bar Start", show=False),
        Binding("end", "jump_bar_end", "Bar End", show=False),
        Binding("ctrl+home", "jump_project_start", "Project Start", show=False),
        Binding("ctrl+end", "jump_project_end", "Project End", show=False),
        Binding("tab", "next_task_bar", "Next Bar", show=False),
        Binding("shift+tab", "prev_task_bar", "Prev Bar", show=False),
        Binding("shift+left", "select_left", "Select Left", show=False),
        Binding("shift+right", "select_right", "Select Right", show=False),
        Binding("shift+home", "select_to_bar_start", "Select to Start", show=False),
        Binding("shift+end", "select_to_bar_end", "Select to End", show=False),
        Binding("ctrl+a", "select_all_bar", "Select All", show=False),
        Binding("space", "fill_cell", "Fill"),
        Binding("enter", "fill_cell", "Fill", show=False),
        Binding("delete", "erase_cell", "Erase"),
        Binding("backspace", "erase_cell", "Erase", show=False),
        Binding("ctrl+c", "copy", "Copy", show=False),
        Binding("ctrl+x", "cut", "Cut", show=False),
        Binding("ctrl+v", "paste", "Paste", show=False),
        Binding("shift+insert", "paste", "Paste", show=False),
        Binding("ctrl+shift+v", "paste_new_task", "Paste New", show=False),
        Binding("ctrl+z", "undo", "Undo", show=False),
        Binding("ctrl+y", "redo", "Redo", show=False),
        Binding("ctrl+k", "split_task", "Split", show=False),
        Binding("ctrl+m", "merge_task", "Merge", show=False),
        Binding("ctrl+d", "duplicate_task", "Duplicate", show=False),
        Binding("plus_sign", "zoom_in", "+Zoom", show=False),
        Binding("minus", "zoom_out", "-Zoom", show=False),
    ]
```

- [ ] **Step 3: Implement navigation actions**

Add cursor navigation methods to `GanttChart`:

```python
    def _ensure_cursor(self) -> None:
        """Initialize cursor_col to the selected task's start date if not set."""
        if self.cursor_col is None and self._task_rows:
            task = self._task_rows[self.selected_index].gantt_task
            if task.work_days:
                self.cursor_col = min(task.work_days)
            else:
                self.cursor_col = self._chart_start

    def _clear_selection(self) -> None:
        self.selection_start = None
        self.selection_end = None

    def action_cursor_left(self) -> None:
        self._ensure_cursor()
        self._clear_selection()
        if self.cursor_col and self.cursor_col > self._chart_start:
            self.cursor_col = self.cursor_col - timedelta(days=1)
            self._refresh_row(self.selected_index)

    def action_cursor_right(self) -> None:
        self._ensure_cursor()
        self._clear_selection()
        if self.cursor_col and self.cursor_col < self._chart_end:
            self.cursor_col = self.cursor_col + timedelta(days=1)
            self._refresh_row(self.selected_index)

    def action_cursor_up(self) -> None:
        if self._task_rows and self.selected_index > 0:
            self._task_rows[self.selected_index].remove_class("selected")
            self.selected_index -= 1
            self._task_rows[self.selected_index].add_class("selected")
            self._task_rows[self.selected_index].scroll_visible()
            self._clear_selection()
            self._refresh_row(self.selected_index)
            self._refresh_row(self.selected_index + 1)

    def action_cursor_down(self) -> None:
        if self._task_rows and self.selected_index < len(self._task_rows) - 1:
            self._task_rows[self.selected_index].remove_class("selected")
            self.selected_index += 1
            self._task_rows[self.selected_index].add_class("selected")
            self._task_rows[self.selected_index].scroll_visible()
            self._clear_selection()
            self._refresh_row(self.selected_index)
            self._refresh_row(self.selected_index - 1)

    def action_jump_week_left(self) -> None:
        self._ensure_cursor()
        self._clear_selection()
        if self.cursor_col:
            self.cursor_col = max(self.cursor_col - timedelta(days=7), self._chart_start)
            self._refresh_row(self.selected_index)

    def action_jump_week_right(self) -> None:
        self._ensure_cursor()
        self._clear_selection()
        if self.cursor_col:
            self.cursor_col = min(self.cursor_col + timedelta(days=7), self._chart_end)
            self._refresh_row(self.selected_index)

    def action_jump_bar_start(self) -> None:
        if self._task_rows:
            task = self._task_rows[self.selected_index].gantt_task
            if task.work_days:
                self.cursor_col = min(task.work_days)
                self._clear_selection()
                self._refresh_row(self.selected_index)

    def action_jump_bar_end(self) -> None:
        if self._task_rows:
            task = self._task_rows[self.selected_index].gantt_task
            if task.work_days:
                self.cursor_col = max(task.work_days)
                self._clear_selection()
                self._refresh_row(self.selected_index)

    def action_jump_project_start(self) -> None:
        self.cursor_col = self._chart_start
        self._clear_selection()
        self._refresh_row(self.selected_index)

    def action_jump_project_end(self) -> None:
        self.cursor_col = self._chart_end
        self._clear_selection()
        self._refresh_row(self.selected_index)

    def action_next_task_bar(self) -> None:
        if self.selected_index < len(self._task_rows) - 1:
            self.action_cursor_down()
            self.action_jump_bar_start()

    def action_prev_task_bar(self) -> None:
        if self.selected_index > 0:
            self.action_cursor_up()
            self.action_jump_bar_start()

    def _refresh_row(self, index: int) -> None:
        """Trigger re-render of a specific row."""
        if 0 <= index < len(self._task_rows):
            row = self._task_rows[index]
            row.cursor_date = self.cursor_col if index == self.selected_index else None
            row.sel_start = self.selection_start if index == self.selected_index else None
            row.sel_end = self.selection_end if index == self.selected_index else None
            row.refresh()
```

- [ ] **Step 4: Implement selection actions**

```python
    def action_select_left(self) -> None:
        self._ensure_cursor()
        if not self.cursor_col:
            return
        if self.selection_start is None:
            self.selection_start = self.cursor_col
            self.selection_end = self.cursor_col
        new_col = self.cursor_col - timedelta(days=1)
        if new_col >= self._chart_start:
            self.cursor_col = new_col
            self.selection_start = min(self.selection_start, new_col)
            self.selection_end = max(self.selection_end, new_col)
            self._refresh_row(self.selected_index)

    def action_select_right(self) -> None:
        self._ensure_cursor()
        if not self.cursor_col:
            return
        if self.selection_start is None:
            self.selection_start = self.cursor_col
            self.selection_end = self.cursor_col
        new_col = self.cursor_col + timedelta(days=1)
        if new_col <= self._chart_end:
            self.cursor_col = new_col
            self.selection_end = max(self.selection_end, new_col)
            self.selection_start = min(self.selection_start, new_col)
            self._refresh_row(self.selected_index)

    def action_select_to_bar_start(self) -> None:
        self._ensure_cursor()
        if not self._task_rows or not self.cursor_col:
            return
        task = self._task_rows[self.selected_index].gantt_task
        if task.work_days:
            bar_start = min(task.work_days)
            self.selection_start = bar_start
            self.selection_end = self.cursor_col
            self._refresh_row(self.selected_index)

    def action_select_to_bar_end(self) -> None:
        self._ensure_cursor()
        if not self._task_rows or not self.cursor_col:
            return
        task = self._task_rows[self.selected_index].gantt_task
        if task.work_days:
            bar_end = max(task.work_days)
            self.selection_start = self.cursor_col
            self.selection_end = bar_end
            self._refresh_row(self.selected_index)

    def action_select_all_bar(self) -> None:
        if not self._task_rows:
            return
        task = self._task_rows[self.selected_index].gantt_task
        if task.work_days:
            self.selection_start = min(task.work_days)
            self.selection_end = max(task.work_days)
            self._refresh_row(self.selected_index)
```

- [ ] **Step 5: Implement editing actions**

```python
    def action_fill_cell(self) -> None:
        self._ensure_cursor()
        if not self._task_rows or not self.cursor_col:
            return
        task = self._task_rows[self.selected_index].gantt_task
        if self.selection_start and self.selection_end:
            self.editor.fill_range(task, self.selection_start, self.selection_end)
            self._clear_selection()
        else:
            self.editor.fill(task, self.cursor_col)
        self.refresh_chart()

    def action_erase_cell(self) -> None:
        self._ensure_cursor()
        if not self._task_rows or not self.cursor_col:
            return
        task = self._task_rows[self.selected_index].gantt_task
        if self.selection_start and self.selection_end:
            self.editor.erase_range(task, self.selection_start, self.selection_end)
            self._clear_selection()
        else:
            self.editor.erase(task, self.cursor_col)
        self.refresh_chart()

    def action_copy(self) -> None:
        if not self._task_rows:
            return
        task = self._task_rows[self.selected_index].gantt_task
        if self.selection_start and self.selection_end:
            self.editor.copy(task, self.selection_start, self.selection_end)
        elif task.work_days:
            self.editor.copy(task, min(task.work_days), max(task.work_days))

    def action_cut(self) -> None:
        if not self._task_rows:
            return
        task = self._task_rows[self.selected_index].gantt_task
        if self.selection_start and self.selection_end:
            self.editor.cut(task, self.selection_start, self.selection_end)
            self._clear_selection()
        elif task.work_days:
            self.editor.cut(task, min(task.work_days), max(task.work_days))
        self.refresh_chart()

    def action_paste(self) -> None:
        self._ensure_cursor()
        if not self._task_rows or not self.cursor_col or not self.editor.clipboard:
            return
        task = self._task_rows[self.selected_index].gantt_task
        self.editor.paste(task, self.cursor_col)
        self.refresh_chart()

    def action_paste_new_task(self) -> None:
        self._ensure_cursor()
        if not self._task_rows or not self.cursor_col or not self.editor.clipboard:
            return
        task = self._task_rows[self.selected_index].gantt_task
        self.editor.paste_as_new_task(self.cursor_col, after_task=task)
        self.refresh_chart()

    def action_undo(self) -> None:
        if self.editor.undo():
            self.refresh_chart()

    def action_redo(self) -> None:
        if self.editor.redo():
            self.refresh_chart()

    def action_split_task(self) -> None:
        self._ensure_cursor()
        if not self._task_rows or not self.cursor_col:
            return
        task = self._task_rows[self.selected_index].gantt_task
        if self.cursor_col in task.work_days:
            self.editor.split(task, self.cursor_col)
            self.refresh_chart()

    def action_merge_task(self) -> None:
        if not self._task_rows or self.selected_index >= len(self._task_rows) - 1:
            return
        task_a = self._task_rows[self.selected_index].gantt_task
        task_b = self._task_rows[self.selected_index + 1].gantt_task
        self.editor.merge(task_a, task_b)
        self.refresh_chart()

    def action_duplicate_task(self) -> None:
        if not self._task_rows:
            return
        task = self._task_rows[self.selected_index].gantt_task
        self.editor.duplicate(task)
        self.refresh_chart()

    def action_zoom_in(self) -> None:
        if self.zoom_level == ZoomLevel.WEEK:
            self.zoom_level = ZoomLevel.HALF_WEEK
        elif self.zoom_level == ZoomLevel.HALF_WEEK:
            self.zoom_level = ZoomLevel.DAY
        self.refresh_chart()

    def action_zoom_out(self) -> None:
        if self.zoom_level == ZoomLevel.DAY:
            self.zoom_level = ZoomLevel.HALF_WEEK
        elif self.zoom_level == ZoomLevel.HALF_WEEK:
            self.zoom_level = ZoomLevel.WEEK
        self.refresh_chart()
```

- [ ] **Step 6: Update GanttTaskRow to accept and render cursor/selection**

Add to `GanttTaskRow.__init__`:

```python
        self.cursor_date: Optional[date] = None
        self.sel_start: Optional[date] = None
        self.sel_end: Optional[date] = None
```

Rewrite `GanttTaskRow.render()` to render cell-by-cell with cursor/selection highlighting:

```python
    def render(self) -> Text:
        task = self.gantt_task
        total_days = (self.chart_end - self.chart_start).days + 1

        # Build label section
        indent = "  " * (task.wbs_level - 1) if task.wbs_level > 0 else ""
        status_sym = STATUS_SYMBOLS.get(task.status, "?")
        wbs_str = f"{task.wbs}" if task.wbs else ""
        label = f"{indent}{status_sym} {wbs_str} {task.name}"
        if len(label) > self.label_width - 2:
            label = label[: self.label_width - 5] + "..."

        line = Text()
        line.append(label.ljust(self.label_width), style="bold" if task.is_critical else "")
        line.append("│", style="dim")

        color = COLOR_MAP.get(task.color, "white")
        bar_style = Style(color=color, bold=task.is_critical)
        cursor_style = Style(color="black", bgcolor="yellow", bold=True)
        selection_style = Style(color=color, bgcolor="rgb(80,60,0)")
        non_working_style = Style(color="rgb(60,60,60)")
        gap_style = Style(color="rgb(100,100,100)")

        for i in range(total_days):
            d = self.chart_start + timedelta(days=i)
            is_cursor = self.cursor_date == d
            is_selected = (
                self.sel_start is not None and self.sel_end is not None
                and self.sel_start <= d <= self.sel_end
            )
            is_filled = d in task.work_days
            is_weekend = d.weekday() >= 5

            cell = self.day_width
            if is_cursor:
                if is_filled:
                    line.append("▓" * cell, style=cursor_style)
                else:
                    line.append("▓" * cell, style=Style(color="yellow", bgcolor="rgb(60,60,0)"))
            elif is_selected:
                if is_filled:
                    line.append("▒" * cell, style=selection_style)
                else:
                    line.append("▒" * cell, style=Style(color="rgb(80,60,0)", bgcolor="rgb(40,30,0)"))
            elif is_filled:
                line.append("█" * cell, style=bar_style)
            elif is_weekend:
                line.append(" ·"[:cell].ljust(cell), style=non_working_style)
            elif task.work_days and min(task.work_days) <= d <= max(task.work_days):
                line.append("··"[:cell].ljust(cell), style=gap_style)
            else:
                line.append(" " * cell)

        return line
```

- [ ] **Step 7: Run all tests**

Run: `pytest tests/ -v`
Expected: ALL PASS (may need to update test fixtures that construct `GanttChart` to pass the new `editor` parameter)

- [ ] **Step 8: Commit**

```bash
git add ganttwarrior/views/gantt.py
git commit -m "feat: rewrite GanttChart with cell-grid cursor, selection, and editing"
```

---

### Task 6: Wire GanttChart editor into app.py

**Files:**
- Modify: `ganttwarrior/app.py`

- [ ] **Step 1: Create GridEditor in GanttWarriorApp and pass to GanttChart**

In `ganttwarrior/app.py`, add import:

```python
from .grid_editor import GridEditor
```

In `GanttWarriorApp.__init__`, after setting `self.project`, add:

```python
        self.editor = GridEditor(self.project)
```

In `compose()`, update the GanttChart construction:

```python
                yield GanttChart(self.project, self.editor, id="gantt-chart")
```

- [ ] **Step 2: Clear undo stack on save**

In `action_save_project()`, after successful save, add:

```python
            self.editor.undo_stack.clear()
```

- [ ] **Step 3: Update info panel for cursor context**

Add a new message handler for cursor info updates. In `GanttChart`, post a message when cursor moves. In `GanttWarriorApp._update_task_info`, add cursor date context:

```python
    def _update_task_info(self, task: Task) -> None:
        panel = self.query_one("#task-info-panel", Static)
        deps = ", ".join(
            f"{self.project.get_task(d.predecessor_id).name if self.project.get_task(d.predecessor_id) else d.predecessor_id} ({d.dependency_type.value})"
            for d in task.dependencies
        ) if task.dependencies else "None"

        gantt = self.query_one("#gantt-chart", GanttChart)
        cursor_info = ""
        if gantt.cursor_col:
            filled = "filled" if gantt.cursor_col in task.work_days else "empty"
            gaps = 0
            if task.work_days:
                span_start = min(task.work_days)
                span_end = max(task.work_days)
                span_days = (span_end - span_start).days + 1
                gaps = span_days - len(task.work_days)
            cursor_info = f" │ Cursor: {gantt.cursor_col} ({filled}) │ Gaps: {gaps}"

        info = (
            f"[bold]{task.wbs}[/bold] {task.name}\n"
            f"Status: {task.status.value} │ Work days: {task.duration_days}d │ "
            f"Progress: {int(task.progress * 100)}% │ Priority: {task.priority}\n"
            f"Start: {task.start_date} │ End: {task.end_date} │ "
            f"Float: {task.total_float}d │ Critical: {'Yes' if task.is_critical else 'No'}{cursor_info}\n"
            f"Assigned: {task.assigned_to or '-'} │ Dependencies: {deps}"
        )
        panel.update(info)
```

- [ ] **Step 4: Run app to verify**

Run: `python -m ganttwarrior demo`
Expected: Gantt chart renders with cell grid. Arrow keys navigate. Space fills. Delete erases. Ctrl+Z undoes.

- [ ] **Step 5: Commit**

```bash
git add ganttwarrior/app.py
git commit -m "feat: wire grid editor into app with cursor info and undo-on-save"
```

---

### Task 7: Update scheduler to use work_days

**Files:**
- Modify: `ganttwarrior/scheduler.py`
- Modify: `tests/test_scheduler.py`

- [ ] **Step 1: Write failing test for manually_edited respect**

Add to `tests/test_scheduler.py`:

```python
    def test_manually_edited_preserved(self):
        project = Project(name="Test", start_date=date(2026, 1, 5))
        t1 = project.add_task(Task(name="A", wbs="1", duration_days=5))
        t1.work_days = {
            date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7),
            date(2026, 1, 8), date(2026, 1, 9),
        }
        t1.manually_edited = True

        scheduler = Scheduler(project)
        scheduler.schedule(date(2026, 1, 5))

        # work_days should not be overwritten
        assert t1.work_days == {
            date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7),
            date(2026, 1, 8), date(2026, 1, 9),
        }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scheduler.py::TestScheduler::test_manually_edited_preserved -v`
Expected: May pass or fail depending on current scheduler behavior. If the scheduler overwrites `start_date`/`end_date`, and those are now computed from `work_days`, the behavior may already be correct. Verify and adjust.

- [ ] **Step 3: Update scheduler forward_pass to respect work_days**

In `scheduler.py`, in `forward_pass()`, update the section that sets task dates:

```python
            # Update the task's actual dates
            if not task.manually_edited:
                task.start_date = task.early_start
                task.end_date = task.early_finish
            # For manually_edited tasks, only update scheduling metadata
            # (early_start/early_finish/late_start/late_finish are metadata,
            # not the authoritative schedule)
```

- [ ] **Step 4: Update test fixtures to populate work_days**

In `tests/test_scheduler.py`, update `_make_project` and other helpers to set `work_days` on tasks, since `add_task` now needs to populate them. Also ensure `WorkCalendar` is used for expansion in `Project.add_task`.

- [ ] **Step 5: Run all scheduler tests**

Run: `pytest tests/test_scheduler.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add ganttwarrior/scheduler.py tests/test_scheduler.py
git commit -m "feat: update scheduler to respect work_days and manually_edited flag"
```

---

### Task 8: Update Project.add_task to populate work_days via WorkCalendar

**Files:**
- Modify: `ganttwarrior/models.py:224-231` (Project.add_task)

- [ ] **Step 1: Update add_task to expand work_days**

This is the integration point where new tasks get their `work_days` populated. In `Project.add_task`, after computing `end_date`, populate `work_days` if empty:

```python
    def add_task(self, task: Task) -> Task:
        if not task.wbs:
            task.wbs = self.next_wbs(task.parent_wbs)
        if not task.start_date:
            task.start_date = self.start_date or date.today()
        task.compute_end_date()
        # Populate work_days from duration if not already set
        if not task.work_days and task.start_date and task.duration_days > 0:
            from .work_calendar import WorkCalendar
            cal = WorkCalendar(self)
            task.work_days = cal.expand_duration(task.start_date, task.duration_days, task)
        self.tasks.append(task)
        return task
```

- [ ] **Step 2: Run all tests**

Run: `pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add ganttwarrior/models.py
git commit -m "feat: populate work_days via WorkCalendar when adding tasks"
```

---

### Task 9: Update export and calendar_io for work_days compatibility

**Files:**
- Modify: `ganttwarrior/export.py`
- Modify: `ganttwarrior/calendar_io.py`

- [ ] **Step 1: Verify exports still work**

Since `start_date`, `end_date`, and `duration_days` are now computed properties that still return valid values from `work_days`, most export code should work unchanged. Run:

Run: `pytest tests/test_export.py tests/test_calendar_io.py -v`

If tests pass, the exports are compatible. If any fail, fix the specific references.

- [ ] **Step 2: Update calendar_io import to populate work_days**

In `ganttwarrior/calendar_io.py`, in `import_ical`, after creating the task and before appending to project:

```python
        # Populate work_days from the computed dates
        if start_date and end_date:
            task.work_days = set()
            current = start_date
            while current <= end_date:
                if current.weekday() < 5:  # Default Mon-Fri
                    task.work_days.add(current)
                current += timedelta(days=1)
```

- [ ] **Step 3: Run all tests**

Run: `pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add ganttwarrior/export.py ganttwarrior/calendar_io.py
git commit -m "feat: update export and calendar_io for work_days compatibility"
```

---

### Task 10: Update demo to use work_days and final integration test

**Files:**
- Modify: `ganttwarrior/__main__.py` (demo function)

- [ ] **Step 1: Run the demo and verify everything works**

Run: `python -m ganttwarrior demo`

Verify:
- Chart renders with cell grid and weekend columns
- Arrow keys move cursor (all 4 directions)
- Space fills a cell, Delete erases
- Shift+Arrow selects, Ctrl+C copies, Ctrl+V pastes
- Ctrl+Z undoes, Ctrl+Y redoes
- Ctrl+K splits, Ctrl+M merges
- `+`/`-` changes zoom level
- Info panel shows cursor date and fill status
- `s` saves and clears undo stack

- [ ] **Step 2: Run full test suite**

Run: `pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "feat: complete Gantt grid editor with cell navigation, editing, and zoom"
```

"""Tests for GanttWarrior scheduler."""

from datetime import date, timedelta

import pytest

from ganttwarrior.models import (
    Dependency,
    DependencyType,
    Project,
    Task,
    TaskColor,
    TaskStatus,
)
from ganttwarrior.scheduler import Scheduler, SchedulerError


class TestScheduler:
    def _make_project(self) -> Project:
        """Create a simple project with dependencies."""
        project = Project(name="Test", start_date=date(2026, 1, 5))

        t1 = project.add_task(Task(name="Task A", wbs="1", duration_days=5))
        t2 = project.add_task(Task(
            name="Task B", wbs="2", duration_days=3,
            dependencies=[Dependency(t1.id, DependencyType.FINISH_TO_START)],
        ))
        t3 = project.add_task(Task(
            name="Task C", wbs="3", duration_days=4,
            dependencies=[Dependency(t1.id, DependencyType.FINISH_TO_START)],
        ))
        t4 = project.add_task(Task(
            name="Task D", wbs="4", duration_days=2,
            dependencies=[
                Dependency(t2.id, DependencyType.FINISH_TO_START),
                Dependency(t3.id, DependencyType.FINISH_TO_START),
            ],
        ))
        return project

    def test_forward_pass(self):
        project = self._make_project()
        scheduler = Scheduler(project)
        scheduler._build_graph()
        scheduler.forward_pass(date(2026, 1, 5))

        tasks = {t.wbs: t for t in project.tasks}

        # Task A: starts Jan 5, 5 days -> ends Jan 9
        assert tasks["1"].early_start == date(2026, 1, 5)
        assert tasks["1"].early_finish == date(2026, 1, 9)

        # Task B: after A, starts Jan 10, 3 days -> ends Jan 12
        assert tasks["2"].early_start == date(2026, 1, 10)
        assert tasks["2"].early_finish == date(2026, 1, 12)

        # Task C: after A, starts Jan 10, 4 days -> ends Jan 13
        assert tasks["3"].early_start == date(2026, 1, 10)
        assert tasks["3"].early_finish == date(2026, 1, 13)

        # Task D: after B and C, starts Jan 14, 2 days -> ends Jan 15
        assert tasks["4"].early_start == date(2026, 1, 14)
        assert tasks["4"].early_finish == date(2026, 1, 15)

    def test_critical_path(self):
        project = self._make_project()
        scheduler = Scheduler(project)
        critical = scheduler.schedule(date(2026, 1, 5))

        # Critical path: A -> C -> D (longest path)
        critical_wbs = {t.wbs for t in critical}
        assert "1" in critical_wbs  # Task A
        assert "3" in critical_wbs  # Task C (4 days > B's 3 days)
        assert "4" in critical_wbs  # Task D

    def test_float_calculation(self):
        project = self._make_project()
        scheduler = Scheduler(project)
        scheduler.schedule(date(2026, 1, 5))

        tasks = {t.wbs: t for t in project.tasks}

        # Task B has float (not on critical path)
        assert tasks["2"].total_float > 0

        # Critical path tasks have 0 float
        assert tasks["1"].total_float == 0
        assert tasks["3"].total_float == 0
        assert tasks["4"].total_float == 0

    def test_blocking(self):
        project = self._make_project()
        scheduler = Scheduler(project)
        scheduler.schedule()

        tasks = {t.wbs: t for t in project.tasks}
        # Tasks with unfinished predecessors should be blocked
        assert tasks["2"].status == TaskStatus.BLOCKED
        assert tasks["4"].status == TaskStatus.BLOCKED

    def test_unblocking(self):
        project = self._make_project()
        tasks = {t.wbs: t for t in project.tasks}

        # Complete Task A
        tasks["1"].status = TaskStatus.COMPLETED

        scheduler = Scheduler(project)
        scheduler.schedule()

        # B and C should be unblocked
        assert tasks["2"].status == TaskStatus.NOT_STARTED
        assert tasks["3"].status == TaskStatus.NOT_STARTED
        # D still blocked (needs B and C)
        assert tasks["4"].status == TaskStatus.BLOCKED

    def test_lag_days(self):
        project = Project(name="Lag Test", start_date=date(2026, 1, 5))
        t1 = project.add_task(Task(name="A", wbs="1", duration_days=3))
        t2 = project.add_task(Task(
            name="B", wbs="2", duration_days=2,
            dependencies=[Dependency(t1.id, DependencyType.FINISH_TO_START, lag_days=2)],
        ))

        scheduler = Scheduler(project)
        scheduler.schedule(date(2026, 1, 5))

        # A: Jan 5-7, B: Jan 7 + 1 + 2 lag = Jan 10, ends Jan 11
        assert t2.early_start == date(2026, 1, 10)

    def test_circular_dependency_detection(self):
        project = Project(name="Circular", start_date=date(2026, 1, 1))
        t1 = project.add_task(Task(name="A", wbs="1", duration_days=1))
        t2 = project.add_task(Task(
            name="B", wbs="2", duration_days=1,
            dependencies=[Dependency(t1.id)],
        ))
        # Create circular: A depends on B, B depends on A
        t1.dependencies.append(Dependency(t2.id))

        scheduler = Scheduler(project)
        with pytest.raises(SchedulerError, match="[Cc]ircular"):
            scheduler.schedule()

    def test_ready_tasks(self):
        project = self._make_project()
        scheduler = Scheduler(project)
        scheduler.schedule()

        ready = scheduler.get_ready_tasks()
        # Only Task A has no predecessors
        assert len(ready) == 1
        assert ready[0].wbs == "1"

    def test_critical_path_duration(self):
        project = self._make_project()
        scheduler = Scheduler(project)
        scheduler.schedule(date(2026, 1, 5))

        duration = scheduler.get_critical_path_duration()
        # A(5) + C(4) + D(2) = 11 days
        assert duration == 11

    def test_empty_project(self):
        project = Project(name="Empty", start_date=date(2026, 1, 1))
        scheduler = Scheduler(project)
        critical = scheduler.schedule()
        assert critical == []

    def test_single_task(self):
        project = Project(name="Single", start_date=date(2026, 1, 5))
        project.add_task(Task(name="Only", wbs="1", duration_days=3))

        scheduler = Scheduler(project)
        critical = scheduler.schedule(date(2026, 1, 5))

        assert len(critical) == 1
        assert critical[0].early_start == date(2026, 1, 5)
        assert critical[0].early_finish == date(2026, 1, 7)

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

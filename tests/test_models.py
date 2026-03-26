"""Tests for GanttWarrior data models."""

import json
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pytest

from ganttwarrior.models import (
    Dependency,
    DependencyType,
    Project,
    Task,
    TaskColor,
    TaskStatus,
)


class TestTask:
    def test_create_task(self):
        task = Task(name="Test Task", duration_days=5)
        assert task.name == "Test Task"
        assert task.duration_days == 5
        assert task.status == TaskStatus.NOT_STARTED
        assert task.color == TaskColor.BLUE
        assert task.progress == 0.0

    def test_wbs_parts(self):
        task = Task(wbs="1.2.3")
        assert task.wbs_parts == [1, 2, 3]
        assert task.wbs_level == 3
        assert task.wbs_parent == "1.2"

    def test_wbs_parent_top_level(self):
        task = Task(wbs="1")
        assert task.wbs_parent == ""
        assert task.wbs_level == 1

    def test_compute_end_date(self):
        task = Task(start_date=date(2026, 1, 1), duration_days=5)
        task.compute_end_date()
        assert task.end_date == date(2026, 1, 5)

    def test_compute_end_date_single_day(self):
        task = Task(start_date=date(2026, 1, 1), duration_days=1)
        task.compute_end_date()
        assert task.end_date == date(2026, 1, 1)

    def test_serialization(self):
        task = Task(
            name="Serialize Me",
            wbs="2.1",
            start_date=date(2026, 3, 1),
            duration_days=3,
            color=TaskColor.RED,
            dependencies=[Dependency("abc123", DependencyType.FINISH_TO_START, lag_days=2)],
        )
        task.compute_end_date()
        data = task.to_dict()
        restored = Task.from_dict(data)

        assert restored.name == "Serialize Me"
        assert restored.wbs == "2.1"
        assert restored.start_date == date(2026, 3, 1)
        assert restored.end_date == date(2026, 3, 3)
        assert restored.color == TaskColor.RED
        assert len(restored.dependencies) == 1
        assert restored.dependencies[0].predecessor_id == "abc123"
        assert restored.dependencies[0].lag_days == 2

    def test_milestone(self):
        task = Task(name="Milestone", is_milestone=True, duration_days=0)
        assert task.is_milestone

    def test_color_cycle(self):
        c0 = TaskColor.cycle(0)
        c1 = TaskColor.cycle(1)
        assert c0 != c1
        # Wraps around
        c_wrap = TaskColor.cycle(len(TaskColor))
        assert c_wrap == c0


class TestDependency:
    def test_create(self):
        dep = Dependency("task1", DependencyType.FINISH_TO_START, lag_days=1)
        assert dep.predecessor_id == "task1"
        assert dep.dependency_type == DependencyType.FINISH_TO_START
        assert dep.lag_days == 1

    def test_serialization(self):
        dep = Dependency("task1", DependencyType.START_TO_START, lag_days=3)
        data = dep.to_dict()
        restored = Dependency.from_dict(data)
        assert restored.predecessor_id == "task1"
        assert restored.dependency_type == DependencyType.START_TO_START
        assert restored.lag_days == 3


class TestProject:
    def test_create_project(self):
        project = Project(name="Test Project", start_date=date(2026, 1, 1))
        assert project.name == "Test Project"
        assert len(project.tasks) == 0

    def test_add_task_auto_wbs(self):
        project = Project(start_date=date(2026, 1, 1))
        t1 = project.add_task(Task(name="First"))
        assert t1.wbs == "1"

        t2 = project.add_task(Task(name="Second"))
        assert t2.wbs == "2"

    def test_add_task_child_wbs(self):
        project = Project(start_date=date(2026, 1, 1))
        project.add_task(Task(name="Parent", wbs="1"))
        child = project.add_task(Task(name="Child", parent_wbs="1"))
        assert child.wbs == "1.1"

    def test_get_children(self):
        project = Project(start_date=date(2026, 1, 1))
        project.add_task(Task(name="P1", wbs="1"))
        project.add_task(Task(name="C1", wbs="1.1"))
        project.add_task(Task(name="C2", wbs="1.2"))
        project.add_task(Task(name="GC1", wbs="1.1.1"))

        children = project.get_children("1")
        assert len(children) == 2
        assert children[0].wbs == "1.1"
        assert children[1].wbs == "1.2"

    def test_sorted_tasks(self):
        project = Project()
        project.tasks = [
            Task(name="B", wbs="2"),
            Task(name="A", wbs="1"),
            Task(name="C", wbs="1.1"),
        ]
        sorted_tasks = project.sorted_tasks()
        assert [t.wbs for t in sorted_tasks] == ["1", "1.1", "2"]

    def test_remove_task(self):
        project = Project(start_date=date(2026, 1, 1))
        t1 = project.add_task(Task(name="Task 1"))
        t2 = project.add_task(Task(
            name="Task 2",
            dependencies=[Dependency(t1.id)],
        ))
        project.remove_task(t1.id)
        assert len(project.tasks) == 1
        assert len(project.tasks[0].dependencies) == 0

    def test_save_and_load(self):
        project = Project(name="Save Test", start_date=date(2026, 1, 1))
        project.add_task(Task(name="Task 1", wbs="1", duration_days=3))
        project.add_task(Task(name="Task 2", wbs="2", duration_days=5))

        with tempfile.NamedTemporaryFile(suffix=".gw.json", delete=False) as f:
            path = f.name

        try:
            project.save(path)
            loaded = Project.load(path)
            assert loaded.name == "Save Test"
            assert len(loaded.tasks) == 2
            assert loaded.tasks[0].name == "Task 1"
        finally:
            Path(path).unlink(missing_ok=True)

    def test_update_blocked_status(self):
        project = Project(start_date=date(2026, 1, 1))
        t1 = project.add_task(Task(name="Predecessor"))
        t2 = project.add_task(Task(
            name="Successor",
            dependencies=[Dependency(t1.id, DependencyType.FINISH_TO_START)],
        ))

        project.update_blocked_status()
        assert t2.status == TaskStatus.BLOCKED

        t1.status = TaskStatus.COMPLETED
        project.update_blocked_status()
        assert t2.status == TaskStatus.NOT_STARTED

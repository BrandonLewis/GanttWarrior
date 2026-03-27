"""Tests for grid editor operations."""
from datetime import date
import pytest
from ganttwarrior.grid_editor import Clipboard, GridEditor
from ganttwarrior.models import Dependency, DependencyType, Project, Task


def _make_project() -> Project:
    project = Project(name="Test", start_date=date(2026, 3, 23))
    t1 = Task(id="t1", name="Task A", wbs="1")
    t1.work_days = {date(2026, 3, 23), date(2026, 3, 24), date(2026, 3, 25), date(2026, 3, 26), date(2026, 3, 27)}
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
        task.work_days.discard(date(2026, 3, 25))
        editor = GridEditor(project)
        editor.copy(task, date(2026, 3, 23), date(2026, 3, 27))
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
        task_a, task_b = editor.split(task, date(2026, 3, 25))
        assert task_a.work_days == {date(2026, 3, 23), date(2026, 3, 24)}
        assert task_b.work_days == {date(2026, 3, 25), date(2026, 3, 26), date(2026, 3, 27)}
        assert task_b.name == "Task A (continued)"
        assert len(task_b.dependencies) == 1
        assert task_b.dependencies[0].predecessor_id == task_a.id

    def test_merge(self):
        project = _make_project()
        editor = GridEditor(project)
        t1 = project.get_task("t1")
        t2 = project.get_task("t2")
        expected_days = t1.work_days | t2.work_days
        merged = editor.merge(t1, t2)
        assert merged.work_days == expected_days
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

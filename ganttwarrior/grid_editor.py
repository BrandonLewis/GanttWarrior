"""Grid editor: fill, erase, clipboard, split, merge operations for the Gantt grid.

Pure logic module with no TUI dependencies.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from ganttwarrior.models import Dependency, DependencyType, Project, Task
from ganttwarrior.undo import UndoEntry, UndoStack


@dataclass
class Clipboard:
    """Stores a copied work-day pattern as relative offsets."""

    offsets: list[int]  # Relative day offsets that have work
    source_task_name: str


class GridEditor:
    """Encapsulates all editing operations for the Gantt grid.

    Owns an UndoStack and a clipboard. Pure logic, no TUI dependencies.
    """

    def __init__(self, project: Project) -> None:
        self.project = project
        self.undo_stack = UndoStack()
        self.clipboard: Optional[Clipboard] = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _snapshot(self, task: Task) -> frozenset[date]:
        """Snapshot a task's work_days as an immutable frozenset."""
        return frozenset(task.work_days)

    def _push_undo(
        self,
        task_ids: list[str],
        before: dict[str, frozenset[date]],
        after: dict[str, frozenset[date]],
        description: str,
    ) -> None:
        """Create and push an UndoEntry onto the undo stack."""
        entry = UndoEntry(
            task_ids=task_ids,
            before=before,
            after=after,
            description=description,
        )
        self.undo_stack.push(entry)

    def _apply_snapshot(self, snapshots: dict[str, frozenset[date]]) -> None:
        """Restore work_days from a snapshot dict for each task_id."""
        for task_id, days in snapshots.items():
            task = self.project.get_task(task_id)
            if task is not None:
                task.work_days = set(days)

    # ------------------------------------------------------------------
    # Fill / Erase
    # ------------------------------------------------------------------

    def fill(self, task: Task, d: date) -> None:
        """Add date to task.work_days. No-op if already filled."""
        if d in task.work_days:
            return
        before = {task.id: self._snapshot(task)}
        task.work_days.add(d)
        task.manually_edited = True
        after = {task.id: self._snapshot(task)}
        self._push_undo([task.id], before, after, f"Fill {d} on {task.name}")

    def fill_range(self, task: Task, start: date, end: date) -> None:
        """Fill all dates in [start, end] inclusive. One undo entry."""
        before = {task.id: self._snapshot(task)}
        current = start
        while current <= end:
            task.work_days.add(current)
            current += timedelta(days=1)
        task.manually_edited = True
        after = {task.id: self._snapshot(task)}
        self._push_undo(
            [task.id], before, after, f"Fill range {start}..{end} on {task.name}"
        )

    def erase(self, task: Task, d: date) -> None:
        """Remove date from task.work_days. No-op if not filled."""
        if d not in task.work_days:
            return
        before = {task.id: self._snapshot(task)}
        task.work_days.discard(d)
        task.manually_edited = True
        after = {task.id: self._snapshot(task)}
        self._push_undo([task.id], before, after, f"Erase {d} on {task.name}")

    def erase_range(self, task: Task, start: date, end: date) -> None:
        """Erase all dates in [start, end] inclusive. One undo entry."""
        before = {task.id: self._snapshot(task)}
        current = start
        while current <= end:
            task.work_days.discard(current)
            current += timedelta(days=1)
        task.manually_edited = True
        after = {task.id: self._snapshot(task)}
        self._push_undo(
            [task.id], before, after, f"Erase range {start}..{end} on {task.name}"
        )

    # ------------------------------------------------------------------
    # Clipboard operations
    # ------------------------------------------------------------------

    def copy(self, task: Task, start: date, end: date) -> None:
        """Copy work day pattern as relative offsets from start.

        E.g., if Mon, Tue, Thu are filled in Mon-Fri range, offsets=[0,1,3].
        """
        offsets: list[int] = []
        current = start
        while current <= end:
            if current in task.work_days:
                offsets.append((current - start).days)
            current += timedelta(days=1)
        self.clipboard = Clipboard(offsets=offsets, source_task_name=task.name)

    def cut(self, task: Task, start: date, end: date) -> None:
        """Copy then erase_range."""
        self.copy(task, start, end)
        self.erase_range(task, start, end)

    def paste(self, task: Task, cursor_date: date) -> None:
        """Apply clipboard offsets starting at cursor_date onto task."""
        if self.clipboard is None:
            return
        before = {task.id: self._snapshot(task)}
        for offset in self.clipboard.offsets:
            task.work_days.add(cursor_date + timedelta(days=offset))
        task.manually_edited = True
        after = {task.id: self._snapshot(task)}
        self._push_undo(
            [task.id], before, after, f"Paste onto {task.name} at {cursor_date}"
        )

    def paste_as_new_task(self, cursor_date: date, after_task: Task) -> Task:
        """Create new task from clipboard, insert after after_task in project.tasks."""
        if self.clipboard is None:
            raise ValueError("Clipboard is empty")

        work_days: set[date] = set()
        for offset in self.clipboard.offsets:
            work_days.add(cursor_date + timedelta(days=offset))

        new_task = Task(
            id=str(uuid.uuid4())[:8],
            name=f"Task (from {self.clipboard.source_task_name})",
            wbs="",
            work_days=work_days,
            manually_edited=True,
        )

        # Insert after after_task in project.tasks
        idx = self.project.tasks.index(after_task)
        self.project.tasks.insert(idx + 1, new_task)

        return new_task

    # ------------------------------------------------------------------
    # Split / Merge / Duplicate
    # ------------------------------------------------------------------

    def split(self, task: Task, cursor_date: date) -> tuple[Task, Task]:
        """Split task at cursor_date.

        task_a gets work_days before cursor.
        task_b gets cursor_date and after.
        task_b named "{name} (continued)" with FS dependency on task_a.
        task_b inserted after task_a in project.
        """
        days_before = {d for d in task.work_days if d < cursor_date}
        days_after = {d for d in task.work_days if d >= cursor_date}

        # task_a is the original task, modified in place
        task_a = task
        before_a = {task_a.id: self._snapshot(task_a)}
        task_a.work_days = days_before
        task_a.manually_edited = True

        # task_b is a new task
        task_b = Task(
            id=str(uuid.uuid4())[:8],
            name=f"{task.name} (continued)",
            wbs="",
            work_days=days_after,
            manually_edited=True,
            color=task.color,
            dependencies=[
                Dependency(
                    predecessor_id=task_a.id,
                    dependency_type=DependencyType.FINISH_TO_START,
                )
            ],
        )

        # Insert task_b after task_a
        idx = self.project.tasks.index(task_a)
        self.project.tasks.insert(idx + 1, task_b)

        after_a = {task_a.id: self._snapshot(task_a)}
        self._push_undo(
            [task_a.id],
            before_a,
            after_a,
            f"Split {task.name} at {cursor_date}",
        )

        return task_a, task_b

    def merge(self, task_a: Task, task_b: Task) -> Task:
        """Union work_days. Keep task_a's name/color/deps. Absorb task_b's deps.

        Skip self-referencing deps. Remove task_b from project.
        """
        before = {
            task_a.id: self._snapshot(task_a),
            task_b.id: self._snapshot(task_b),
        }

        # Union work days
        task_a.work_days = task_a.work_days | task_b.work_days
        task_a.manually_edited = True

        # Absorb task_b's dependencies, skipping self-references
        existing_pred_ids = {d.predecessor_id for d in task_a.dependencies}
        for dep in task_b.dependencies:
            if dep.predecessor_id == task_a.id:
                continue  # Skip self-referencing
            if dep.predecessor_id not in existing_pred_ids:
                task_a.dependencies.append(dep)
                existing_pred_ids.add(dep.predecessor_id)

        # Remove task_b from project
        self.project.tasks = [t for t in self.project.tasks if t.id != task_b.id]

        # Update any dependencies pointing to task_b to point to task_a
        for t in self.project.tasks:
            for dep in t.dependencies:
                if dep.predecessor_id == task_b.id:
                    dep.predecessor_id = task_a.id

        after = {task_a.id: self._snapshot(task_a)}
        self._push_undo(
            [task_a.id, task_b.id],
            before,
            after,
            f"Merge {task_b.name} into {task_a.name}",
        )

        return task_a

    def duplicate(self, task: Task) -> Task:
        """Copy task with new ID, name "{name} (copy)", same work_days. Insert after original."""
        dup = Task(
            id=str(uuid.uuid4())[:8],
            name=f"{task.name} (copy)",
            wbs="",
            work_days=set(task.work_days),
            manually_edited=task.manually_edited,
            color=task.color,
            description=task.description,
            priority=task.priority,
            assigned_to=task.assigned_to,
        )

        idx = self.project.tasks.index(task)
        self.project.tasks.insert(idx + 1, dup)

        return dup

    # ------------------------------------------------------------------
    # Undo / Redo
    # ------------------------------------------------------------------

    def undo(self) -> bool:
        """Pop from undo stack, restore work_days from before snapshots."""
        entry = self.undo_stack.undo()
        if entry is None:
            return False
        self._apply_snapshot(entry.before)
        return True

    def redo(self) -> bool:
        """Pop from redo stack, restore work_days from after snapshots."""
        entry = self.undo_stack.redo()
        if entry is None:
            return False
        self._apply_snapshot(entry.after)
        return True

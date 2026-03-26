"""Data models for GanttWarrior: Tasks, Projects, WBS, and dependencies."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional


class TaskStatus(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class TaskColor(str, Enum):
    """Predefined task colors for visual differentiation."""
    RED = "red"
    GREEN = "green"
    BLUE = "blue"
    YELLOW = "yellow"
    MAGENTA = "magenta"
    CYAN = "cyan"
    ORANGE = "orange"
    PURPLE = "purple"
    WHITE = "white"

    @classmethod
    def cycle(cls, index: int) -> "TaskColor":
        colors = list(cls)
        return colors[index % len(colors)]


class DependencyType(str, Enum):
    FINISH_TO_START = "FS"   # Predecessor must finish before successor starts
    START_TO_START = "SS"    # Both start at the same time
    FINISH_TO_FINISH = "FF"  # Both finish at the same time
    START_TO_FINISH = "SF"   # Predecessor starts before successor finishes


@dataclass
class Dependency:
    predecessor_id: str
    dependency_type: DependencyType = DependencyType.FINISH_TO_START
    lag_days: int = 0

    def to_dict(self) -> dict:
        return {
            "predecessor_id": self.predecessor_id,
            "dependency_type": self.dependency_type.value,
            "lag_days": self.lag_days,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Dependency":
        return cls(
            predecessor_id=data["predecessor_id"],
            dependency_type=DependencyType(data["dependency_type"]),
            lag_days=data.get("lag_days", 0),
        )


@dataclass
class Task:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    wbs: str = ""  # e.g. "1.2.3"
    description: str = ""
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    duration_days: int = 1
    status: TaskStatus = TaskStatus.NOT_STARTED
    color: TaskColor = TaskColor.BLUE
    progress: float = 0.0  # 0.0 to 1.0
    dependencies: list[Dependency] = field(default_factory=list)
    assigned_to: str = ""
    priority: int = 0  # Higher = more important
    is_milestone: bool = False
    parent_wbs: str = ""  # WBS of the parent summary task

    # Computed by scheduler
    early_start: Optional[date] = None
    early_finish: Optional[date] = None
    late_start: Optional[date] = None
    late_finish: Optional[date] = None
    total_float: int = 0
    is_critical: bool = False

    @property
    def wbs_parts(self) -> list[int]:
        if not self.wbs:
            return []
        try:
            return [int(p) for p in self.wbs.split(".")]
        except ValueError:
            # Fallback for invalid WBS segments so core flows don't crash.
            # This preserves behavior for valid numeric WBS strings while
            # tolerating user-entered non-numeric values.
            return []

    @property
    def wbs_level(self) -> int:
        return len(self.wbs_parts)

    @property
    def wbs_parent(self) -> str:
        parts = self.wbs_parts
        if len(parts) <= 1:
            return ""
        return ".".join(str(p) for p in parts[:-1])

    @property
    def is_summary(self) -> bool:
        return self.parent_wbs == "" and self.wbs_level == 1

    def compute_end_date(self) -> None:
        # Compute end_date based on start_date and duration_days.
        # Treat 0-day duration (milestones) as ending on the start_date.
        if self.start_date is not None and self.duration_days is not None:
            if self.duration_days <= 0:
                # Milestone or explicitly zero/negative duration: same-day end.
                self.end_date = self.start_date
            else:
                self.end_date = self.start_date + timedelta(days=self.duration_days - 1)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "wbs": self.wbs,
            "description": self.description,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "duration_days": self.duration_days,
            "status": self.status.value,
            "color": self.color.value,
            "progress": self.progress,
            "dependencies": [d.to_dict() for d in self.dependencies],
            "assigned_to": self.assigned_to,
            "priority": self.priority,
            "is_milestone": self.is_milestone,
            "parent_wbs": self.parent_wbs,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        task = cls(
            id=data["id"],
            name=data["name"],
            wbs=data.get("wbs", ""),
            description=data.get("description", ""),
            start_date=date.fromisoformat(data["start_date"]) if data.get("start_date") else None,
            end_date=date.fromisoformat(data["end_date"]) if data.get("end_date") else None,
            duration_days=data.get("duration_days", 1),
            status=TaskStatus(data.get("status", "not_started")),
            color=TaskColor(data.get("color", "blue")),
            progress=data.get("progress", 0.0),
            dependencies=[Dependency.from_dict(d) for d in data.get("dependencies", [])],
            assigned_to=data.get("assigned_to", ""),
            priority=data.get("priority", 0),
            is_milestone=data.get("is_milestone", False),
            parent_wbs=data.get("parent_wbs", ""),
        )
        return task


@dataclass
class Project:
    name: str = "Untitled Project"
    description: str = ""
    tasks: list[Task] = field(default_factory=list)
    start_date: Optional[date] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    file_path: Optional[str] = None

    def get_task(self, task_id: str) -> Optional[Task]:
        for t in self.tasks:
            if t.id == task_id:
                return t
        return None

    def get_task_by_wbs(self, wbs: str) -> Optional[Task]:
        for t in self.tasks:
            if t.wbs == wbs:
                return t
        return None

    def get_children(self, parent_wbs: str) -> list[Task]:
        """Get direct children of a WBS node."""
        parent_level = len(parent_wbs.split(".")) if parent_wbs else 0
        result = []
        for t in self.tasks:
            if parent_wbs and t.wbs.startswith(parent_wbs + "."):
                if t.wbs_level == parent_level + 1:
                    result.append(t)
            elif not parent_wbs and t.wbs_level == 1:
                result.append(t)
        return sorted(result, key=lambda x: x.wbs_parts)

    def get_all_descendants(self, parent_wbs: str) -> list[Task]:
        """Get all descendants of a WBS node."""
        return [t for t in self.tasks if t.wbs.startswith(parent_wbs + ".")]

    def sorted_tasks(self) -> list[Task]:
        """Return tasks sorted by WBS notation."""
        return sorted(self.tasks, key=lambda t: t.wbs_parts if t.wbs_parts else [999])

    def next_wbs(self, parent_wbs: str = "") -> str:
        """Generate the next available WBS number under a parent."""
        children = self.get_children(parent_wbs)
        if not children:
            return f"{parent_wbs}.1" if parent_wbs else "1"
        last = children[-1].wbs_parts[-1]
        if parent_wbs:
            return f"{parent_wbs}.{last + 1}"
        return str(last + 1)

    def add_task(self, task: Task) -> Task:
        if not task.wbs:
            task.wbs = self.next_wbs(task.parent_wbs)
        if not task.start_date:
            task.start_date = self.start_date or date.today()
        task.compute_end_date()
        self.tasks.append(task)
        return task

    def remove_task(self, task_id: str) -> None:
        self.tasks = [t for t in self.tasks if t.id != task_id]
        # Remove dependencies referencing the deleted task
        for t in self.tasks:
            t.dependencies = [d for d in t.dependencies if d.predecessor_id != task_id]

    def update_blocked_status(self) -> None:
        """Mark tasks as blocked if their dependencies aren't complete.

        Blocking rules by dependency type:
        - FS (Finish-to-Start): predecessor must be COMPLETED before successor can start.
        - SS (Start-to-Start): predecessor must have started (IN_PROGRESS or COMPLETED).
        - FF (Finish-to-Finish): predecessor must be COMPLETED before successor can finish.
        - SF (Start-to-Finish): predecessor must have started (IN_PROGRESS or COMPLETED).
        """
        for task in self.tasks:
            if task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
                continue
            blocked = False
            for dep in task.dependencies:
                pred = self.get_task(dep.predecessor_id)
                if not pred:
                    continue
                if dep.dependency_type in (DependencyType.FINISH_TO_START, DependencyType.FINISH_TO_FINISH):
                    if pred.status != TaskStatus.COMPLETED:
                        blocked = True
                        break
                elif dep.dependency_type in (DependencyType.START_TO_START, DependencyType.START_TO_FINISH):
                    if pred.status not in (TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED):
                        blocked = True
                        break
            if blocked and task.status != TaskStatus.IN_PROGRESS:
                task.status = TaskStatus.BLOCKED
            elif task.status == TaskStatus.BLOCKED and not blocked:
                task.status = TaskStatus.NOT_STARTED

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "tasks": [t.to_dict() for t in self.tasks],
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Project":
        return cls(
            name=data.get("name", "Untitled Project"),
            description=data.get("description", ""),
            tasks=[Task.from_dict(t) for t in data.get("tasks", [])],
            start_date=date.fromisoformat(data["start_date"]) if data.get("start_date") else None,
            created_at=data.get("created_at", datetime.now().isoformat()),
        )

    def save(self, path: Optional[str] = None) -> str:
        save_path = path or self.file_path
        if not save_path:
            safe_name = self.name.replace(" ", "_").lower()
            save_path = f"{safe_name}.gw.json"
        self.file_path = save_path
        Path(save_path).write_text(json.dumps(self.to_dict(), indent=2))
        return save_path

    @classmethod
    def load(cls, path: str) -> "Project":
        data = json.loads(Path(path).read_text())
        project = cls.from_dict(data)
        project.file_path = path
        return project

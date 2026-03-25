"""Kanban board TUI view using Textual."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static, Label

from ..models import Project, Task, TaskColor, TaskStatus
from .gantt import COLOR_MAP, STATUS_SYMBOLS


KANBAN_COLUMNS = [
    ("Not Started", TaskStatus.NOT_STARTED),
    ("Blocked", TaskStatus.BLOCKED),
    ("In Progress", TaskStatus.IN_PROGRESS),
    ("Completed", TaskStatus.COMPLETED),
]

COLUMN_STYLES = {
    TaskStatus.NOT_STARTED: "white on rgb(40,40,50)",
    TaskStatus.BLOCKED: "white on rgb(60,30,30)",
    TaskStatus.IN_PROGRESS: "white on rgb(30,40,60)",
    TaskStatus.COMPLETED: "white on rgb(30,60,30)",
}


class KanbanCard(Widget):
    """A single task card on the Kanban board."""

    DEFAULT_CSS = """
    KanbanCard {
        height: auto;
        min-height: 3;
        width: 1fr;
        margin: 0 1 1 1;
        padding: 0 1;
        border: round $secondary;
    }
    KanbanCard:hover {
        border: round $accent;
    }
    KanbanCard.critical {
        border: round red;
    }
    """

    class Selected(Message):
        def __init__(self, task: Task) -> None:
            super().__init__()
            self.task = task

    def __init__(self, task: Task, **kwargs):
        super().__init__(**kwargs)
        self.task = task
        if task.is_critical:
            self.add_class("critical")

    def render(self) -> Text:
        task = self.task
        color = COLOR_MAP.get(task.color, "white")
        text = Text()

        # Title line with color indicator
        text.append("● ", style=color)
        text.append(f"{task.wbs} ", style="dim")
        text.append(task.name, style="bold")
        text.append("\n")

        # Details line
        if task.assigned_to:
            text.append(f"  👤 {task.assigned_to}", style="dim")
        if task.duration_days:
            text.append(f"  ⏱ {task.duration_days}d", style="dim")
        if task.progress > 0:
            pct = int(task.progress * 100)
            text.append(f"  {pct}%", style="green" if pct == 100 else "yellow")
        if task.is_critical:
            text.append("  ⚠ CRITICAL", style="bold red")

        return text

    def on_click(self) -> None:
        self.post_message(self.Selected(self.task))


class KanbanColumn(Vertical):
    """A column in the Kanban board."""

    DEFAULT_CSS = """
    KanbanColumn {
        width: 1fr;
        height: 1fr;
        margin: 0 1;
        border: solid $primary-background;
    }
    """

    def __init__(self, title: str, status: TaskStatus, tasks: list[Task], **kwargs):
        super().__init__(**kwargs)
        self.column_title = title
        self.status = status
        self.column_tasks = tasks

    def compose(self) -> ComposeResult:
        # Column header
        count = len(self.column_tasks)
        header_text = f" {self.column_title} ({count}) "
        yield Static(header_text, classes="kanban-column-header")
        yield Static("─" * 30)

        container = ScrollableContainer()
        with container:
            for task in self.column_tasks:
                yield KanbanCard(task)
        yield container


class KanbanBoard(Horizontal):
    """The full Kanban board widget."""

    DEFAULT_CSS = """
    KanbanBoard {
        height: 1fr;
        width: 1fr;
    }
    """

    def __init__(self, project: Project, **kwargs):
        super().__init__(**kwargs)
        self.project = project

    def compose(self) -> ComposeResult:
        for title, status in KANBAN_COLUMNS:
            tasks = [t for t in self.project.sorted_tasks() if t.status == status]
            yield KanbanColumn(title, status, tasks)

    def refresh_board(self) -> None:
        """Rebuild the board after data changes."""
        self.remove_children()
        for title, status in KANBAN_COLUMNS:
            tasks = [t for t in self.project.sorted_tasks() if t.status == status]
            self.mount(KanbanColumn(title, status, tasks))

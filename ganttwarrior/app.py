"""Main Textual TUI application for GanttWarrior."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    OptionList,
    Select,
    Static,
    TabbedContent,
    TabPane,
)
from textual.widgets.option_list import Option

from .models import (
    Dependency,
    DependencyType,
    Project,
    Task,
    TaskColor,
    TaskStatus,
)
from .scheduler import Scheduler, SchedulerError
from .views.gantt import GanttChart
from .views.kanban import KanbanBoard

SPLASH_ART = r"""
[dim white]
                          ___
                         /   \
                        |  o  |
                        | --- |
                         \_^_/
                      .-'/ | \`-.
                     /  /  |  \  \
                    |  |  _|_  |  |
                    |  | (___) |  |
                     \  \ | | /  /
                      '-.|_|_|.-'
                     _/| \___/ |\_
                    / /|  |||  |\ \
                   | | |  |||  | | |
                   | | |  |||  | | |
                    \ \| ,===. |/ /
                     '-(  / \  )-'
                        | | | |
                        | | | |
                       _| | | |_
                      (___) (___)
[/dim white]
[bold white]               *** GANTTWARRIOR ***[/bold white]

[dim italic]  You stand at the threshold of a vast project.
  Timelines stretch endlessly before you. Tasks loom
  like ancient pillars in the mist. Dependencies coil
  in the darkness. You grip your Gantt chart tightly
  and step forward...[/dim italic]

[bold dim]           >>> Press any key to begin <<<[/bold dim]
"""


class SplashScreen(ModalScreen):
    """Intro splash screen - a gaunt warrior awaits."""

    DEFAULT_CSS = """
    SplashScreen {
        align: center middle;
        background: $background 90%;
    }
    #splash-box {
        width: 60;
        height: auto;
        padding: 1 2;
        border: heavy $primary;
        background: $surface;
        content-align: center middle;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(SPLASH_ART, id="splash-box")

    def on_key(self, event) -> None:
        event.stop()
        self.dismiss()

    def on_click(self, event) -> None:
        event.stop()
        self.dismiss()


class TaskEditScreen(ModalScreen[Optional[Task]]):
    """Modal dialog for adding/editing a task."""

    DEFAULT_CSS = """
    TaskEditScreen {
        align: center middle;
    }
    #task-edit-dialog {
        width: 70;
        height: 90%;
        padding: 1 2;
        border: thick $accent;
        background: $surface;
    }
    #task-edit-form {
        height: 1fr;
    }
    #task-edit-dialog Label {
        margin: 1 0 0 0;
    }
    #task-edit-dialog Input {
        margin: 0 0 0 0;
    }
    #task-edit-buttons {
        margin-top: 1;
        height: auto;
        min-height: 3;
        align: center middle;
        dock: bottom;
    }
    #task-edit-buttons Button {
        margin: 0 2;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, task: Optional[Task] = None, project: Optional[Project] = None):
        super().__init__()
        self.gantt_task = task
        self.project = project
        self.is_edit = task is not None

    def compose(self) -> ComposeResult:
        task = self.gantt_task or Task()
        title = "Edit Task" if self.is_edit else "Add Task"

        with Vertical(id="task-edit-dialog"):
            yield Label(f"[bold]{title}[/bold]")

            with ScrollableContainer(id="task-edit-form"):
                yield Label("Name:")
                yield Input(value=task.name, id="task-name", placeholder="Task name")

                yield Label("WBS (e.g. 1.2.3):")
                yield Input(value=task.wbs, id="task-wbs", placeholder="Auto-assigned if empty")

                yield Label("Duration (days):")
                yield Input(value=str(task.duration_days), id="task-duration", placeholder="1")

                yield Label("Start Date (YYYY-MM-DD):")
                yield Input(
                    value=task.start_date.isoformat() if task.start_date else "",
                    id="task-start",
                    placeholder="YYYY-MM-DD",
                )

                yield Label("Assigned To:")
                yield Input(value=task.assigned_to, id="task-assigned", placeholder="Person name")

                yield Label("Description:")
                yield Input(value=task.description, id="task-desc", placeholder="Task description")

                yield Label("Color:")
                yield Select(
                    [(c.value, c.value) for c in TaskColor],
                    value=task.color.value,
                    id="task-color",
                )

                yield Label("Status:")
                yield Select(
                    [(s.value, s.value) for s in TaskStatus],
                    value=task.status.value,
                    id="task-status",
                )

                yield Label("Priority (0-9):")
                yield Input(value=str(task.priority), id="task-priority", placeholder="0")

            with Horizontal(id="task-edit-buttons"):
                yield Button("Save", variant="primary", id="save-btn")
                yield Button("Cancel", variant="default", id="cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            self._save_task()
        elif event.button.id == "cancel-btn":
            self.dismiss(None)

    def _save_task(self) -> None:
        name = self.query_one("#task-name", Input).value.strip()
        if not name:
            self.notify("Task name is required", severity="error")
            return

        task = self.gantt_task or Task()
        task.name = name
        task.wbs = self.query_one("#task-wbs", Input).value.strip()
        task.description = self.query_one("#task-desc", Input).value.strip()
        task.assigned_to = self.query_one("#task-assigned", Input).value.strip()

        duration_str = self.query_one("#task-duration", Input).value.strip()
        task.duration_days = int(duration_str) if duration_str.isdigit() else 1

        start_str = self.query_one("#task-start", Input).value.strip()
        if start_str:
            try:
                task.start_date = date.fromisoformat(start_str)
            except ValueError:
                self.notify("Invalid date format. Use YYYY-MM-DD", severity="error")
                return

        color_val = self.query_one("#task-color", Select).value
        if color_val and color_val != Select.BLANK:
            task.color = TaskColor(color_val)

        status_val = self.query_one("#task-status", Select).value
        if status_val and status_val != Select.BLANK:
            task.status = TaskStatus(status_val)

        priority_str = self.query_one("#task-priority", Input).value.strip()
        task.priority = int(priority_str) if priority_str.isdigit() else 0

        self.dismiss(task)

    def action_cancel(self) -> None:
        self.dismiss(None)


class DependencyScreen(ModalScreen[Optional[Dependency]]):
    """Modal for adding a dependency to a task."""

    DEFAULT_CSS = """
    DependencyScreen {
        align: center middle;
    }
    #dep-dialog {
        width: 60;
        height: auto;
        padding: 1 2;
        border: thick $accent;
        background: $surface;
    }
    #dep-buttons {
        margin-top: 1;
        height: 3;
        align: center middle;
    }
    #dep-buttons Button {
        margin: 0 2;
    }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, project: Project, current_task_id: str):
        super().__init__()
        self.project = project
        self.current_task_id = current_task_id

    def compose(self) -> ComposeResult:
        with Vertical(id="dep-dialog"):
            yield Label("[bold]Add Dependency[/bold]")

            yield Label("Predecessor Task:")
            options = [
                (f"{t.wbs} {t.name}", t.id)
                for t in self.project.sorted_tasks()
                if t.id != self.current_task_id
            ]
            yield Select(options, id="dep-predecessor")

            yield Label("Type:")
            yield Select(
                [(dt.value, dt.value) for dt in DependencyType],
                value=DependencyType.FINISH_TO_START.value,
                id="dep-type",
            )

            yield Label("Lag (days):")
            yield Input(value="0", id="dep-lag", placeholder="0")

            with Horizontal(id="dep-buttons"):
                yield Button("Add", variant="primary", id="add-dep-btn")
                yield Button("Cancel", variant="default", id="cancel-dep-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "add-dep-btn":
            pred_val = self.query_one("#dep-predecessor", Select).value
            if not pred_val or pred_val == Select.BLANK:
                self.notify("Select a predecessor task", severity="error")
                return

            dep_type_val = self.query_one("#dep-type", Select).value
            lag_str = self.query_one("#dep-lag", Input).value.strip()

            dep = Dependency(
                predecessor_id=str(pred_val),
                dependency_type=DependencyType(dep_type_val),
                lag_days=int(lag_str) if lag_str.isdigit() else 0,
            )
            self.dismiss(dep)
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ExportScreen(ModalScreen[None]):
    """Modal for export options."""

    DEFAULT_CSS = """
    ExportScreen {
        align: center middle;
    }
    #export-dialog {
        width: 50;
        height: auto;
        padding: 1 2;
        border: thick $accent;
        background: $surface;
    }
    #export-buttons {
        margin-top: 1;
        height: auto;
    }
    #export-buttons Button {
        width: 100%;
        margin: 0 0 1 0;
    }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, project: Project):
        super().__init__()
        self.project = project

    def compose(self) -> ComposeResult:
        with Vertical(id="export-dialog"):
            yield Label("[bold]Export Project[/bold]")
            yield Label("File path:")
            yield Input(
                value=self.project.name.replace(" ", "_").lower(),
                id="export-path",
                placeholder="filename (without extension)",
            )

            with Vertical(id="export-buttons"):
                yield Button("Export to PDF", variant="primary", id="export-pdf")
                yield Button("Export to Excel", variant="primary", id="export-excel")
                yield Button("Export to iCal", variant="primary", id="export-ical")
                yield Button("Print to Terminal", variant="warning", id="export-print")
                yield Button("Cancel", variant="default", id="export-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        base = self.query_one("#export-path", Input).value.strip() or "project"

        if event.button.id == "export-pdf":
            from .export import export_pdf
            try:
                path = export_pdf(self.project, f"{base}.pdf")
                self.notify(f"Exported to {path}", severity="information")
            except Exception as e:
                self.notify(f"PDF export failed: {e}", severity="error")
            self.dismiss(None)

        elif event.button.id == "export-excel":
            from .export import export_excel
            try:
                path = export_excel(self.project, f"{base}.xlsx")
                self.notify(f"Exported to {path}", severity="information")
            except Exception as e:
                self.notify(f"Excel export failed: {e}", severity="error")
            self.dismiss(None)

        elif event.button.id == "export-ical":
            from .calendar_io import export_ical
            try:
                path = export_ical(self.project, f"{base}.ics")
                self.notify(f"Exported to {path}", severity="information")
            except Exception as e:
                self.notify(f"iCal export failed: {e}", severity="error")
            self.dismiss(None)

        elif event.button.id == "export-print":
            from .export import print_project
            print_project(self.project)
            self.notify("Printed to terminal", severity="information")
            self.dismiss(None)

        elif event.button.id == "export-cancel":
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ImportScreen(ModalScreen[Optional[str]]):
    """Modal for importing a calendar file."""

    DEFAULT_CSS = """
    ImportScreen {
        align: center middle;
    }
    #import-dialog {
        width: 50;
        height: auto;
        padding: 1 2;
        border: thick $accent;
        background: $surface;
    }
    #import-buttons {
        margin-top: 1;
        height: 3;
        align: center middle;
    }
    #import-buttons Button {
        margin: 0 2;
    }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="import-dialog"):
            yield Label("[bold]Import Calendar (.ics)[/bold]")
            yield Label("File path:")
            yield Input(id="import-path", placeholder="/path/to/file.ics")

            with Horizontal(id="import-buttons"):
                yield Button("Import", variant="primary", id="import-btn")
                yield Button("Cancel", variant="default", id="import-cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "import-btn":
            path = self.query_one("#import-path", Input).value.strip()
            if path and Path(path).exists():
                self.dismiss(path)
            else:
                self.notify("File not found", severity="error")
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class StatusBar(Static):
    """Bottom status bar showing project info."""

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        dock: bottom;
        background: $primary;
        color: $text;
        padding: 0 1;
    }
    """

    def update_project(self, project: Project) -> None:
        total = len(project.tasks)
        completed = sum(1 for t in project.tasks if t.status == TaskStatus.COMPLETED)
        critical = sum(1 for t in project.tasks if t.is_critical)
        blocked = sum(1 for t in project.tasks if t.status == TaskStatus.BLOCKED)
        self.update(
            f" {project.name} │ Tasks: {total} │ "
            f"Done: {completed} │ Critical: {critical} │ Blocked: {blocked}"
        )


class GanttWarriorApp(App):
    """GanttWarrior - TUI Gantt Chart & Task Scheduler."""

    TITLE = "GanttWarrior"
    SUB_TITLE = "Gantt Chart & Task Scheduler"

    CSS = """
    Screen {
        layout: vertical;
    }
    #main-content {
        height: 1fr;
    }
    .gantt-separator {
        height: 1;
        color: $text-muted;
    }
    .kanban-column-header {
        text-align: center;
        text-style: bold;
        background: $primary;
        color: $text;
        height: 1;
    }
    #task-info-panel {
        height: 8;
        dock: bottom;
        border-top: solid $primary;
        padding: 0 1;
        background: $surface;
    }
    """

    BINDINGS = [
        Binding("a", "add_task", "Add Task"),
        Binding("e", "edit_task", "Edit Task"),
        Binding("d", "delete_task", "Delete Task"),
        Binding("l", "add_dependency", "Link (Dep)"),
        Binding("r", "reschedule", "Reschedule"),
        Binding("x", "export", "Export"),
        Binding("i", "import_cal", "Import"),
        Binding("s", "save_project", "Save"),
        Binding("p", "print_project", "Print"),
        Binding("q", "quit", "Quit"),
        Binding("1", "show_gantt", "Gantt"),
        Binding("2", "show_kanban", "Kanban"),
    ]

    def __init__(self, project: Optional[Project] = None, file_path: Optional[str] = None):
        super().__init__()
        if project:
            self.project = project
        elif file_path and Path(file_path).exists():
            self.project = Project.load(file_path)
        else:
            self.project = Project(
                name="New Project",
                start_date=date.today(),
            )
            if file_path:
                self.project.file_path = file_path

    def compose(self) -> ComposeResult:
        yield Header()

        with TabbedContent(id="main-content"):
            with TabPane("Gantt Chart", id="gantt-tab"):
                yield GanttChart(self.project, id="gantt-chart")
            with TabPane("Kanban Board", id="kanban-tab"):
                yield KanbanBoard(self.project, id="kanban-board")

        yield Static("", id="task-info-panel")
        yield StatusBar()
        yield Footer()

    def on_mount(self) -> None:
        self._run_scheduler()
        self._update_status()
        self.push_screen(SplashScreen())

    def _run_scheduler(self) -> None:
        if not self.project.tasks:
            return
        try:
            scheduler = Scheduler(self.project)
            scheduler.schedule(self.project.start_date)
        except SchedulerError as e:
            self.notify(str(e), severity="error")

    def _update_status(self) -> None:
        try:
            self.query_one(StatusBar).update_project(self.project)
        except Exception:
            pass

    def _refresh_views(self) -> None:
        self._run_scheduler()
        try:
            self.query_one("#gantt-chart", GanttChart).refresh_chart()
        except Exception:
            pass
        try:
            self.query_one("#kanban-board", KanbanBoard).refresh_board()
        except Exception:
            pass
        self._update_status()

    def _update_task_info(self, task: Task) -> None:
        panel = self.query_one("#task-info-panel", Static)
        deps = ", ".join(
            f"{self.project.get_task(d.predecessor_id).name if self.project.get_task(d.predecessor_id) else d.predecessor_id} ({d.dependency_type.value})"
            for d in task.dependencies
        ) if task.dependencies else "None"

        info = (
            f"[bold]{task.wbs}[/bold] {task.name}\n"
            f"Status: {task.status.value} │ Duration: {task.duration_days}d │ "
            f"Progress: {int(task.progress * 100)}% │ Priority: {task.priority}\n"
            f"Start: {task.start_date} │ End: {task.end_date} │ "
            f"Float: {task.total_float}d │ Critical: {'Yes' if task.is_critical else 'No'}\n"
            f"Assigned: {task.assigned_to or '-'} │ Dependencies: {deps}"
        )
        panel.update(info)

    def on_gantt_task_row_selected(self, event) -> None:
        self._update_task_info(event.gantt_task)

    def on_kanban_card_selected(self, event) -> None:
        self._update_task_info(event.gantt_task)

    def action_add_task(self) -> None:
        def on_result(task: Optional[Task]) -> None:
            if task:
                self.project.add_task(task)
                self._refresh_views()
                self.notify(f"Added task: {task.name}")

        self.push_screen(TaskEditScreen(project=self.project), on_result)

    def action_edit_task(self) -> None:
        gantt = self.query_one("#gantt-chart", GanttChart)
        task = gantt.get_selected_task()
        if not task:
            self.notify("No task selected", severity="warning")
            return

        def on_result(updated: Optional[Task]) -> None:
            if updated:
                # Update in place
                original = self.project.get_task(task.id)
                if original:
                    original.name = updated.name
                    original.wbs = updated.wbs or original.wbs
                    original.description = updated.description
                    original.duration_days = updated.duration_days
                    original.assigned_to = updated.assigned_to
                    original.color = updated.color
                    original.status = updated.status
                    original.priority = updated.priority
                    if updated.start_date:
                        original.start_date = updated.start_date
                    self._refresh_views()
                    self.notify(f"Updated: {original.name}")

        self.push_screen(TaskEditScreen(task=task, project=self.project), on_result)

    def action_delete_task(self) -> None:
        gantt = self.query_one("#gantt-chart", GanttChart)
        task = gantt.get_selected_task()
        if task:
            self.project.remove_task(task.id)
            self._refresh_views()
            self.notify(f"Deleted: {task.name}")
        else:
            self.notify("No task selected", severity="warning")

    def action_add_dependency(self) -> None:
        gantt = self.query_one("#gantt-chart", GanttChart)
        task = gantt.get_selected_task()
        if not task:
            self.notify("Select a task first", severity="warning")
            return

        def on_result(dep: Optional[Dependency]) -> None:
            if dep:
                original = self.project.get_task(task.id)
                if original:
                    original.dependencies.append(dep)
                    self._refresh_views()
                    pred = self.project.get_task(dep.predecessor_id)
                    pred_name = pred.name if pred else dep.predecessor_id
                    self.notify(f"Added dependency: {pred_name} -> {original.name}")

        self.push_screen(DependencyScreen(self.project, task.id), on_result)

    def action_reschedule(self) -> None:
        self._refresh_views()
        self.notify("Project rescheduled")

    def action_export(self) -> None:
        self.push_screen(ExportScreen(self.project))

    def action_import_cal(self) -> None:
        def on_result(path: Optional[str]) -> None:
            if path:
                from .calendar_io import import_ical
                try:
                    import_ical(path, self.project)
                    self._refresh_views()
                    self.notify(f"Imported from {path}")
                except Exception as e:
                    self.notify(f"Import failed: {e}", severity="error")

        self.push_screen(ImportScreen(), on_result)

    def action_save_project(self) -> None:
        try:
            path = self.project.save()
            self.notify(f"Saved to {path}")
        except Exception as e:
            self.notify(f"Save failed: {e}", severity="error")

    def action_print_project(self) -> None:
        from .export import print_project
        print_project(self.project)
        self.notify("Printed to terminal")

    def action_show_gantt(self) -> None:
        self.query_one(TabbedContent).active = "gantt-tab"

    def action_show_kanban(self) -> None:
        self.query_one(TabbedContent).active = "kanban-tab"

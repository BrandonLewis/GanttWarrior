"""Gantt chart TUI view using Textual."""

from __future__ import annotations

from datetime import date, timedelta
from enum import Enum
from typing import Optional

from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static, Label

from ..grid_editor import GridEditor
from ..models import Project, Task, TaskColor, TaskStatus
from ..work_calendar import WorkCalendar


# Map TaskColor to Rich color names
COLOR_MAP = {
    TaskColor.RED: "red",
    TaskColor.GREEN: "green",
    TaskColor.BLUE: "dodger_blue1",
    TaskColor.YELLOW: "yellow",
    TaskColor.MAGENTA: "magenta",
    TaskColor.CYAN: "cyan",
    TaskColor.ORANGE: "dark_orange",
    TaskColor.PURPLE: "medium_purple",
    TaskColor.WHITE: "white",
}

STATUS_SYMBOLS = {
    TaskStatus.NOT_STARTED: "○",
    TaskStatus.IN_PROGRESS: "◉",
    TaskStatus.COMPLETED: "✓",
    TaskStatus.BLOCKED: "⊘",
    TaskStatus.CANCELLED: "✗",
}


class ZoomLevel(str, Enum):
    DAY = "day"
    HALF_WEEK = "half_week"
    WEEK = "week"


class GanttTaskRow(Widget):
    """A single task row in the Gantt chart."""

    DEFAULT_CSS = """
    GanttTaskRow {
        height: 1;
        width: 1fr;
    }
    GanttTaskRow.critical {
        background: $error 10%;
    }
    GanttTaskRow.selected {
        background: $accent 20%;
    }
    """

    class Selected(Message):
        def __init__(self, task: Task) -> None:
            super().__init__()
            self.gantt_task = task

    def __init__(
        self,
        task: Task,
        chart_start: date,
        chart_end: date,
        calendar: WorkCalendar,
        day_width: int = 2,
        label_width: int = 35,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.gantt_task = task
        self.chart_start = chart_start
        self.chart_end = chart_end
        self.calendar = calendar
        self.day_width = day_width
        self.label_width = label_width
        self.cursor_date: Optional[date] = None
        self.sel_start: Optional[date] = None
        self.sel_end: Optional[date] = None
        if task.is_critical:
            self.add_class("critical")

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

        # Determine bar span for gap detection
        bar_start = task.start_date
        bar_end = task.end_date
        color = COLOR_MAP.get(task.color, "white")
        bar_style = Style(color=color, bold=task.is_critical)

        # Normalize selection range
        sel_lo: Optional[date] = None
        sel_hi: Optional[date] = None
        if self.sel_start is not None and self.sel_end is not None:
            sel_lo = min(self.sel_start, self.sel_end)
            sel_hi = max(self.sel_start, self.sel_end)

        # Render cell-by-cell
        for i in range(total_days):
            d = self.chart_start + timedelta(days=i)
            is_cursor = (d == self.cursor_date)
            is_selected = (sel_lo is not None and sel_hi is not None and sel_lo <= d <= sel_hi)
            is_filled = (d in task.work_days)
            is_working = self.calendar.is_working_day(d, task)
            in_bar_span = (bar_start is not None and bar_end is not None
                           and bar_start <= d <= bar_end)

            cell_width = self.day_width

            if is_cursor:
                line.append("▓" * cell_width, style=Style(color="black", bgcolor="yellow", bold=True))
            elif is_selected:
                if is_filled:
                    line.append("▒" * cell_width, style=Style(color=color, bgcolor="grey37"))
                else:
                    line.append("▒" * cell_width, style=Style(color="grey50", bgcolor="grey23"))
            elif is_filled:
                line.append("█" * cell_width, style=bar_style)
            elif not is_working:
                line.append(" ·"[:cell_width].ljust(cell_width), style=Style(color="grey30", dim=True))
            elif in_bar_span:
                # Gap within bar span (working day but not filled)
                line.append("·" * cell_width, style=Style(color="grey50"))
            else:
                line.append(" " * cell_width)

        return line

    def on_click(self) -> None:
        self.add_class("selected")
        self.post_message(self.Selected(self.gantt_task))


class GanttHeader(Static):
    """Header row showing date scale."""

    DEFAULT_CSS = """
    GanttHeader {
        height: 2;
        width: 1fr;
        color: $text-muted;
    }
    """

    def __init__(
        self,
        chart_start: date,
        chart_end: date,
        day_width: int = 2,
        label_width: int = 35,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.chart_start = chart_start
        self.chart_end = chart_end
        self.day_width = day_width
        self.label_width = label_width

    def render(self) -> Text:
        total_days = (self.chart_end - self.chart_start).days + 1
        header = Text()

        # Month row
        month_line = " " * self.label_width + "│"
        current = self.chart_start
        while current <= self.chart_end:
            month_name = current.strftime("%b %Y")
            # Simpler: just count remaining days in this month
            if current.month < 12:
                next_month = date(current.year, current.month + 1, 1)
            else:
                next_month = date(current.year + 1, 1, 1)
            days_left = min((next_month - current).days, (self.chart_end - current).days + 1)
            space = days_left * self.day_width
            month_line += month_name[:space].center(space)
            current = next_month

        header.append(month_line + "\n", style="bold")

        # Day row
        day_line = " " * self.label_width + "│"
        for i in range(total_days):
            d = self.chart_start + timedelta(days=i)
            day_str = str(d.day).rjust(self.day_width)
            day_line += day_str  # simplified
        header.append(day_line, style="dim")

        return header


class GanttChart(ScrollableContainer):
    """The full Gantt chart widget with cell-grid cursor/selection/editing."""

    DEFAULT_CSS = """
    GanttChart {
        height: 1fr;
        width: 1fr;
        overflow-y: auto;
        overflow-x: auto;
    }
    """

    BINDINGS = [
        Binding("up", "cursor_up", "Up"),
        Binding("down", "cursor_down", "Down"),
        Binding("left", "cursor_left", "Left"),
        Binding("right", "cursor_right", "Right"),
        Binding("ctrl+left", "jump_week_left", "Week Left", show=False),
        Binding("ctrl+right", "jump_week_right", "Week Right", show=False),
        Binding("home", "jump_bar_start", "Bar Start", show=False),
        Binding("end", "jump_bar_end", "Bar End", show=False),
        Binding("ctrl+home", "jump_project_start", "Proj Start", show=False),
        Binding("ctrl+end", "jump_project_end", "Proj End", show=False),
        Binding("tab", "next_task_bar", "Next Bar", show=False),
        Binding("shift+tab", "prev_task_bar", "Prev Bar", show=False),
        Binding("shift+left", "select_left", "Sel Left", show=False),
        Binding("shift+right", "select_right", "Sel Right", show=False),
        Binding("shift+home", "select_to_bar_start", "Sel Start", show=False),
        Binding("shift+end", "select_to_bar_end", "Sel End", show=False),
        Binding("ctrl+a", "select_all_bar", "Sel All", show=False),
        Binding("space", "fill_cell", "Fill"),
        Binding("enter", "fill_cell", "Fill", show=False),
        Binding("delete", "erase_cell", "Erase"),
        Binding("backspace", "erase_cell", "Erase", show=False),
        Binding("ctrl+c", "copy_cells", "Copy", show=False),
        Binding("ctrl+x", "cut_cells", "Cut", show=False),
        Binding("ctrl+v", "paste_cells", "Paste", show=False),
        Binding("shift+insert", "paste_cells", "Paste", show=False),
        Binding("ctrl+shift+v", "paste_new_task", "Paste New", show=False),
        Binding("ctrl+z", "undo_edit", "Undo", show=False),
        Binding("ctrl+y", "redo_edit", "Redo", show=False),
        Binding("ctrl+k", "split_task", "Split", show=False),
        Binding("ctrl+m", "merge_task", "Merge", show=False),
        Binding("ctrl+d", "duplicate_task", "Duplicate", show=False),
        Binding("plus_sign", "zoom_in", "+Zoom", show=False),
        Binding("hyphen_minus", "zoom_out", "-Zoom", show=False),
    ]

    selected_index: reactive[int] = reactive(0)
    cursor_col: reactive[Optional[date]] = reactive(None)
    selection_start: reactive[Optional[date]] = reactive(None)
    selection_end: reactive[Optional[date]] = reactive(None)

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

    def _get_date_range(self) -> tuple[date, date]:
        starts = [t.start_date for t in self.project.tasks if t.start_date]
        ends = [t.end_date for t in self.project.tasks if t.end_date]

        if not starts:
            today = date.today()
            self._chart_start = today
            self._chart_end = today + timedelta(days=30)
            return self._chart_start, self._chart_end

        chart_start = min(starts) - timedelta(days=1)
        chart_end = max(ends) + timedelta(days=3) if ends else min(starts) + timedelta(days=30)
        self._chart_start = chart_start
        self._chart_end = chart_end
        return chart_start, chart_end

    def compose(self) -> ComposeResult:
        chart_start, chart_end = self._get_date_range()

        yield GanttHeader(
            chart_start, chart_end,
            day_width=self.day_width,
            label_width=self.label_width,
        )

        # Separator
        total_days = (chart_end - chart_start).days + 1
        sep = "─" * self.label_width + "┼" + "─" * (total_days * self.day_width)
        yield Static(sep, classes="gantt-separator")

        self._task_rows = []
        for task in self.project.sorted_tasks():
            row = GanttTaskRow(
                task, chart_start, chart_end,
                calendar=self.calendar,
                day_width=self.day_width,
                label_width=self.label_width,
            )
            self._task_rows.append(row)
            yield row

    def on_gantt_task_row_selected(self, event: GanttTaskRow.Selected) -> None:
        # Deselect all, select clicked
        for row in self._task_rows:
            row.remove_class("selected")
        for i, row in enumerate(self._task_rows):
            if row.gantt_task.id == event.gantt_task.id:
                row.add_class("selected")
                self.selected_index = i
                break

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ensure_cursor(self) -> None:
        """Initialize cursor_col if not yet set."""
        if self.cursor_col is None:
            task = self.get_selected_task()
            if task and task.start_date:
                self.cursor_col = task.start_date
            else:
                self.cursor_col = self._chart_start

    def _clear_selection(self) -> None:
        """Reset selection anchors."""
        self.selection_start = None
        self.selection_end = None

    def _refresh_row(self, index: Optional[int] = None) -> None:
        """Push cursor/selection state to the specified row and refresh it."""
        if index is None:
            index = self.selected_index
        if 0 <= index < len(self._task_rows):
            row = self._task_rows[index]
            row.cursor_date = self.cursor_col
            row.sel_start = self.selection_start
            row.sel_end = self.selection_end
            row.refresh()

    def _refresh_all_rows(self) -> None:
        """Clear cursor/selection visuals on all rows, set only the selected one."""
        for i, row in enumerate(self._task_rows):
            if i == self.selected_index:
                row.cursor_date = self.cursor_col
                row.sel_start = self.selection_start
                row.sel_end = self.selection_end
            else:
                row.cursor_date = None
                row.sel_start = None
                row.sel_end = None
            row.refresh()

    def _get_selected_row(self) -> Optional[GanttTaskRow]:
        """Return the currently selected row, if any."""
        if self._task_rows and 0 <= self.selected_index < len(self._task_rows):
            return self._task_rows[self.selected_index]
        return None

    # ------------------------------------------------------------------
    # Navigation actions
    # ------------------------------------------------------------------

    def action_cursor_up(self) -> None:
        if self._task_rows and self.selected_index > 0:
            self._task_rows[self.selected_index].remove_class("selected")
            old_index = self.selected_index
            self.selected_index -= 1
            self._task_rows[self.selected_index].add_class("selected")
            self._task_rows[self.selected_index].scroll_visible()
            self._clear_selection()
            # Clear old row visuals
            self._task_rows[old_index].cursor_date = None
            self._task_rows[old_index].sel_start = None
            self._task_rows[old_index].sel_end = None
            self._task_rows[old_index].refresh()
            self._refresh_row()

    def action_cursor_down(self) -> None:
        if self._task_rows and self.selected_index < len(self._task_rows) - 1:
            self._task_rows[self.selected_index].remove_class("selected")
            old_index = self.selected_index
            self.selected_index += 1
            self._task_rows[self.selected_index].add_class("selected")
            self._task_rows[self.selected_index].scroll_visible()
            self._clear_selection()
            # Clear old row visuals
            self._task_rows[old_index].cursor_date = None
            self._task_rows[old_index].sel_start = None
            self._task_rows[old_index].sel_end = None
            self._task_rows[old_index].refresh()
            self._refresh_row()

    def action_cursor_left(self) -> None:
        self._ensure_cursor()
        self._clear_selection()
        if self.cursor_col and self.cursor_col > self._chart_start:
            self.cursor_col = self.cursor_col - timedelta(days=1)
        self._refresh_row()

    def action_cursor_right(self) -> None:
        self._ensure_cursor()
        self._clear_selection()
        if self.cursor_col and self.cursor_col < self._chart_end:
            self.cursor_col = self.cursor_col + timedelta(days=1)
        self._refresh_row()

    def action_jump_week_left(self) -> None:
        self._ensure_cursor()
        self._clear_selection()
        if self.cursor_col:
            new_date = self.cursor_col - timedelta(days=7)
            self.cursor_col = max(new_date, self._chart_start)
        self._refresh_row()

    def action_jump_week_right(self) -> None:
        self._ensure_cursor()
        self._clear_selection()
        if self.cursor_col:
            new_date = self.cursor_col + timedelta(days=7)
            self.cursor_col = min(new_date, self._chart_end)
        self._refresh_row()

    def action_jump_bar_start(self) -> None:
        self._clear_selection()
        task = self.get_selected_task()
        if task and task.start_date:
            self.cursor_col = task.start_date
        self._refresh_row()

    def action_jump_bar_end(self) -> None:
        self._clear_selection()
        task = self.get_selected_task()
        if task and task.end_date:
            self.cursor_col = task.end_date
        self._refresh_row()

    def action_jump_project_start(self) -> None:
        self._clear_selection()
        self.cursor_col = self._chart_start
        self._refresh_row()

    def action_jump_project_end(self) -> None:
        self._clear_selection()
        self.cursor_col = self._chart_end
        self._refresh_row()

    def action_next_task_bar(self) -> None:
        """Move cursor down and jump to the next task's bar start."""
        if self._task_rows and self.selected_index < len(self._task_rows) - 1:
            self._task_rows[self.selected_index].remove_class("selected")
            old_index = self.selected_index
            self.selected_index += 1
            self._task_rows[self.selected_index].add_class("selected")
            self._task_rows[self.selected_index].scroll_visible()
            self._clear_selection()
            task = self.get_selected_task()
            if task and task.start_date:
                self.cursor_col = task.start_date
            # Clear old row
            self._task_rows[old_index].cursor_date = None
            self._task_rows[old_index].sel_start = None
            self._task_rows[old_index].sel_end = None
            self._task_rows[old_index].refresh()
            self._refresh_row()

    def action_prev_task_bar(self) -> None:
        """Move cursor up and jump to the previous task's bar start."""
        if self._task_rows and self.selected_index > 0:
            self._task_rows[self.selected_index].remove_class("selected")
            old_index = self.selected_index
            self.selected_index -= 1
            self._task_rows[self.selected_index].add_class("selected")
            self._task_rows[self.selected_index].scroll_visible()
            self._clear_selection()
            task = self.get_selected_task()
            if task and task.start_date:
                self.cursor_col = task.start_date
            # Clear old row
            self._task_rows[old_index].cursor_date = None
            self._task_rows[old_index].sel_start = None
            self._task_rows[old_index].sel_end = None
            self._task_rows[old_index].refresh()
            self._refresh_row()

    # ------------------------------------------------------------------
    # Selection actions
    # ------------------------------------------------------------------

    def action_select_left(self) -> None:
        self._ensure_cursor()
        if self.cursor_col is None or self.cursor_col <= self._chart_start:
            return
        if self.selection_start is None:
            self.selection_start = self.cursor_col
        self.cursor_col = self.cursor_col - timedelta(days=1)
        self.selection_end = self.cursor_col
        self._refresh_row()

    def action_select_right(self) -> None:
        self._ensure_cursor()
        if self.cursor_col is None or self.cursor_col >= self._chart_end:
            return
        if self.selection_start is None:
            self.selection_start = self.cursor_col
        self.cursor_col = self.cursor_col + timedelta(days=1)
        self.selection_end = self.cursor_col
        self._refresh_row()

    def action_select_to_bar_start(self) -> None:
        self._ensure_cursor()
        task = self.get_selected_task()
        if task and task.start_date and self.cursor_col:
            if self.selection_start is None:
                self.selection_start = self.cursor_col
            self.cursor_col = task.start_date
            self.selection_end = self.cursor_col
        self._refresh_row()

    def action_select_to_bar_end(self) -> None:
        self._ensure_cursor()
        task = self.get_selected_task()
        if task and task.end_date and self.cursor_col:
            if self.selection_start is None:
                self.selection_start = self.cursor_col
            self.cursor_col = task.end_date
            self.selection_end = self.cursor_col
        self._refresh_row()

    def action_select_all_bar(self) -> None:
        task = self.get_selected_task()
        if task and task.start_date and task.end_date:
            self.selection_start = task.start_date
            self.selection_end = task.end_date
            self.cursor_col = task.end_date
        self._refresh_row()

    # ------------------------------------------------------------------
    # Editing actions
    # ------------------------------------------------------------------

    def action_fill_cell(self) -> None:
        self._ensure_cursor()
        task = self.get_selected_task()
        if not task or not self.cursor_col:
            return
        if self.selection_start is not None and self.selection_end is not None:
            sel_lo = min(self.selection_start, self.selection_end)
            sel_hi = max(self.selection_start, self.selection_end)
            self.editor.fill_range(task, sel_lo, sel_hi)
            self._clear_selection()
        else:
            self.editor.fill(task, self.cursor_col)
        self._refresh_all_rows()

    def action_erase_cell(self) -> None:
        self._ensure_cursor()
        task = self.get_selected_task()
        if not task or not self.cursor_col:
            return
        if self.selection_start is not None and self.selection_end is not None:
            sel_lo = min(self.selection_start, self.selection_end)
            sel_hi = max(self.selection_start, self.selection_end)
            self.editor.erase_range(task, sel_lo, sel_hi)
            self._clear_selection()
        else:
            self.editor.erase(task, self.cursor_col)
        self._refresh_all_rows()

    def action_copy_cells(self) -> None:
        self._ensure_cursor()
        task = self.get_selected_task()
        if not task:
            return
        if self.selection_start is not None and self.selection_end is not None:
            sel_lo = min(self.selection_start, self.selection_end)
            sel_hi = max(self.selection_start, self.selection_end)
            self.editor.copy(task, sel_lo, sel_hi)
            self.app.notify(f"Copied {(sel_hi - sel_lo).days + 1} days")
        elif self.cursor_col:
            self.editor.copy(task, self.cursor_col, self.cursor_col)
            self.app.notify("Copied 1 day")

    def action_cut_cells(self) -> None:
        self._ensure_cursor()
        task = self.get_selected_task()
        if not task:
            return
        if self.selection_start is not None and self.selection_end is not None:
            sel_lo = min(self.selection_start, self.selection_end)
            sel_hi = max(self.selection_start, self.selection_end)
            self.editor.cut(task, sel_lo, sel_hi)
            self._clear_selection()
        elif self.cursor_col:
            self.editor.cut(task, self.cursor_col, self.cursor_col)
        self._refresh_all_rows()

    def action_paste_cells(self) -> None:
        self._ensure_cursor()
        task = self.get_selected_task()
        if not task or not self.cursor_col:
            return
        if self.editor.clipboard is None:
            self.app.notify("Clipboard is empty", severity="warning")
            return
        self.editor.paste(task, self.cursor_col)
        self._refresh_all_rows()

    def action_paste_new_task(self) -> None:
        self._ensure_cursor()
        task = self.get_selected_task()
        if not task or not self.cursor_col:
            return
        if self.editor.clipboard is None:
            self.app.notify("Clipboard is empty", severity="warning")
            return
        try:
            new_task = self.editor.paste_as_new_task(self.cursor_col, task)
            self.refresh_chart()
            self.app.notify(f"Created: {new_task.name}")
        except ValueError as e:
            self.app.notify(str(e), severity="error")

    def action_undo_edit(self) -> None:
        if self.editor.undo():
            self._refresh_all_rows()
            self.app.notify("Undo")
        else:
            self.app.notify("Nothing to undo", severity="warning")

    def action_redo_edit(self) -> None:
        if self.editor.redo():
            self._refresh_all_rows()
            self.app.notify("Redo")
        else:
            self.app.notify("Nothing to redo", severity="warning")

    def action_split_task(self) -> None:
        self._ensure_cursor()
        task = self.get_selected_task()
        if not task or not self.cursor_col:
            return
        if not task.work_days:
            self.app.notify("Task has no work days to split", severity="warning")
            return
        self.editor.split(task, self.cursor_col)
        self.refresh_chart()
        self.app.notify(f"Split {task.name} at {self.cursor_col}")

    def action_merge_task(self) -> None:
        """Merge selected task with the next task below it."""
        if not self._task_rows or self.selected_index >= len(self._task_rows) - 1:
            self.app.notify("No next task to merge with", severity="warning")
            return
        task_a = self._task_rows[self.selected_index].gantt_task
        task_b = self._task_rows[self.selected_index + 1].gantt_task
        self.editor.merge(task_a, task_b)
        self.refresh_chart()
        self.app.notify(f"Merged into {task_a.name}")

    def action_duplicate_task(self) -> None:
        task = self.get_selected_task()
        if not task:
            return
        dup = self.editor.duplicate(task)
        self.refresh_chart()
        self.app.notify(f"Duplicated: {dup.name}")

    def action_zoom_in(self) -> None:
        if self.zoom_level == ZoomLevel.WEEK:
            self.zoom_level = ZoomLevel.HALF_WEEK
            self.day_width = 2
        elif self.zoom_level == ZoomLevel.HALF_WEEK:
            self.zoom_level = ZoomLevel.DAY
            self.day_width = 3
        elif self.zoom_level == ZoomLevel.DAY and self.day_width < 5:
            self.day_width += 1
        self.refresh_chart()

    def action_zoom_out(self) -> None:
        if self.zoom_level == ZoomLevel.DAY and self.day_width > 2:
            self.day_width -= 1
        elif self.zoom_level == ZoomLevel.DAY and self.day_width <= 2:
            self.zoom_level = ZoomLevel.HALF_WEEK
            self.day_width = 1
        elif self.zoom_level == ZoomLevel.HALF_WEEK:
            self.zoom_level = ZoomLevel.WEEK
            self.day_width = 1
        self.refresh_chart()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_selected_task(self) -> Optional[Task]:
        if self._task_rows and 0 <= self.selected_index < len(self._task_rows):
            return self._task_rows[self.selected_index].gantt_task
        return None

    def refresh_chart(self) -> None:
        """Rebuild the chart after data changes."""
        self.remove_children()
        self._task_rows = []
        chart_start, chart_end = self._get_date_range()

        self.mount(GanttHeader(
            chart_start, chart_end,
            day_width=self.day_width,
            label_width=self.label_width,
        ))

        total_days = (chart_end - chart_start).days + 1
        sep = "─" * self.label_width + "┼" + "─" * (total_days * self.day_width)
        self.mount(Static(sep, classes="gantt-separator"))

        for task in self.project.sorted_tasks():
            row = GanttTaskRow(
                task, chart_start, chart_end,
                calendar=self.calendar,
                day_width=self.day_width,
                label_width=self.label_width,
            )
            self._task_rows.append(row)
            self.mount(row)

        # Restore cursor on selected row
        if self.selected_index >= len(self._task_rows):
            self.selected_index = max(0, len(self._task_rows) - 1)
        if self._task_rows:
            self._task_rows[self.selected_index].add_class("selected")
        self._refresh_row()

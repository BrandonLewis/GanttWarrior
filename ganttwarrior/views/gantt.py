"""Gantt chart TUI view using Textual."""

from __future__ import annotations

from datetime import date, timedelta
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

from ..models import Project, Task, TaskColor, TaskStatus


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
        day_width: int = 2,
        label_width: int = 35,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.gantt_task = task
        self.chart_start = chart_start
        self.chart_end = chart_end
        self.day_width = day_width
        self.label_width = label_width
        if task.is_critical:
            self.add_class("critical")

    def render(self) -> Text:
        task = self.gantt_task
        total_days = (self.chart_end - self.chart_start).days + 1
        chart_width = total_days * self.day_width

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

        # Build bar
        color = COLOR_MAP.get(task.color, "white")
        bar_style = Style(color=color, bold=task.is_critical)
        critical_style = Style(color="red", bold=True)

        if task.start_date and task.end_date:
            start_offset = max((task.start_date - self.chart_start).days, 0)
            end_offset = min((task.end_date - self.chart_start).days + 1, total_days)
            bar_len = max(end_offset - start_offset, 0)

            # Spaces before bar
            line.append(" " * (start_offset * self.day_width))

            if task.is_milestone:
                line.append("◆", style=critical_style if task.is_critical else bar_style)
            else:
                bar_chars = bar_len * self.day_width
                if bar_chars > 0:
                    # Show progress within bar
                    filled = int(bar_chars * task.progress)
                    remaining = bar_chars - filled
                    if filled > 0:
                        line.append("█" * filled, style=bar_style)
                    if remaining > 0:
                        line.append("░" * remaining, style=bar_style)

            # Spaces after bar
            after = chart_width - (end_offset * self.day_width)
            if after > 0:
                line.append(" " * after)
        else:
            line.append(" " * chart_width)

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
            style = "dim" if d.weekday() >= 5 else ""
            day_line += day_str if not style else day_str  # simplified
        header.append(day_line, style="dim")

        return header


class GanttChart(ScrollableContainer):
    """The full Gantt chart widget."""

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
        Binding("enter", "select_task", "Select"),
    ]

    selected_index: reactive[int] = reactive(0)

    def __init__(self, project: Project, day_width: int = 2, **kwargs):
        super().__init__(**kwargs)
        self.project = project
        self.day_width = day_width
        self.label_width = 35
        self._task_rows: list[GanttTaskRow] = []

    def _get_date_range(self) -> tuple[date, date]:
        starts = [t.start_date for t in self.project.tasks if t.start_date]
        ends = [t.end_date for t in self.project.tasks if t.end_date]

        if not starts:
            today = date.today()
            return today, today + timedelta(days=30)

        chart_start = min(starts) - timedelta(days=1)
        chart_end = max(ends) + timedelta(days=3) if ends else min(starts) + timedelta(days=30)
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

    def action_cursor_up(self) -> None:
        if self._task_rows and self.selected_index > 0:
            self._task_rows[self.selected_index].remove_class("selected")
            self.selected_index -= 1
            self._task_rows[self.selected_index].add_class("selected")
            self._task_rows[self.selected_index].scroll_visible()

    def action_cursor_down(self) -> None:
        if self._task_rows and self.selected_index < len(self._task_rows) - 1:
            self._task_rows[self.selected_index].remove_class("selected")
            self.selected_index += 1
            self._task_rows[self.selected_index].add_class("selected")
            self._task_rows[self.selected_index].scroll_visible()

    def action_select_task(self) -> None:
        if self._task_rows:
            row = self._task_rows[self.selected_index]
            row.post_message(GanttTaskRow.Selected(row.gantt_task))

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
                day_width=self.day_width,
                label_width=self.label_width,
            )
            self._task_rows.append(row)
            self.mount(row)

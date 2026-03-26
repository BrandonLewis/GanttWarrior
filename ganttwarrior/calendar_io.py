"""iCalendar import and export for GanttWarrior."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from icalendar import Calendar, Event, vDate

from .models import Dependency, DependencyType, Project, Task, TaskColor, TaskStatus


def export_ical(project: Project, path: str) -> str:
    """Export project tasks to an iCalendar (.ics) file."""
    cal = Calendar()
    cal.add("prodid", "-//GanttWarrior//ganttwarrior//EN")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", project.name)

    for task in project.tasks:
        event = Event()
        event.add("uid", f"{task.id}@ganttwarrior")
        event.add("summary", f"[{task.wbs}] {task.name}" if task.wbs else task.name)

        if task.description:
            event.add("description", task.description)

        if task.start_date:
            event.add("dtstart", vDate(task.start_date))
        if task.end_date:
            # iCal DTEND is exclusive for DATE values
            event.add("dtend", vDate(task.end_date + timedelta(days=1)))

        if task.duration_days and not task.end_date:
            event.add("duration", timedelta(days=task.duration_days))

        # Store metadata in custom properties
        event.add("x-gw-wbs", task.wbs)
        event.add("x-gw-status", task.status.value)
        event.add("x-gw-color", task.color.value)
        event.add("x-gw-progress", str(task.progress))
        event.add("x-gw-priority", str(task.priority))

        if task.assigned_to:
            event.add("x-gw-assigned", task.assigned_to)

        if task.is_milestone:
            event.add("x-gw-milestone", "true")

        if task.is_critical:
            event.add("x-gw-critical", "true")

        # Dependencies as comma-separated predecessor IDs
        if task.dependencies:
            deps = ",".join(
                f"{d.predecessor_id}:{d.dependency_type.value}:{d.lag_days}"
                for d in task.dependencies
            )
            event.add("x-gw-dependencies", deps)

        event.add("categories", [task.status.value, task.color.value])
        cal.add_component(event)

    output_path = Path(path)
    output_path.write_bytes(cal.to_ical())
    return str(output_path)


def import_ical(path: str, project: Optional[Project] = None) -> Project:
    """Import tasks from an iCalendar (.ics) file."""
    cal_data = Path(path).read_bytes()
    cal = Calendar.from_ical(cal_data)

    if project is None:
        cal_name = str(cal.get("x-wr-calname", "Imported Project"))
        project = Project(name=cal_name, start_date=date.today())

    color_index = len(project.tasks)

    for component in cal.walk():
        if component.name != "VEVENT":
            continue

        summary = str(component.get("summary", "Untitled"))
        uid = str(component.get("uid", ""))
        task_id = uid.split("@")[0] if "@" in uid else uid[:8]

        # Parse dates
        dtstart = component.get("dtstart")
        dtend = component.get("dtend")
        start_date = None
        end_date = None

        if dtstart:
            dt = dtstart.dt
            start_date = dt if isinstance(dt, date) and not isinstance(dt, datetime) else dt.date() if isinstance(dt, datetime) else dt

        if dtend:
            dt = dtend.dt
            end_date = dt if isinstance(dt, date) and not isinstance(dt, datetime) else dt.date() if isinstance(dt, datetime) else dt
            # iCal DTEND is exclusive for DATE
            if end_date:
                end_date = end_date - timedelta(days=1)

        # Calculate duration
        duration_days = 1
        if start_date and end_date:
            duration_days = max((end_date - start_date).days + 1, 1)

        # Parse GanttWarrior-specific metadata
        wbs = str(component.get("x-gw-wbs", ""))
        status_str = str(component.get("x-gw-status", "not_started"))
        color_str = str(component.get("x-gw-color", ""))
        progress_str = str(component.get("x-gw-progress", "0"))
        priority_str = str(component.get("x-gw-priority", "0"))
        assigned = str(component.get("x-gw-assigned", ""))
        is_milestone = str(component.get("x-gw-milestone", "")).lower() == "true"

        # Parse status
        try:
            status = TaskStatus(status_str)
        except ValueError:
            status = TaskStatus.NOT_STARTED

        # Parse color
        try:
            color = TaskColor(color_str) if color_str else TaskColor.cycle(color_index)
        except ValueError:
            color = TaskColor.cycle(color_index)

        # Parse dependencies
        dependencies = []
        dep_str = str(component.get("x-gw-dependencies", ""))
        if dep_str:
            for dep_part in dep_str.split(","):
                parts = dep_part.strip().split(":")
                if len(parts) >= 1 and parts[0]:
                    pred_id = parts[0]
                    dep_type = DependencyType(parts[1]) if len(parts) > 1 else DependencyType.FINISH_TO_START
                    lag = int(parts[2]) if len(parts) > 2 else 0
                    dependencies.append(Dependency(pred_id, dep_type, lag))

        # Strip WBS prefix from summary if present
        name = summary
        if name.startswith("[") and "]" in name:
            name = name[name.index("]") + 1:].strip()

        task = Task(
            id=task_id,
            name=name,
            wbs=wbs,
            description=str(component.get("description", "")),
            start_date=start_date,
            end_date=end_date,
            duration_days=duration_days,
            status=status,
            color=color,
            progress=float(progress_str),
            dependencies=dependencies,
            assigned_to=assigned,
            priority=int(priority_str),
            is_milestone=is_milestone,
        )
        project.tasks.append(task)
        color_index += 1

    return project

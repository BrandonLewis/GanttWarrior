"""Work calendar helper for resolving working days."""

from datetime import date, timedelta
from typing import Optional

from ganttwarrior.models import Project, Task


class WorkCalendar:
    """Resolves working-day rules for a project with optional per-task overrides."""

    def __init__(self, project: Project) -> None:
        self.project = project

    def _work_weekdays(self, task: Optional[Task] = None) -> set[int]:
        """Return the effective work weekdays set for the given context."""
        if task is not None and task.work_weekdays is not None:
            return task.work_weekdays
        return self.project.default_work_weekdays

    def is_working_day(self, d: date, task: Optional[Task] = None) -> bool:
        """Check if a date is a working day.

        Uses task.work_weekdays if set, otherwise project.default_work_weekdays.
        Also checks project.holidays.
        """
        if d in self.project.holidays:
            return False
        return d.weekday() in self._work_weekdays(task)

    def expand_duration(
        self, start: date, duration: int, task: Optional[Task] = None
    ) -> set[date]:
        """Starting from *start*, return *duration* working days.

        Skips non-working days (weekends per the applicable weekday set and
        project holidays).
        """
        if duration <= 0:
            return set()
        result: set[date] = set()
        current = start
        while len(result) < duration:
            if self.is_working_day(current, task):
                result.add(current)
            current += timedelta(days=1)
        return result

    def get_week_work_days(
        self, d: date, task: Optional[Task] = None
    ) -> set[date]:
        """Return all working days in the Monday-Sunday week containing *d*."""
        monday = d - timedelta(days=d.weekday())
        return {
            monday + timedelta(days=i)
            for i in range(7)
            if self.is_working_day(monday + timedelta(days=i), task)
        }

    def get_half_week_work_days(
        self, d: date, task: Optional[Task] = None
    ) -> set[date]:
        """Return working days in the half-week containing *d*.

        Mon-Wed (weekday 0-2) is the first half; Thu-Sun (weekday 3-6) is
        the second half.
        """
        monday = d - timedelta(days=d.weekday())
        if d.weekday() <= 2:
            # First half: Monday, Tuesday, Wednesday
            day_range = range(0, 3)
        else:
            # Second half: Thursday, Friday, Saturday, Sunday
            day_range = range(3, 7)
        return {
            monday + timedelta(days=i)
            for i in day_range
            if self.is_working_day(monday + timedelta(days=i), task)
        }

"""Tests for work calendar logic."""
from datetime import date
import pytest
from ganttwarrior.models import Project, Task
from ganttwarrior.work_calendar import WorkCalendar

class TestWorkCalendar:
    def test_is_working_day_weekday(self):
        project = Project(name="Test", default_work_weekdays={0, 1, 2, 3, 4})
        cal = WorkCalendar(project)
        assert cal.is_working_day(date(2026, 3, 25)) is True  # Wednesday

    def test_is_working_day_weekend(self):
        project = Project(name="Test", default_work_weekdays={0, 1, 2, 3, 4})
        cal = WorkCalendar(project)
        assert cal.is_working_day(date(2026, 3, 28)) is False  # Saturday

    def test_is_working_day_holiday(self):
        project = Project(name="Test", default_work_weekdays={0, 1, 2, 3, 4})
        project.holidays = {date(2026, 3, 25)}
        cal = WorkCalendar(project)
        assert cal.is_working_day(date(2026, 3, 25)) is False

    def test_is_working_day_task_override(self):
        project = Project(name="Test", default_work_weekdays={0, 1, 2, 3, 4})
        cal = WorkCalendar(project)
        task = Task(name="Weekend Work", work_weekdays={5, 6})
        assert cal.is_working_day(date(2026, 3, 28), task=task) is True  # Sat
        assert cal.is_working_day(date(2026, 3, 25), task=task) is False  # Wed

    def test_expand_duration(self):
        project = Project(name="Test", default_work_weekdays={0, 1, 2, 3, 4})
        cal = WorkCalendar(project)
        days = cal.expand_duration(date(2026, 3, 25), 5)  # Start Wed
        assert len(days) == 5
        assert days == {date(2026, 3, 25), date(2026, 3, 26), date(2026, 3, 27), date(2026, 3, 30), date(2026, 3, 31)}

    def test_expand_duration_with_holiday(self):
        project = Project(name="Test", default_work_weekdays={0, 1, 2, 3, 4})
        project.holidays = {date(2026, 3, 26)}
        cal = WorkCalendar(project)
        days = cal.expand_duration(date(2026, 3, 25), 3)
        assert days == {date(2026, 3, 25), date(2026, 3, 27), date(2026, 3, 30)}

    def test_expand_duration_task_override(self):
        project = Project(name="Test", default_work_weekdays={0, 1, 2, 3, 4})
        cal = WorkCalendar(project)
        task = Task(name="Weekend", work_weekdays={5, 6})
        days = cal.expand_duration(date(2026, 3, 28), 2, task=task)
        assert days == {date(2026, 3, 28), date(2026, 3, 29)}

    def test_expand_duration_zero(self):
        project = Project(name="Test")
        cal = WorkCalendar(project)
        assert cal.expand_duration(date(2026, 3, 25), 0) == set()

    def test_get_week_dates(self):
        project = Project(name="Test", default_work_weekdays={0, 1, 2, 3, 4})
        cal = WorkCalendar(project)
        days = cal.get_week_work_days(date(2026, 3, 25))  # Wed
        assert days == {date(2026, 3, 23), date(2026, 3, 24), date(2026, 3, 25), date(2026, 3, 26), date(2026, 3, 27)}

    def test_get_half_week_dates_first_half(self):
        project = Project(name="Test", default_work_weekdays={0, 1, 2, 3, 4})
        cal = WorkCalendar(project)
        days = cal.get_half_week_work_days(date(2026, 3, 23))  # Monday
        assert days == {date(2026, 3, 23), date(2026, 3, 24), date(2026, 3, 25)}

    def test_get_half_week_dates_second_half(self):
        project = Project(name="Test", default_work_weekdays={0, 1, 2, 3, 4})
        cal = WorkCalendar(project)
        days = cal.get_half_week_work_days(date(2026, 3, 26))  # Thursday
        assert days == {date(2026, 3, 26), date(2026, 3, 27)}

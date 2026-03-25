"""CLI entry point for GanttWarrior."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ganttwarrior",
        description="GanttWarrior - TUI Gantt Chart & Task Scheduler",
    )
    subparsers = parser.add_subparsers(dest="command")

    # Default: launch TUI
    parser.add_argument("file", nargs="?", help="Project file (.gw.json) to open")
    parser.add_argument("--new", "-n", metavar="NAME", help="Create a new project")

    # Export subcommand
    export_parser = subparsers.add_parser("export", help="Export project")
    export_parser.add_argument("file", help="Project file to export")
    export_parser.add_argument("--pdf", metavar="PATH", help="Export to PDF")
    export_parser.add_argument("--excel", metavar="PATH", help="Export to Excel")
    export_parser.add_argument("--ical", metavar="PATH", help="Export to iCalendar")
    export_parser.add_argument("--print", action="store_true", help="Print to terminal")

    # Import subcommand
    import_parser = subparsers.add_parser("import", help="Import calendar")
    import_parser.add_argument("ical_file", help="iCalendar file to import")
    import_parser.add_argument("--output", "-o", help="Output project file")

    # Demo subcommand
    subparsers.add_parser("demo", help="Launch with a demo project")

    args = parser.parse_args()

    if args.command == "export":
        _handle_export(args)
    elif args.command == "import":
        _handle_import(args)
    elif args.command == "demo":
        _launch_demo()
    else:
        _launch_tui(args)


def _handle_export(args) -> None:
    from .export import export_excel, export_pdf, print_project
    from .models import Project
    from .scheduler import Scheduler

    project = Project.load(args.file)
    scheduler = Scheduler(project)
    scheduler.schedule()

    if args.pdf:
        path = export_pdf(project, args.pdf)
        print(f"Exported PDF: {path}")
    if args.excel:
        path = export_excel(project, args.excel)
        print(f"Exported Excel: {path}")
    if args.ical:
        from .calendar_io import export_ical
        path = export_ical(project, args.ical)
        print(f"Exported iCal: {path}")
    if getattr(args, "print", False):
        print_project(project)


def _handle_import(args) -> None:
    from .calendar_io import import_ical
    from .models import Project

    project = import_ical(args.ical_file)
    output = args.output or args.ical_file.rsplit(".", 1)[0] + ".gw.json"
    project.save(output)
    print(f"Imported {len(project.tasks)} tasks to {output}")


def _launch_demo() -> None:
    from .models import Dependency, DependencyType, Project, Task, TaskColor, TaskStatus

    project = Project(
        name="Website Redesign",
        description="Complete website redesign project",
        start_date=date.today(),
    )

    # Phase 1: Planning
    t1 = project.add_task(Task(
        name="Planning", wbs="1", duration_days=1,
        color=TaskColor.BLUE, is_milestone=False,
    ))
    t1_1 = project.add_task(Task(
        name="Requirements Gathering", wbs="1.1", duration_days=5,
        color=TaskColor.BLUE, assigned_to="Alice", parent_wbs="1",
    ))
    t1_2 = project.add_task(Task(
        name="Stakeholder Review", wbs="1.2", duration_days=3,
        color=TaskColor.BLUE, assigned_to="Bob", parent_wbs="1",
        dependencies=[Dependency(t1_1.id, DependencyType.FINISH_TO_START)],
    ))
    t1_3 = project.add_task(Task(
        name="Approve Requirements", wbs="1.3", duration_days=1,
        color=TaskColor.YELLOW, assigned_to="Charlie", parent_wbs="1",
        is_milestone=True,
        dependencies=[Dependency(t1_2.id, DependencyType.FINISH_TO_START)],
    ))

    # Phase 2: Design
    t2 = project.add_task(Task(
        name="Design", wbs="2", duration_days=1,
        color=TaskColor.GREEN,
    ))
    t2_1 = project.add_task(Task(
        name="Wireframes", wbs="2.1", duration_days=7,
        color=TaskColor.GREEN, assigned_to="Diana", parent_wbs="2",
        dependencies=[Dependency(t1_3.id, DependencyType.FINISH_TO_START)],
    ))
    t2_2 = project.add_task(Task(
        name="Visual Design", wbs="2.2", duration_days=10,
        color=TaskColor.GREEN, assigned_to="Diana", parent_wbs="2",
        dependencies=[Dependency(t2_1.id, DependencyType.FINISH_TO_START)],
    ))
    t2_3 = project.add_task(Task(
        name="Design Review", wbs="2.3", duration_days=2,
        color=TaskColor.GREEN, assigned_to="Bob", parent_wbs="2",
        dependencies=[Dependency(t2_2.id, DependencyType.FINISH_TO_START)],
    ))

    # Phase 3: Development
    t3 = project.add_task(Task(
        name="Development", wbs="3", duration_days=1,
        color=TaskColor.RED,
    ))
    t3_1 = project.add_task(Task(
        name="Frontend Development", wbs="3.1", duration_days=15,
        color=TaskColor.RED, assigned_to="Eve", parent_wbs="3",
        dependencies=[Dependency(t2_3.id, DependencyType.FINISH_TO_START)],
    ))
    t3_2 = project.add_task(Task(
        name="Backend API", wbs="3.2", duration_days=12,
        color=TaskColor.ORANGE, assigned_to="Frank", parent_wbs="3",
        dependencies=[Dependency(t2_3.id, DependencyType.FINISH_TO_START)],
    ))
    t3_3 = project.add_task(Task(
        name="Integration", wbs="3.3", duration_days=5,
        color=TaskColor.RED, assigned_to="Eve", parent_wbs="3",
        dependencies=[
            Dependency(t3_1.id, DependencyType.FINISH_TO_START),
            Dependency(t3_2.id, DependencyType.FINISH_TO_START),
        ],
    ))

    # Phase 4: Testing & Launch
    t4 = project.add_task(Task(
        name="Testing & Launch", wbs="4", duration_days=1,
        color=TaskColor.PURPLE,
    ))
    t4_1 = project.add_task(Task(
        name="QA Testing", wbs="4.1", duration_days=5,
        color=TaskColor.PURPLE, assigned_to="Grace", parent_wbs="4",
        dependencies=[Dependency(t3_3.id, DependencyType.FINISH_TO_START)],
    ))
    t4_2 = project.add_task(Task(
        name="Bug Fixes", wbs="4.2", duration_days=3,
        color=TaskColor.PURPLE, assigned_to="Eve", parent_wbs="4",
        dependencies=[Dependency(t4_1.id, DependencyType.FINISH_TO_START)],
    ))
    t4_3 = project.add_task(Task(
        name="Launch", wbs="4.3", duration_days=1,
        color=TaskColor.MAGENTA, assigned_to="Charlie", parent_wbs="4",
        is_milestone=True,
        dependencies=[Dependency(t4_2.id, DependencyType.FINISH_TO_START)],
    ))

    # Set some tasks as in progress / completed for demo
    t1_1.status = TaskStatus.COMPLETED
    t1_1.progress = 1.0
    t1_2.status = TaskStatus.COMPLETED
    t1_2.progress = 1.0
    t1_3.status = TaskStatus.COMPLETED
    t1_3.progress = 1.0
    t2_1.status = TaskStatus.COMPLETED
    t2_1.progress = 1.0
    t2_2.status = TaskStatus.IN_PROGRESS
    t2_2.progress = 0.6

    from .app import GanttWarriorApp
    app = GanttWarriorApp(project=project)
    app.run()


def _launch_tui(args) -> None:
    from .app import GanttWarriorApp
    from .models import Project

    file_path = args.file
    project = None

    if args.new:
        project = Project(name=args.new, start_date=date.today())
        if file_path:
            project.file_path = file_path

    app = GanttWarriorApp(project=project, file_path=file_path)
    app.run()


if __name__ == "__main__":
    main()

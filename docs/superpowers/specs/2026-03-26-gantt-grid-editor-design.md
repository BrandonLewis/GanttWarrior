# Gantt Grid Editor — Design Spec

## Overview

Transform the Gantt chart from a read-only visualization into an editable cell grid with text-editor-like keyboard interaction. Each cell represents one task × day intersection. Users paint work days directly onto the grid — fill, erase, cut, copy, paste, split — with full undo support.

## Core Concept

The chart is a 2D grid: rows are tasks, columns are time units. A filled cell means work happens that day. An empty cell means no work. The user edits the schedule by navigating the grid and painting cells, like a pixel editor. What you see on the chart is the literal truth of when work happens — gaps, skips, and all.

## Data Model Changes

### Task Additions

```python
@dataclass
class Task:
    # ... existing fields ...

    work_days: set[date] = field(default_factory=set)
    # The authoritative set of dates when this task has scheduled work.
    # Replaces duration_days as the source of truth for scheduling.
    # Gaps in the set represent non-working days for this task.

    work_weekdays: Optional[set[int]] = None
    # Override project default working weekdays for this task.
    # e.g., {5, 6} for Saturday-Sunday only tasks.
    # None = use project default.

    manually_edited: bool = False
    # Set to True when the user directly edits work_days via the grid.
    # Prevents the scheduler from overwriting user edits on reschedule.
```

**Computed properties** (replace stored fields):
- `duration_days` → `len(self.work_days)`
- `start_date` → `min(self.work_days)` if work_days else None
- `end_date` → `max(self.work_days)` if work_days else None

**Migration**: existing tasks with `start_date`, `end_date`, and `duration_days` are migrated on load by expanding the date range into `work_days`, filtering through the project work calendar.

### Project Additions

```python
@dataclass
class Project:
    # ... existing fields ...

    default_work_weekdays: set[int] = field(default_factory=lambda: {0, 1, 2, 3, 4})
    # Monday=0 through Friday=4. Default is Mon-Fri.

    holidays: set[date] = field(default_factory=set)
    # Project-wide non-working dates (specific dates, not recurring).
```

**Work calendar resolution** for a given task + date:
1. If the task has `work_weekdays`, use that; otherwise use `project.default_work_weekdays`.
2. If the date is in `project.holidays`, it's non-working (unless the task explicitly has it in `work_days` — user intent overrides).
3. If the date's weekday is not in the effective weekday set, it's non-working.

### Serialization

`work_days` serializes as a sorted list of ISO date strings in the JSON file:

```json
{
  "work_days": ["2026-03-25", "2026-03-26", "2026-03-28", "2026-03-31"],
  "work_weekdays": null,
  "manually_edited": false
}
```

`project.holidays` and `project.default_work_weekdays` serialize similarly at the project level.

Backward compatibility: if `work_days` is absent on load, expand from `start_date` + `duration_days` using the project calendar.

## Zoom Levels

Three zoom levels control the time granularity of the grid:

| Zoom    | Column width | Description                              |
|---------|-------------|------------------------------------------|
| Day     | 1 day       | Fine-grained editing, default view       |
| Half-week | ~3 days   | Mon-Wed / Thu-Fri blocks                 |
| Week    | 1 week      | Rough planning, big-picture scheduling   |

### Behavior at Coarse Zoom

**Painting at coarse zoom auto-expands to work days.** Filling a week cell populates `work_days` with all valid work-calendar days in that week (e.g., 5 days for Mon-Fri default). Erasing a week cell removes all work days in that week.

**Zooming in reveals the auto-assigned days.** The task doesn't track what zoom level it was painted at. `work_days` is always the source of truth. Users zoom to day view to fine-tune.

**Toggle zoom:** `+` zooms in (week → half-week → day), `-` zooms out (day → half-week → week).

### Half-Week Split

Each week divides into two blocks:
- **First half:** Monday through Wednesday (3 days)
- **Second half:** Thursday through Friday (2 days)

For task-level weekend overrides (e.g., Sat-Sun workers), the half-week split adjusts to the task's effective work weekdays.

## Keyboard Map

### Navigation

| Key                  | Action                                    |
|----------------------|-------------------------------------------|
| ↑ ↓ ← →             | Move cursor one cell (task / time unit)   |
| Ctrl+← / Ctrl+→     | Jump 7 days (one week)                    |
| Home / End           | Jump to start / end of current task's bar |
| Ctrl+Home / Ctrl+End | Jump to first / last day of project       |
| Tab / Shift+Tab      | Jump to next / previous task's bar start  |
| Page Up / Page Down  | Scroll chart vertically                   |

### Selection

| Key                    | Action                                |
|------------------------|---------------------------------------|
| Shift+← / Shift+→     | Extend/shrink selection by one cell   |
| Shift+Home / Shift+End | Select from cursor to bar start/end  |
| Ctrl+A                 | Select entire current task bar        |

Selection is always a contiguous horizontal range on a single task row. No multi-row selection in this version.

### Editing

| Key                   | Action                                              |
|-----------------------|-----------------------------------------------------|
| Space / Enter         | Fill cell (add day to task's work_days)             |
| Delete / Backspace    | Erase cell (remove day from work_days)              |
| Ctrl+C                | Copy selection (or whole bar if no selection)        |
| Ctrl+X                | Cut selection (copy + erase)                         |
| Ctrl+V / Shift+Insert | Paste at cursor onto current task row               |
| Ctrl+Shift+V          | Paste as new task (creates task with default name)   |
| Ctrl+Z                | Undo                                                 |
| Ctrl+Y                | Redo                                                 |

### Task Operations

| Key    | Action                                           |
|--------|--------------------------------------------------|
| Ctrl+K | Split task at cursor into two tasks              |
| Ctrl+M | Merge current task with next task                |
| Ctrl+D | Duplicate task on a new row                      |

### Zoom

| Key | Action                                    |
|-----|-------------------------------------------|
| +   | Zoom in (week → half-week → day)          |
| -   | Zoom out (day → half-week → week)         |

## Editing Semantics

### Fill (Space/Enter)

- Cursor on empty cell within a task's span → adds that date to `work_days`.
- Cursor on empty cell outside any task's span → extends the nearest bar edge of the current row's task to include this date (fills the gap between bar and cursor).
- Cursor on already-filled cell → no-op.
- With selection: fills all selected cells.
- Sets `manually_edited = True` on the task.

### Erase (Delete/Backspace)

- Cursor on filled cell → removes that date from `work_days`. Duration shrinks. A gap appears if the removed day was in the middle.
- Cursor on empty cell → no-op.
- With selection: erases all selected cells.
- Sets `manually_edited = True` on the task.

### Copy (Ctrl+C)

- With selection: copies the selected date range as a list of relative day offsets (which days within the range have work). E.g., selecting Mon-Fri where Wed is a gap copies `[0, 1, 3, 4]` (relative offsets of work days).
- No selection: copies the entire bar.

### Cut (Ctrl+X)

- Same as copy, then erases the selected/all cells.

### Paste (Ctrl+V / Shift+Insert)

- Pastes the copied day pattern starting at the cursor position onto the current task row.
- The relative offsets are applied from the cursor date. Work calendar is **not** re-applied — paste is literal (the user is explicitly placing work on these days).
- If the target row is a different task than the source, the days are added to the target task's `work_days`. The source task is not modified (that already happened at cut time, if applicable).

### Paste as New Task (Ctrl+Shift+V)

- Creates a new task with name "Task (from {source_task_name})".
- Populates `work_days` from the clipboard pattern starting at cursor date.
- Inserts the task after the current row.
- User can rename later with `e` (edit).

### Split (Ctrl+K)

- Cursor must be on a filled cell within a task's bar.
- Creates two tasks from the original:
  - **Task A**: all `work_days` before the cursor date.
  - **Task B**: cursor date and all `work_days` on or after it.
- Task A keeps the original name. Task B gets "{name} (continued)".
- Task A keeps original dependencies. Task B gets a FS dependency on Task A.
- WBS is reassigned: if original was "2.1", Task A stays "2.1", Task B becomes "2.2" (subsequent tasks renumber).

### Merge (Ctrl+M)

- Merges the current task with the next task in the list.
- Combined `work_days` is the union of both sets.
- Keeps the current task's name, color, and dependencies.
- Absorbs the next task's dependencies (predecessors of the next task become predecessors of the merged task, but only if they don't create cycles).

## Visual Rendering

### Cell States

| Visual | Meaning                                      |
|--------|----------------------------------------------|
| `██`   | Filled work day                              |
| `░░`   | Unfilled day within bar span (schedulable)   |
| `··`   | Task skip day (gap — explicitly removed)     |
| ` · `  | Project non-working day (weekend/holiday)    |
| `▓▓`   | Cursor position (highlighted)                |
| `▒▒`   | Selected range                               |

### Weekend/Holiday Columns

Non-working day columns render with a dimmed marker so the grid stays aligned. Tasks with overridden `work_weekdays` that include those days show filled cells normally.

### Cursor Rendering

The cursor cell gets a distinct background color (e.g., amber/highlight). The current row also gets a subtle highlight. The selected range gets a secondary highlight color.

### Info Panel

The bottom info panel updates to show cursor context:
- Task name, cursor date, whether the cell is filled
- Task duration (work days count), span (start to end), gaps count

## Undo System

### Design

- Each user action (fill, erase, cut, paste, split, merge) pushes one entry onto the undo stack.
- An undo entry stores: task ID(s) affected, previous `work_days` snapshot(s), and for structural changes (split/merge) the previous task list state.
- Ctrl+Z pops from undo stack, pushes to redo stack, restores state.
- Ctrl+Y pops from redo stack, pushes to undo stack, re-applies.
- Any new edit clears the redo stack.
- Save (`s`) clears both undo and redo stacks.

### Granularity

One undo step per user-initiated action:
- Filling a single cell = 1 step
- Filling a selection of 10 cells = 1 step
- Cut + paste = 2 steps (cut is one, paste is one)
- Split = 1 step

## Scheduler Integration

- The scheduler reads `work_days` as the authoritative schedule for each task.
- When rescheduling (`r`), tasks with `manually_edited = True` keep their `work_days` untouched. The scheduler only adjusts their computed scheduling metadata (early_start, late_finish, float, critical path).
- Tasks with `manually_edited = False` can have their `work_days` regenerated from dependencies and the work calendar.
- New tasks added via the `a` dialog auto-populate `work_days` by expanding `duration_days` across the work calendar starting from the assigned start date.

## Implementation Scope

### In Scope

- Cell-grid cursor with visual highlight on GanttChart
- Shift+arrow selection
- Fill / erase / cut / copy / paste (same-task and cross-task)
- Paste-as-new-task (Ctrl+Shift+V)
- Split (Ctrl+K) and merge (Ctrl+M)
- Duplicate (Ctrl+D)
- Undo/redo (unlimited until save)
- `work_days` set on Task, `duration_days` as computed property
- `work_weekdays` override on Task
- Project `default_work_weekdays` + `holidays`
- Weekend/holiday column rendering with dimmed markers
- Zoom levels: day / half-week / week with `+`/`-` toggle
- Paint-at-coarse-zoom auto-expands to work calendar days
- `manually_edited` flag, scheduler respects it
- Serialization and backward-compatible migration
- Info panel updates with cursor context

### Deferred

- Hour-level granularity
- Mouse drag-and-drop bar moving
- Multi-row selection (selecting across multiple tasks)
- Recurring task patterns
- Month zoom level

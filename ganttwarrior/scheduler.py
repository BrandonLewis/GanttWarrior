"""Critical Path Method (CPM) scheduler with task blocking and dependency resolution."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

from .models import DependencyType, Project, Task, TaskStatus


class SchedulerError(Exception):
    pass


class Scheduler:
    """Implements the Critical Path Method for project scheduling."""

    def __init__(self, project: Project):
        self.project = project
        self._task_map: dict[str, Task] = {}
        self._successors: dict[str, list[str]] = defaultdict(list)
        self._predecessors: dict[str, list[str]] = defaultdict(list)

    def _build_graph(self) -> None:
        self._task_map = {t.id: t for t in self.project.tasks}
        self._successors = defaultdict(list)
        self._predecessors = defaultdict(list)

        for task in self.project.tasks:
            for dep in task.dependencies:
                if dep.predecessor_id in self._task_map:
                    self._successors[dep.predecessor_id].append(task.id)
                    self._predecessors[task.id].append(dep.predecessor_id)

    def _detect_cycles(self) -> list[str]:
        """Detect circular dependencies using DFS. Returns the cycle segment if found."""
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {tid: WHITE for tid in self._task_map}
        path: list[str] = []
        cycle: list[str] = []

        def dfs(node: str) -> bool:
            nonlocal cycle
            color[node] = GRAY
            path.append(node)
            for succ in self._successors.get(node, []):
                if color[succ] == GRAY:
                    cycle_start = path.index(succ)
                    cycle = path[cycle_start:] + [succ]
                    return True
                if color[succ] == WHITE and dfs(succ):
                    return True
            path.pop()
            color[node] = BLACK
            return False

        for tid in self._task_map:
            if color[tid] == WHITE:
                if dfs(tid):
                    return cycle
        return []

    def _topological_sort(self) -> list[str]:
        """Return task IDs in topological order."""
        in_degree = {tid: 0 for tid in self._task_map}
        for tid in self._task_map:
            for dep in self._task_map[tid].dependencies:
                if dep.predecessor_id in self._task_map:
                    in_degree[tid] += 1

        queue = [tid for tid, deg in in_degree.items() if deg == 0]
        result = []

        while queue:
            # Sort queue by WBS for deterministic ordering
            queue.sort(key=lambda tid: self._task_map[tid].wbs_parts or [999])
            node = queue.pop(0)
            result.append(node)
            for succ in self._successors.get(node, []):
                in_degree[succ] -= 1
                if in_degree[succ] == 0:
                    queue.append(succ)

        if len(result) != len(self._task_map):
            raise SchedulerError("Circular dependency detected - cannot schedule")
        return result

    def forward_pass(self, project_start: Optional[date] = None) -> None:
        """Calculate early start and early finish for all tasks."""
        start = project_start or self.project.start_date or date.today()
        order = self._topological_sort()

        for tid in order:
            task = self._task_map[tid]
            earliest = start

            for dep in task.dependencies:
                pred = self._task_map.get(dep.predecessor_id)
                if not pred or pred.early_finish is None:
                    continue

                lag = timedelta(days=dep.lag_days)

                if dep.dependency_type == DependencyType.FINISH_TO_START:
                    candidate = pred.early_finish + timedelta(days=1) + lag
                elif dep.dependency_type == DependencyType.START_TO_START:
                    candidate = pred.early_start + lag if pred.early_start else start
                elif dep.dependency_type == DependencyType.FINISH_TO_FINISH:
                    ef = pred.early_finish + lag if pred.early_finish else start
                    candidate = ef - timedelta(days=max(task.duration_days - 1, 0))
                elif dep.dependency_type == DependencyType.START_TO_FINISH:
                    candidate = (pred.early_start + lag - timedelta(days=max(task.duration_days - 1, 0))
                                 if pred.early_start else start)
                else:
                    candidate = start

                if candidate > earliest:
                    earliest = candidate

            # Respect manually set start dates
            if task.start_date and task.start_date > earliest:
                earliest = task.start_date

            task.early_start = earliest
            task.early_finish = earliest + timedelta(days=max(task.duration_days - 1, 0))

            # Update the task's actual dates
            task.start_date = task.early_start
            task.end_date = task.early_finish

    def backward_pass(self) -> None:
        """Calculate late start, late finish, and float for all tasks."""
        order = self._topological_sort()

        # Find project end date
        project_end = max(
            (t.early_finish for t in self._task_map.values() if t.early_finish),
            default=date.today(),
        )

        # Process in reverse order
        for tid in reversed(order):
            task = self._task_map[tid]
            latest_finish = project_end

            for succ_id in self._successors.get(tid, []):
                succ = self._task_map[succ_id]
                if succ.late_start is None:
                    continue

                for dep in succ.dependencies:
                    if dep.predecessor_id != tid:
                        continue
                    lag = timedelta(days=dep.lag_days)

                    if dep.dependency_type == DependencyType.FINISH_TO_START:
                        candidate = succ.late_start - timedelta(days=1) - lag
                    elif dep.dependency_type == DependencyType.START_TO_START:
                        candidate = succ.late_start - lag + timedelta(days=max(task.duration_days - 1, 0))
                    elif dep.dependency_type == DependencyType.FINISH_TO_FINISH:
                        candidate = succ.late_finish - lag if succ.late_finish else project_end
                    elif dep.dependency_type == DependencyType.START_TO_FINISH:
                        candidate = (succ.late_finish - lag + timedelta(days=max(task.duration_days - 1, 0))
                                     if succ.late_finish else project_end)
                    else:
                        candidate = project_end

                    if candidate < latest_finish:
                        latest_finish = candidate

            task.late_finish = latest_finish
            task.late_start = latest_finish - timedelta(days=max(task.duration_days - 1, 0))
            task.total_float = (task.late_start - task.early_start).days if task.early_start and task.late_start else 0

    def identify_critical_path(self) -> list[Task]:
        """Mark tasks on the critical path (float == 0)."""
        critical = []
        for task in self.project.tasks:
            task.is_critical = task.total_float == 0
            if task.is_critical:
                critical.append(task)
        return sorted(critical, key=lambda t: t.early_start or date.today())

    def update_blocking(self) -> None:
        """Update blocked status based on dependency completion."""
        self.project.update_blocked_status()

    def schedule(self, project_start: Optional[date] = None) -> list[Task]:
        """Run the full scheduling algorithm. Returns critical path tasks."""
        self._build_graph()

        cycle = self._detect_cycles()
        if cycle:
            names = [self._task_map[tid].name for tid in cycle if tid in self._task_map]
            raise SchedulerError(f"Circular dependency: {' -> '.join(names)}")

        self.forward_pass(project_start)
        self.backward_pass()
        critical = self.identify_critical_path()
        self.update_blocking()
        return critical

    def get_critical_path_duration(self) -> int:
        """Get total project duration in days based on critical path."""
        starts = [t.early_start for t in self.project.tasks if t.early_start and t.is_critical]
        ends = [t.early_finish for t in self.project.tasks if t.early_finish and t.is_critical]
        if not starts or not ends:
            return 0
        return (max(ends) - min(starts)).days + 1

    def get_blocked_tasks(self) -> list[Task]:
        return [t for t in self.project.tasks if t.status == TaskStatus.BLOCKED]

    def get_ready_tasks(self) -> list[Task]:
        """Tasks whose dependencies are all met and are not started."""
        ready = []
        for task in self.project.tasks:
            if task.status != TaskStatus.NOT_STARTED:
                continue
            all_met = True
            for dep in task.dependencies:
                pred = self.project.get_task(dep.predecessor_id)
                if pred and dep.dependency_type == DependencyType.FINISH_TO_START:
                    if pred.status != TaskStatus.COMPLETED:
                        all_met = False
                        break
            if all_met:
                ready.append(task)
        return ready

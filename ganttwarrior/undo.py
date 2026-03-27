"""Undo/redo stack for tracking grid editor operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class UndoEntry:
    """A single undoable operation."""

    task_ids: list[str]
    before: dict[str, frozenset[date]]
    after: dict[str, frozenset[date]]
    description: str
    before_tasks: Optional[list] = None
    after_tasks: Optional[list] = None


class UndoStack:
    """Undo/redo stack for editor operations."""

    def __init__(self) -> None:
        self._undo: list[UndoEntry] = []
        self._redo: list[UndoEntry] = []

    def push(self, entry: UndoEntry) -> None:
        """Add an entry to the undo stack, clearing the redo stack."""
        self._undo.append(entry)
        self._redo.clear()

    def undo(self) -> Optional[UndoEntry]:
        """Pop from undo, push to redo, and return the entry (or None if empty)."""
        if not self._undo:
            return None
        entry = self._undo.pop()
        self._redo.append(entry)
        return entry

    def redo(self) -> Optional[UndoEntry]:
        """Pop from redo, push to undo, and return the entry (or None if empty)."""
        if not self._redo:
            return None
        entry = self._redo.pop()
        self._undo.append(entry)
        return entry

    @property
    def can_undo(self) -> bool:
        """Whether there are entries available to undo."""
        return len(self._undo) > 0

    @property
    def can_redo(self) -> bool:
        """Whether there are entries available to redo."""
        return len(self._redo) > 0

    def clear(self) -> None:
        """Clear both undo and redo stacks."""
        self._undo.clear()
        self._redo.clear()

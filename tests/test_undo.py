"""Tests for undo/redo stack."""
from datetime import date
import pytest
from ganttwarrior.undo import UndoEntry, UndoStack

class TestUndoStack:
    def test_push_and_undo(self):
        stack = UndoStack()
        entry = UndoEntry(task_ids=["t1"], before={"t1": frozenset({date(2026, 3, 25)})}, after={"t1": frozenset({date(2026, 3, 25), date(2026, 3, 26)})}, description="fill")
        stack.push(entry)
        assert stack.can_undo
        undone = stack.undo()
        assert undone is entry
        assert not stack.can_undo

    def test_undo_then_redo(self):
        stack = UndoStack()
        entry = UndoEntry(task_ids=["t1"], before={"t1": frozenset({date(2026, 3, 25)})}, after={"t1": frozenset({date(2026, 3, 25), date(2026, 3, 26)})}, description="fill")
        stack.push(entry)
        stack.undo()
        assert stack.can_redo
        redone = stack.redo()
        assert redone is entry

    def test_new_edit_clears_redo(self):
        stack = UndoStack()
        e1 = UndoEntry(task_ids=["t1"], before={}, after={}, description="e1")
        e2 = UndoEntry(task_ids=["t1"], before={}, after={}, description="e2")
        stack.push(e1)
        stack.undo()
        assert stack.can_redo
        stack.push(e2)
        assert not stack.can_redo

    def test_clear(self):
        stack = UndoStack()
        stack.push(UndoEntry(task_ids=["t1"], before={}, after={}, description="x"))
        stack.clear()
        assert not stack.can_undo
        assert not stack.can_redo

    def test_undo_empty_returns_none(self):
        stack = UndoStack()
        assert stack.undo() is None

    def test_redo_empty_returns_none(self):
        stack = UndoStack()
        assert stack.redo() is None

    def test_multiple_undos(self):
        stack = UndoStack()
        e1 = UndoEntry(task_ids=["t1"], before={}, after={}, description="e1")
        e2 = UndoEntry(task_ids=["t1"], before={}, after={}, description="e2")
        e3 = UndoEntry(task_ids=["t1"], before={}, after={}, description="e3")
        stack.push(e1)
        stack.push(e2)
        stack.push(e3)
        assert stack.undo() is e3
        assert stack.undo() is e2
        assert stack.undo() is e1
        assert stack.undo() is None

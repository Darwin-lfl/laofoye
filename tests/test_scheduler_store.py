from __future__ import annotations

from datetime import UTC, datetime, timedelta

from scheduler.store import TaskStore
from scheduler.types import ScheduledTask


def _task(task_id: str, next_run: datetime) -> ScheduledTask:
    return ScheduledTask(
        id=task_id,
        chat_id="chat-1",
        prompt="send report",
        schedule_type="once",
        schedule_value=next_run.isoformat(),
        next_run=next_run,
        last_run=None,
        last_result=None,
        status="active",
        created_at=datetime.now(UTC),
    )


def test_task_store_add_list_remove(tmp_path):
    store = TaskStore(tmp_path / "schedules.json")
    run_at = datetime.now(UTC) + timedelta(minutes=10)
    task = _task("task-1", run_at)

    store.add(task)

    tasks = store.load()
    assert len(tasks) == 1
    assert tasks[0].id == "task-1"

    assert store.remove("task-1") is True
    assert store.remove("task-1") is False


def test_task_store_due_filter(tmp_path):
    store = TaskStore(tmp_path / "schedules.json")
    now = datetime.now(UTC)
    store.add(_task("due", now - timedelta(seconds=1)))
    store.add(_task("future", now + timedelta(minutes=5)))

    due = store.get_due(now)

    assert [task.id for task in due] == ["due"]

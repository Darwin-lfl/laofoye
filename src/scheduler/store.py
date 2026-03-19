from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from croniter import croniter

from scheduler.types import ScheduledTask


class TaskStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> list[ScheduledTask]:
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return [ScheduledTask.from_dict(item) for item in data]

    def save(self, tasks: list[ScheduledTask]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(
            json.dumps([task.to_dict() for task in tasks], indent=2),
            encoding="utf-8",
        )
        temp.replace(self.path)

    def add(self, task: ScheduledTask) -> None:
        tasks = self.load()
        tasks.append(task)
        self.save(tasks)

    def remove(self, task_id: str) -> bool:
        tasks = self.load()
        idx = next((i for i, item in enumerate(tasks) if item.id == task_id or item.id.startswith(task_id)), -1)
        if idx < 0:
            return False
        tasks.pop(idx)
        self.save(tasks)
        return True

    def update(self, task_id: str, **updates: object) -> bool:
        tasks = self.load()
        for task in tasks:
            if task.id == task_id:
                for key, value in updates.items():
                    setattr(task, key, value)
                self.save(tasks)
                return True
        return False

    def get(self, task_id: str) -> ScheduledTask | None:
        return next((task for task in self.load() if task.id == task_id or task.id.startswith(task_id)), None)

    def get_due(self, now: datetime | None = None) -> list[ScheduledTask]:
        ts = now or datetime.now(UTC)
        due: list[ScheduledTask] = []
        for task in self.load():
            if task.status != "active" or task.next_run is None:
                continue
            if task.next_run <= ts:
                due.append(task)
        return due


def compute_next_run(schedule_type: str, schedule_value: str, now: datetime | None = None) -> datetime | None:
    ts = now or datetime.now(UTC)
    if schedule_type == "once":
        candidate = datetime.fromisoformat(schedule_value)
        if candidate.tzinfo is None:
            candidate = candidate.replace(tzinfo=UTC)
        return candidate if candidate > ts else None

    if schedule_type == "cron":
        itr = croniter(schedule_value, ts)
        value = itr.get_next(datetime)
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value

    return None

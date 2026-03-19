from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


TaskStatus = Literal["active", "paused", "completed"]
ScheduleType = Literal["cron", "once"]


@dataclass(slots=True)
class ScheduledTask:
    id: str
    chat_id: str
    prompt: str
    schedule_type: ScheduleType
    schedule_value: str
    next_run: datetime | None
    last_run: datetime | None
    last_result: str | None
    status: TaskStatus
    created_at: datetime

    def to_dict(self) -> dict[str, str | None]:
        return {
            "id": self.id,
            "chat_id": self.chat_id,
            "prompt": self.prompt,
            "schedule_type": self.schedule_type,
            "schedule_value": self.schedule_value,
            "next_run": self.next_run.isoformat() if self.next_run else None,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "last_result": self.last_result,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, str | None]) -> "ScheduledTask":
        return cls(
            id=str(data["id"]),
            chat_id=str(data["chat_id"]),
            prompt=str(data["prompt"]),
            schedule_type=str(data["schedule_type"]),
            schedule_value=str(data["schedule_value"]),
            next_run=datetime.fromisoformat(data["next_run"]) if data.get("next_run") else None,
            last_run=datetime.fromisoformat(data["last_run"]) if data.get("last_run") else None,
            last_result=data.get("last_result"),
            status=str(data["status"]),
            created_at=datetime.fromisoformat(str(data["created_at"])),
        )

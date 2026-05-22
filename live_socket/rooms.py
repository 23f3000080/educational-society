from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from time import time
from typing import Any


@dataclass
class RoomParticipant:
    socket_id: str
    user_id: int
    name: str
    role: str
    hand_raised: bool = False
    speaking: bool = False
    camera_on: bool = True
    mic_on: bool = True
    screen_sharing: bool = False
    joined_at: float = field(default_factory=time)


@dataclass
class RoomState:
    live_class_id: int
    participants: dict[str, RoomParticipant] = field(default_factory=dict)
    chat: list[dict[str, Any]] = field(default_factory=list)
    last_activity: float = field(default_factory=time)


_ROOM_LOCK = Lock()
_ROOMS: dict[int, RoomState] = {}
_SID_INDEX: dict[str, int] = {}


def _room_key(live_class_id: int) -> int:
    return int(live_class_id)


def get_or_create_room(live_class_id: int) -> RoomState:
    key = _room_key(live_class_id)
    with _ROOM_LOCK:
        room = _ROOMS.get(key)
        if room is None:
            room = RoomState(live_class_id=key)
            _ROOMS[key] = room
        room.last_activity = time()
        return room


def get_room_snapshot(live_class_id: int) -> dict[str, Any]:
    with _ROOM_LOCK:
        room = _ROOMS.get(_room_key(live_class_id))
        if room is None:
            return {"participant_count": 0, "participants": [], "chat": []}

        return {
            "participant_count": len(room.participants),
            "participants": [serialize_participant(p) for p in room.participants.values()],
            "chat": list(room.chat[-50:]),
        }


def get_participants_snapshot(live_class_id: int) -> list[dict[str, Any]]:
    with _ROOM_LOCK:
        room = _ROOMS.get(_room_key(live_class_id))
        if room is None:
            return []
        return [serialize_participant(p) for p in room.participants.values()]


def serialize_participant(participant: RoomParticipant) -> dict[str, Any]:
    return {
        "socket_id": participant.socket_id,
        "user_id": participant.user_id,
        "name": participant.name,
        "role": participant.role,
        "hand_raised": participant.hand_raised,
        "speaking": participant.speaking,
        "camera_on": participant.camera_on,
        "mic_on": participant.mic_on,
        "screen_sharing": participant.screen_sharing,
        "joined_at": participant.joined_at,
    }


def add_participant(
    live_class_id: int,
    socket_id: str,
    user_id: int,
    name: str,
    role: str,
) -> RoomParticipant:
    room = get_or_create_room(live_class_id)
    participant = RoomParticipant(
        socket_id=socket_id,
        user_id=user_id,
        name=name,
        role=role,
    )

    with _ROOM_LOCK:
        room.participants[socket_id] = participant
        room.last_activity = time()
        _SID_INDEX[socket_id] = _room_key(live_class_id)

    return participant


def remove_participant(socket_id: str) -> tuple[int | None, RoomParticipant | None, int]:
    with _ROOM_LOCK:
        live_class_id = _SID_INDEX.pop(socket_id, None)
        if live_class_id is None:
            return None, None, 0

        room = _ROOMS.get(live_class_id)
        if room is None:
            return live_class_id, None, 0

        participant = room.participants.pop(socket_id, None)
        room.last_activity = time()
        participant_count = len(room.participants)

        if participant_count == 0 and not room.chat:
            _ROOMS.pop(live_class_id, None)

        return live_class_id, participant, participant_count


def get_live_class_id_for_socket(socket_id: str) -> int | None:
    with _ROOM_LOCK:
        return _SID_INDEX.get(socket_id)


def update_participant_state(socket_id: str, **updates: Any) -> dict[str, Any] | None:
    with _ROOM_LOCK:
        live_class_id = _SID_INDEX.get(socket_id)
        if live_class_id is None:
            return None

        room = _ROOMS.get(live_class_id)
        if room is None:
            return None

        participant = room.participants.get(socket_id)
        if participant is None:
            return None

        for key, value in updates.items():
            if hasattr(participant, key):
                setattr(participant, key, value)

        room.last_activity = time()
        return serialize_participant(participant)


def append_chat_message(live_class_id: int, message: dict[str, Any]) -> dict[str, Any]:
    room = get_or_create_room(live_class_id)
    with _ROOM_LOCK:
        room.chat.append(message)
        room.chat = room.chat[-50:]
        room.last_activity = time()
    return message


def cleanup_idle_rooms(max_idle_seconds: int = 7200) -> None:
    """Best-effort cleanup for rooms that no longer have participants."""
    now = time()
    with _ROOM_LOCK:
        stale_rooms = [
            room_id
            for room_id, room in _ROOMS.items()
            if not room.participants and (now - room.last_activity) > max_idle_seconds
        ]
        for room_id in stale_rooms:
            _ROOMS.pop(room_id, None)

from __future__ import annotations

from datetime import datetime, timezone

import jwt
from flask import current_app, request
from flask_socketio import SocketIO, emit, join_room, leave_room

from models import Course, Enrollment, LiveClass, User, db
from live_socket.rooms import (
    add_participant,
    append_chat_message,
    get_live_class_id_for_socket,
    get_or_create_room,
    get_participants_snapshot,
    get_room_snapshot,
    remove_participant,
    serialize_participant,
    update_participant_state,
)

socketio = SocketIO(
    cors_allowed_origins="*",
    async_mode="eventlet",
    logger=False,
    engineio_logger=False,
    manage_session=False,
    ping_interval=25,
    ping_timeout=20,
)

SID_CONTEXT: dict[str, dict] = {}


def init_socketio(app):
    socketio.init_app(app, cors_allowed_origins="*")
    return socketio


def _room_name(live_class_id: int) -> str:
    return f"live-class-{live_class_id}"


def _decode_token(token: str):
    if not token:
        return None

    try:
        payload = jwt.decode(
            token,
            current_app.config["SECRET_KEY"],
            algorithms=["HS256"],
        )
        user = User.query.get(payload.get("user_id"))
        if not user or not user.active:
            return None
        return user
    except Exception:
        return None


def _role_name(user: User) -> str:
    roles = [role.name for role in user.roles]
    return roles[0] if roles else "user"


def _student_course_ids(user_id: int) -> list[int]:
    return [
        enrollment.course_id
        for enrollment in Enrollment.query.filter_by(
            student_id=user_id,
            payment_status="paid",
            enrollment_status="active",
        ).all()
    ]


def _can_access_live_class(user: User, live_class: LiveClass) -> bool:
    if _role_name(user) == "admin":
        return True

    if live_class.status == "Cancelled":
        return False

    return live_class.course_id in set(_student_course_ids(user.id))


def _serialize_room_state(live_class: LiveClass, user: User):
    room_snapshot = get_room_snapshot(live_class.id)
    return {
        "live_class": {
            "id": live_class.id,
            "course_id": live_class.course_id,
            "course_title": live_class.course.title if live_class.course else None,
            "room_id": f"LC-{live_class.id}",
            "title": live_class.title,
            "description": live_class.description,
            "start_time": live_class.start_time.isoformat() if live_class.start_time else None,
            "end_time": live_class.end_time.isoformat() if live_class.end_time else None,
            "meeting_link": live_class.meeting_link,
            "instructor_name": live_class.instructor_name,
            "status": live_class.status,
            "message": live_class.message,
            "created_at": live_class.created_at.isoformat() if live_class.created_at else None,
            "updated_at": live_class.updated_at.isoformat() if live_class.updated_at else None,
        },
        "room": {
            "room_id": f"LC-{live_class.id}",
            "participant_count": room_snapshot["participant_count"],
            "participants": room_snapshot["participants"],
            "chat": room_snapshot["chat"],
        },
        "current_user": {
            "id": user.id,
            "name": f"{user.first_name} {user.last_name or ''}".strip(),
            "role": _role_name(user),
        },
    }


@socketio.on("connect")
def handle_connect(auth=None):
    token = (auth or {}).get("token") or request.args.get("token")
    user = _decode_token(token)
    if not user:
        return False

    SID_CONTEXT[request.sid] = {
        "user_id": user.id,
        "user_name": f"{user.first_name} {user.last_name or ''}".strip(),
        "role": _role_name(user),
        "live_class_id": None,
        "mic_on": True,
        "camera_on": True,
        "screen_sharing": False,
        "hand_raised": False,
    }

    emit("socket:connected", {"socket_id": request.sid})


@socketio.on("join-room")
def handle_join_room(payload):
    context = SID_CONTEXT.get(request.sid)
    if not context:
        emit("room:error", {"message": "Not authenticated"})
        return

    live_class_id = int((payload or {}).get("live_class_id") or 0)
    live_class = LiveClass.query.get(live_class_id)
    if not live_class:
        emit("room:error", {"message": "Live class not found"})
        return

    user = User.query.get(context["user_id"])
    if not user or not _can_access_live_class(user, live_class):
        emit("room:error", {"message": "You are not allowed to join this room"})
        return

    room_name = _room_name(live_class_id)
    existing_participants = get_participants_snapshot(live_class_id)

    join_room(room_name)
    participant = add_participant(
        live_class_id=live_class_id,
        socket_id=request.sid,
        user_id=user.id,
        name=context["user_name"],
        role=context["role"],
    )

    context["live_class_id"] = live_class_id
    context["room_name"] = room_name

    emit("room:ready", _serialize_room_state(live_class, user), to=request.sid)
    emit("room:existing-participants", {"participants": existing_participants}, to=request.sid)
    emit("room:participant-joined", {"participant": serialize_participant(participant)}, to=room_name, include_self=False)
    emit("room:participants", {"participants": get_room_snapshot(live_class_id)["participants"]}, to=room_name)
    emit("room:participant-count", {"count": get_room_snapshot(live_class_id)["participant_count"]}, to=room_name)


@socketio.on("signal")
def handle_signal(payload):
    target_socket_id = (payload or {}).get("target_socket_id")
    if not target_socket_id:
        return

    emit(
        "signal",
        {
            "from_socket_id": request.sid,
            "signal": (payload or {}).get("signal"),
        },
        to=target_socket_id,
    )


@socketio.on("chat-message")
def handle_chat_message(payload):
    context = SID_CONTEXT.get(request.sid)
    live_class_id = context.get("live_class_id") if context else None
    if not live_class_id:
        return

    message_text = str((payload or {}).get("message") or "").strip()
    if not message_text:
        return

    user = User.query.get(context["user_id"])
    if not user:
        return

    message = {
        "id": f"chat-{int(datetime.now(timezone.utc).timestamp() * 1000)}",
        "live_class_id": live_class_id,
        "socket_id": request.sid,
        "user_id": user.id,
        "name": context["user_name"],
        "role": context["role"],
        "message": message_text,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    append_chat_message(live_class_id, message)
    emit("chat-message", message, to=_room_name(live_class_id))


@socketio.on("participant-state")
def handle_participant_state(payload):
    context = SID_CONTEXT.get(request.sid)
    live_class_id = context.get("live_class_id") if context else None
    if not live_class_id:
        return

    updates = {
        "mic_on": bool((payload or {}).get("mic_on", True)),
        "camera_on": bool((payload or {}).get("camera_on", True)),
        "screen_sharing": bool((payload or {}).get("screen_sharing", False)),
        "hand_raised": bool((payload or {}).get("hand_raised", False)),
        "speaking": bool((payload or {}).get("speaking", False)),
    }
    context.update(updates)

    participant = update_participant_state(request.sid, **updates)
    if participant:
        emit("participant-updated", {"participant": participant}, to=_room_name(live_class_id))


@socketio.on("leave-room")
def handle_leave_room(_payload=None):
    _leave_current_room(request.sid)


@socketio.on("disconnect")
def handle_disconnect():
    _leave_current_room(request.sid)
    SID_CONTEXT.pop(request.sid, None)


def _leave_current_room(socket_id: str):
    context = SID_CONTEXT.get(socket_id)
    live_class_id = context.get("live_class_id") if context else get_live_class_id_for_socket(socket_id)
    if not live_class_id:
        return

    room_name = _room_name(live_class_id)
    leave_room(room_name)
    removed_live_class_id, participant, count = remove_participant(socket_id)

    if participant:
        emit(
            "room:participant-left",
            {
                "socket_id": socket_id,
                "user_id": participant.user_id,
                "name": participant.name,
                "role": participant.role,
            },
            to=room_name,
        )
        emit("room:participant-count", {"count": count}, to=room_name)

    if context:
        context["live_class_id"] = None


@socketio.on("room:ping")
def handle_ping(payload):
    emit("room:pong", {"timestamp": datetime.now(timezone.utc).isoformat(), "echo": payload or {}})

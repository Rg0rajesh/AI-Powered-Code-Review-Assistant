"""
LintVertex - Discussion Rooms Routes
Human-only chat via Server-Sent Events (SSE)
No AI in chat — real-time collaboration only
"""
import uuid
import json
import time
import threading
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, Response, stream_with_context
from utils.security import require_auth
import services.supabase_client as db

rooms_bp = Blueprint("rooms", __name__)

# In-memory SSE subscriber registry: {room_id: [queue, queue, ...]}
# Each queue is a list used as a simple message buffer
_room_subscribers: dict[str, list] = {}
_subscribers_lock = threading.Lock()


def _notify_room(room_id: str, event_data: dict):
    """Push event to all subscribers of a room"""
    with _subscribers_lock:
        queues = _room_subscribers.get(room_id, [])
        message = f"data: {json.dumps(event_data)}\n\n"
        for q in queues:
            q.append(message)


def _generate_room_key() -> str:
    """Generate a short unique room key"""
    return str(uuid.uuid4()).replace("-", "")[:10].upper()


# ─── Room Management ──────────────────────────────────────────────────────────

@rooms_bp.route("/api/rooms/create", methods=["POST"])
@require_auth
def create_room():
    data = request.get_json() or {}
    room_name = data.get("room_name", "").strip()

    if not room_name:
        return jsonify({"error": "Room name is required"}), 400
    if len(room_name) > 50:
        return jsonify({"error": "Room name too long (max 50 chars)"}), 400

    user_id = request.user["user_id"]
    room_key = _generate_room_key()

    room_data = {
        "room_name": room_name,
        "room_key": room_key,
        "created_by": user_id,
    }

    result = db.create_room(room_data)
    if not result.data:
        return jsonify({"error": "Failed to create room"}), 500

    room = result.data[0]
    db.join_room(room["id"], user_id)
    db.log_activity(user_id, f"room_created:{room['id']}")

    return jsonify({
        "message": "Room created",
        "room": {
            "id": room["id"],
            "name": room_name,
            "key": room_key,
        }
    }), 201


@rooms_bp.route("/api/rooms/join", methods=["POST"])
@require_auth
def join_room():
    data = request.get_json() or {}
    room_key = data.get("room_key", "").strip().upper()

    if not room_key:
        return jsonify({"error": "Room key is required"}), 400

    user_id = request.user["user_id"]
    room = db.get_room_by_key(room_key)

    if not room:
        return jsonify({"error": "Invalid room key"}), 404

    db.join_room(room["id"], user_id)
    db.log_activity(user_id, f"room_joined:{room['id']}")

    # Load recent messages
    messages_result = db.get_room_messages(room["id"], limit=50)
    messages = []
    for msg in (messages_result.data or []):
        user_data = msg.get("users") or {}
        messages.append({
            "id": msg["id"],
            "message": msg["message"],
            "created_at": msg["created_at"],
            "user": {
                "username": user_data.get("username", "Unknown"),
                "avatar": user_data.get("profile_image"),
            }
        })

    return jsonify({
        "message": "Joined room",
        "room": {
            "id": room["id"],
            "name": room["room_name"],
            "key": room_key,
        },
        "history": messages,
    }), 200


@rooms_bp.route("/api/rooms/my", methods=["GET"])
@require_auth
def my_rooms():
    user_id = request.user["user_id"]
    result = db.get_user_rooms(user_id)

    rooms = []
    for r in (result.data or []):
        room_info = r.get("rooms") or {}
        rooms.append({
            "id": room_info.get("id"),
            "name": room_info.get("room_name"),
            "key": room_info.get("room_key"),
            "created_at": room_info.get("created_at"),
        })

    return jsonify({"rooms": rooms}), 200


# ─── Messaging ────────────────────────────────────────────────────────────────

@rooms_bp.route("/api/rooms/<room_id>/send", methods=["POST"])
@require_auth
def send_message(room_id):
    data = request.get_json() or {}
    message = data.get("message", "").strip()

    if not message:
        return jsonify({"error": "Message is required"}), 400
    if len(message) > 2000:
        return jsonify({"error": "Message too long (max 2000 chars)"}), 400

    user_id = request.user["user_id"]

    # Get user info for display
    user = db.get_user_by_id(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    msg_data = {
        "room_id": room_id,
        "user_id": user_id,
        "message": message,
    }

    result = db.save_message(msg_data)
    if not result.data:
        return jsonify({"error": "Failed to send message"}), 500

    saved_msg = result.data[0]

    # Broadcast to SSE subscribers
    event = {
        "type": "message",
        "id": saved_msg["id"],
        "message": message,
        "created_at": saved_msg["created_at"],
        "user": {
            "id": user_id,
            "username": user["username"],
            "avatar": user.get("profile_image"),
        }
    }
    _notify_room(room_id, event)

    return jsonify({"message": "Sent", "id": saved_msg["id"]}), 200


@rooms_bp.route("/api/rooms/<room_id>/typing", methods=["POST"])
@require_auth
def send_typing(room_id):
    """Broadcast typing indicator via SSE"""
    user = db.get_user_by_id(request.user["user_id"])
    if user:
        _notify_room(room_id, {
            "type": "typing",
            "username": user["username"],
        })
    return jsonify({}), 200


# ─── SSE Stream ───────────────────────────────────────────────────────────────

@rooms_bp.route("/api/rooms/<room_id>/stream")
@require_auth
def stream_room(room_id):
    """SSE endpoint for real-time room updates"""
    user_id = request.user["user_id"]
    queue = []

    with _subscribers_lock:
        if room_id not in _room_subscribers:
            _room_subscribers[room_id] = []
        _room_subscribers[room_id].append(queue)

    # Announce join
    user = db.get_user_by_id(user_id)
    if user:
        _notify_room(room_id, {
            "type": "join",
            "username": user["username"],
        })

    def generate():
        try:
            # Send initial heartbeat
            yield "data: {\"type\": \"connected\"}\n\n"

            last_heartbeat = time.time()
            while True:
                # ── Check for actual messages ─────────────────
                if queue:
                    while queue:
                        msg = queue.pop(0)
                        yield msg
                    last_heartbeat = time.time()

                # ── Heartbeat every 20s (keep conn alive) ─────
                now = time.time()
                if now - last_heartbeat > 20:
                    yield "data: {\"type\": \"ping\"}\n\n"
                    last_heartbeat = now
                
                # ── Brief sleep to prevent CPU spiking ───────
                time.sleep(0.1)
        except GeneratorExit:
            pass
        finally:
            with _subscribers_lock:
                if room_id in _room_subscribers and queue in _room_subscribers[room_id]:
                    _room_subscribers[room_id].remove(queue)
            if user:
                _notify_room(room_id, {
                    "type": "leave",
                    "username": user["username"],
                })

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )

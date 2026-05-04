from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

app = FastAPI(title="Brainstorm Collaboration Server")
ROOT_DIR = Path(__file__).resolve().parent
INDEX_FILE = ROOT_DIR / "index.html"

# Optional for local front-end testing across origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@dataclass
class ClientInfo:
    client_id: str
    role: str
    ws: WebSocket


@dataclass
class RoomInfo:
    clients: dict[str, ClientInfo] = field(default_factory=dict)
    state: dict[str, Any] | None = None
    updated_at: str | None = None


rooms: dict[str, RoomInfo] = {}
rooms_lock = asyncio.Lock()


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "rooms": len(rooms),
        "clients": sum(len(room.clients) for room in rooms.values()),
    }


@app.get("/")
async def serve_index_root() -> FileResponse:
    if not INDEX_FILE.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(INDEX_FILE)


@app.get("/index.html")
async def serve_index_file() -> FileResponse:
    if not INDEX_FILE.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(INDEX_FILE)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_room(raw: str | None) -> str:
    code = (raw or "000000").strip()
    return code if code else "000000"


def normalize_role(raw: str | None) -> str:
    role = (raw or "guest").strip().lower()
    if role not in {"host", "guest"}:
        return "guest"
    return role


def normalize_client_id(raw: str | None, ws: WebSocket) -> str:
    candidate = (raw or "").strip()
    if candidate:
        return candidate
    host = ws.client.host if ws.client else "unknown"
    port = ws.client.port if ws.client else 0
    return f"ws-{host}-{port}-{int(datetime.now().timestamp() * 1000)}"


async def send_json_safe(ws: WebSocket, payload: dict[str, Any]) -> bool:
    try:
        await ws.send_text(json.dumps(payload, ensure_ascii=False))
        return True
    except Exception:
        return False


async def broadcast_presence(room_code: str) -> None:
    async with rooms_lock:
        room = rooms.get(room_code)
        if not room:
            return
        peers = list(room.clients.values())
        count = len(peers)

    message = {
        "type": "peer_count",
        "room": room_code,
        "count": count,
        "peerCount": count,
        "senderId": "server",
        "ts": now_iso(),
    }

    dead_clients: list[str] = []
    for client in peers:
        ok = await send_json_safe(client.ws, message)
        if not ok:
            dead_clients.append(client.client_id)

    if dead_clients:
        async with rooms_lock:
            room = rooms.get(room_code)
            if not room:
                return
            for dead in dead_clients:
                room.clients.pop(dead, None)
            if not room.clients:
                rooms.pop(room_code, None)


async def join_room(room_code: str, client: ClientInfo) -> None:
    async with rooms_lock:
        room = rooms.setdefault(room_code, RoomInfo())
        room.clients[client.client_id] = client


async def leave_room(room_code: str, client_id: str) -> None:
    async with rooms_lock:
        room = rooms.get(room_code)
        if not room:
            return
        room.clients.pop(client_id, None)
        if not room.clients:
            rooms.pop(room_code, None)


async def get_room_snapshot(room_code: str) -> tuple[dict[str, Any] | None, list[ClientInfo]]:
    async with rooms_lock:
        room = rooms.get(room_code)
        if not room:
            return None, []
        state = room.state
        clients = list(room.clients.values())
    return state, clients


async def set_room_state(room_code: str, state_payload: dict[str, Any]) -> None:
    async with rooms_lock:
        room = rooms.setdefault(room_code, RoomInfo())
        room.state = state_payload
        room.updated_at = now_iso()


async def broadcast_to_room(
    room_code: str,
    payload: dict[str, Any],
    *,
    exclude_client_id: str | None = None,
    roles: set[str] | None = None,
) -> None:
    _, clients = await get_room_snapshot(room_code)
    for client in clients:
        if exclude_client_id and client.client_id == exclude_client_id:
            continue
        if roles is not None and client.role not in roles:
            continue
        await send_json_safe(client.ws, payload)


@app.websocket("/ws/collab")
async def collab_ws(websocket: WebSocket) -> None:
    await websocket.accept()

    room_code = normalize_room(websocket.query_params.get("room"))
    role = normalize_role(websocket.query_params.get("role"))
    client_id = normalize_client_id(websocket.query_params.get("clientId"), websocket)

    client = ClientInfo(client_id=client_id, role=role, ws=websocket)
    await join_room(room_code, client)

    await send_json_safe(
        websocket,
        {
            "type": "joined",
            "room": room_code,
            "role": role,
            "clientId": client_id,
            "senderId": "server",
            "ts": now_iso(),
        },
    )

    state, _ = await get_room_snapshot(room_code)
    if state is not None:
        await send_json_safe(
            websocket,
            {
                "type": "state_sync",
                "room": room_code,
                "senderId": "server",
                "state": state,
                "ts": now_iso(),
            },
        )

    await broadcast_presence(room_code)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await send_json_safe(
                    websocket,
                    {
                        "type": "error",
                        "room": room_code,
                        "senderId": "server",
                        "error": "invalid_json",
                        "ts": now_iso(),
                    },
                )
                continue

            msg_type = str(msg.get("type") or "").strip()
            sender_id = str(msg.get("clientId") or client_id)

            if msg_type in {"join", "ping"}:
                await send_json_safe(
                    websocket,
                    {
                        "type": "pong" if msg_type == "ping" else "joined",
                        "room": room_code,
                        "senderId": "server",
                        "clientId": client_id,
                        "ts": now_iso(),
                    },
                )
                continue

            if msg_type in {"state_sync", "state_update"}:
                state_payload = msg.get("state")
                if isinstance(state_payload, dict):
                    await set_room_state(room_code, state_payload)
                    await broadcast_to_room(
                        room_code,
                        {
                            "type": "state_sync",
                            "room": room_code,
                            "senderId": sender_id,
                            "state": state_payload,
                            "ts": now_iso(),
                        },
                        exclude_client_id=client_id,
                    )
                continue

            if msg_type == "state_request":
                current_state, _ = await get_room_snapshot(room_code)
                if current_state is not None:
                    await send_json_safe(
                        websocket,
                        {
                            "type": "state_sync",
                            "room": room_code,
                            "senderId": "server",
                            "state": current_state,
                            "ts": now_iso(),
                        },
                    )
                else:
                    # If server has no snapshot yet, ask current host(s) to provide one.
                    await broadcast_to_room(
                        room_code,
                        {
                            "type": "state_request",
                            "room": room_code,
                            "senderId": sender_id,
                            "ts": now_iso(),
                        },
                        exclude_client_id=client_id,
                        roles={"host"},
                    )
                continue

            # Fallback: relay unknown message types inside the room.
            await broadcast_to_room(
                room_code,
                {
                    **msg,
                    "room": room_code,
                    "senderId": sender_id,
                    "ts": now_iso(),
                },
                exclude_client_id=client_id,
            )

    except WebSocketDisconnect:
        pass
    finally:
        await leave_room(room_code, client_id)
        await broadcast_presence(room_code)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)

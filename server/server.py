"""Globe Board server: serves the game page and runs the online lobby.

One web service does everything, so a game is one link:
  GET /         the game (index.html, one folder up)
  GET /healthz  "globe-board", so the page knows online play is available
  GET /ws       the WebSocket for the lobby and for games

The server knows nothing about the rules. It keeps a list of players and rooms and
passes messages between the players in a room. The host's browser referees each game.

Client -> server
  {t: "hello", name}                 enter the lobby
  {t: "host"}                        open a room, as its host
  {t: "join", room}                  join a room that hasn't started
  {t: "leave"}                       leave the room
  {t: "begin"}                       host: the game started, take the room off the list
  {t: "again"}                       host: the game is over, reopen the room for another
  {t: "relay", to: "host"|"others", data}

Server -> client
  {t: "welcome", id}
  {t: "lobby", rooms: [{id, hostName, players, started}]}
  {t: "room", room: {id, host, players: [{id, name}], started}}
  {t: "relay", from, data}
  {t: "left", id}                    someone left your room
  {t: "hostLeft"}                    the host left your room; the room is closed
  {t: "error", msg}
"""
import asyncio
import json
import os
import secrets
from pathlib import Path

from aiohttp import WSMsgType, web

GAME_PAGE = Path(__file__).resolve().parent.parent / "index.html"
MAX_PLAYERS = 6
MAX_NAME = 16

clients = {}  # id -> {"ws", "name", "room"}
rooms = {}    # id -> {"host", "players": [ids], "started"}


async def send(cid, message):
    client = clients.get(cid)
    if not client:
        return
    try:
        await client["ws"].send_str(json.dumps(message))
    except (ConnectionResetError, RuntimeError):
        pass


def lobby_message():
    return {
        "t": "lobby",
        "rooms": [
            {
                "id": rid,
                "hostName": clients[room["host"]]["name"],
                "players": len(room["players"]),
                "started": room["started"],
            }
            for rid, room in rooms.items()
            if room["host"] in clients
        ],
    }


async def broadcast_lobby():
    message = lobby_message()
    await asyncio.gather(*(send(cid, message) for cid, c in list(clients.items()) if c["name"] and not c["room"]))


def room_message(rid):
    room = rooms[rid]
    return {
        "t": "room",
        "room": {
            "id": rid,
            "host": room["host"],
            "players": [{"id": cid, "name": clients[cid]["name"]} for cid in room["players"] if cid in clients],
            "started": room["started"],
        },
    }


async def broadcast_room(rid):
    if rid not in rooms:
        return
    message = room_message(rid)
    await asyncio.gather(*(send(cid, message) for cid in rooms[rid]["players"]))


async def leave_room(cid):
    client = clients.get(cid)
    rid = client and client["room"]
    room = rooms.get(rid)
    if not room:
        return
    client["room"] = None
    room["players"] = [p for p in room["players"] if p != cid]
    if room["host"] == cid:
        # The host's browser runs the game, so the room closes with it.
        rooms.pop(rid, None)
        for other in room["players"]:
            if other in clients:
                clients[other]["room"] = None
            await send(other, {"t": "hostLeft"})
    else:
        await asyncio.gather(*(send(other, {"t": "left", "id": cid}) for other in room["players"]))
        if not room["started"]:
            await broadcast_room(rid)
    await broadcast_lobby()


async def handle(cid, data):
    client = clients[cid]
    kind = data.get("t")

    if kind == "hello":
        client["name"] = (str(data.get("name", "")).strip() or "Player")[:MAX_NAME]
        await send(cid, lobby_message())

    elif kind == "host":
        if not client["name"] or client["room"]:
            return
        rid = secrets.token_hex(4)
        rooms[rid] = {"host": cid, "players": [cid], "started": False}
        client["room"] = rid
        await broadcast_room(rid)
        await broadcast_lobby()

    elif kind == "join":
        rid = data.get("room")
        room = rooms.get(rid)
        if not client["name"] or client["room"]:
            return
        if not room or room["started"]:
            await send(cid, {"t": "error", "msg": "That game has already started or closed."})
            return
        if len(room["players"]) >= MAX_PLAYERS:
            await send(cid, {"t": "error", "msg": "That game is full."})
            return
        room["players"].append(cid)
        client["room"] = rid
        await broadcast_room(rid)
        await broadcast_lobby()

    elif kind == "leave":
        await leave_room(cid)

    elif kind == "begin":
        room = rooms.get(client["room"])
        if room and room["host"] == cid:
            room["started"] = True
            await broadcast_lobby()

    elif kind == "again":
        rid = client["room"]
        room = rooms.get(rid)
        if room and room["host"] == cid and room["started"]:
            room["started"] = False
            await broadcast_room(rid)
            await broadcast_lobby()

    elif kind == "relay":
        room = rooms.get(client["room"])
        if not room:
            return
        message = {"t": "relay", "from": cid, "data": data.get("data")}
        if data.get("to") == "host":
            if room["host"] != cid:
                await send(room["host"], message)
        else:
            await asyncio.gather(*(send(other, message) for other in room["players"] if other != cid))


async def websocket(request):
    ws = web.WebSocketResponse(heartbeat=25, max_msg_size=8 * 1024 * 1024)
    await ws.prepare(request)
    cid = secrets.token_hex(4)
    clients[cid] = {"ws": ws, "name": None, "room": None}
    print(f"[+] {cid} connected ({len(clients)} online)", flush=True)
    await send(cid, {"t": "welcome", "id": cid})
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                data = json.loads(msg.data)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                await handle(cid, data)
    finally:
        await leave_room(cid)
        clients.pop(cid, None)
        print(f"[-] {cid} left ({len(clients)} online)", flush=True)
    return ws


async def page(request):
    return web.FileResponse(GAME_PAGE, headers={"Cache-Control": "no-cache"})


async def health(request):
    return web.Response(text="globe-board", headers={"Cache-Control": "no-store"})


def make_app():
    app = web.Application()
    app.router.add_get("/", page)
    app.router.add_get("/index.html", page)
    app.router.add_get("/healthz", health)
    app.router.add_get("/ws", websocket)
    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8800))
    print(f"Globe Board on http://0.0.0.0:{port}", flush=True)
    web.run_app(make_app(), host="0.0.0.0", port=port, print=None)

# brainstorm

## 多人協作連線架構

前端協作層採用固定策略：

1. 先嘗試 `PeerJS / WebRTC`
2. 若連線受企業網路限制而失敗，自動切換到同主機 `FastAPI WebSocket`

前端不再提供傳輸模式與 WebSocket 位址輸入 UI。

設計重點：

1. 畫布狀態統一為同一份 JSON（`nodes`, `stickies`, `connections`, `nextId`）
2. `snapshot()` 後只呼叫一次 `collabBroadcast()`
3. 傳輸層由 `collabActiveTransport` 自動決定，資料模型不綁定 PeerJS 或 WebSocket

## FastAPI WebSocket 建議協議

前端使用同主機 WebSocket 端點：

- `ws://<目前主機>/ws/collab`（HTTP）
- `wss://<目前主機>/ws/collab`（HTTPS）

並在連線 URL 帶上：

- `room`: 房號
- `role`: `host` 或 `guest`
- `clientId`: 前端隨機識別

前端也會在 WebSocket 開啟後送出：

```json
{ "type": "join", "room": "123456", "role": "host", "clientId": "c-xxxx" }
```

建議後端支援以下訊息型別：

1. `state_sync` / `state_update`: 廣播最新完整狀態
2. `state_request`: 新加入者請求目前狀態
3. `peer_count` 或 `presence`: 回傳目前房間人數

狀態 payload 結構：

```json
{
	"nodes": [],
	"stickies": [],
	"connections": [],
	"nextId": 1
}
```

## FastAPI WebSocket 後端範例（簡化）

```python
from collections import defaultdict
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

app = FastAPI()
rooms = defaultdict(set)


async def broadcast(room: str, message: str):
	dead = []
	for ws in rooms[room]:
		try:
			await ws.send_text(message)
		except Exception:
			dead.append(ws)
	for ws in dead:
		rooms[room].discard(ws)


@app.websocket("/ws/collab")
async def collab_ws(websocket: WebSocket):
	await websocket.accept()
	room = websocket.query_params.get("room", "000000")
	rooms[room].add(websocket)

	try:
		while True:
			data = await websocket.receive_text()
			await broadcast(room, data)
	except WebSocketDisconnect:
		rooms[room].discard(websocket)
```

此範例是「房內廣播」基礎版，正式環境可再加上驗證、ACL、訊息大小限制與心跳機制。

## 直接可跑的伺服器檔

專案已新增可直接執行的後端檔案：`server.py`

### 安裝與啟動

1. 安裝套件

```bash
pip install fastapi uvicorn
```

2. 啟動伺服器

```bash
python server.py
```

或使用：

```bash
uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

3. 前端直接使用同一台主機提供頁面與 WebSocket，不需額外設定位址。

### 內建能力

1. 房間管理：依 `room` 分群（支援 query string）
2. 人數廣播：加入/離開時送 `peer_count`
3. 狀態同步：支援 `state_request`、`state_sync`、`state_update`
4. 伺服器快照：房內保存最新 state，後加入者可立即同步
5. 健康檢查：`GET /health`
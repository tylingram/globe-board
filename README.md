# Globe Board

A turn-based 3D board game played on a sphere. Each side has three pill-bug pieces that move, fire cannons and roll into balls; perks, mushrooms, medals of valor and spreading ice decide who holds out longest.

The whole game is `index.html` (Three.js r128 from cdnjs). Open it in a browser to play against 1-5 bots.

For testing, add `?speed=10` to the address to play turns out ten times as fast.

## Online play

`server/server.py` serves the game page and runs the online lobby from one web service, so a game is one link. Players enter a name, then host a game or join one from the list. The host's panel settings (sphere size, bots, turn timer) are used for the game, and the host's browser runs the bots.

How a turn stays the same for everyone: each player sends their orders to the host; the host sends every order to everyone at once; every browser plays the turn from the same orders with the same dice; then the host sends the true end-of-turn state, which every browser takes over.

If a player leaves, their pieces stand still for the rest of the game. If the host leaves, the game ends.

When a game ends, everyone sees who won and each side's kills and medals, piece by piece. The host's Play again takes everyone still there back to the room, where the host can change the settings and start another game.

The Online section only appears when the page is loaded from the server (it checks `/healthz`), so the single-file version stays offline.

### Run it locally

```
pip install -r server/requirements.txt
python server/server.py
```

Then open http://localhost:8800 in two browser windows.

### Deploy on Render

1. Push this repository to GitHub.
2. In Render, choose **New > Blueprint**, pick the repository, and deploy. `render.yaml` sets up one free Python web service.
3. Share the service's address (for example `https://globe-board.onrender.com`).

On the free plan the service sleeps after about 15 minutes without visitors, so the first visit after that takes up to a minute while it wakes.

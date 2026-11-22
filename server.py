"""
Local web viewer for the hazard maze.

    python server.py              # then open http://localhost:8000
    python server.py --port 9000

Endpoints
  GET /                     the live viewer (web/index.html)
  GET /api/run?seed=7&size=51&radius=2[&arrows=N]
                            one maze + every agent's full run, as JSON
  GET /api/bench?n=10&size=51&radius=2
                            average results over n mazes

Laya: drop a file `laya_agent.py` next to this one that defines
    def predict(state_text: str, obs: dict) -> str   # "up" | "down" | "left" | "right"
and it is picked up automatically as a fourth agent (restart the server after adding it).
"""
import argparse
import json
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import maze_sim as M

WEB = Path(__file__).parent / "web"
MAX_SIZE = 101


def agents():
    out = M.default_agents()
    try:
        import laya_agent  # optional, coded separately
        if hasattr(laya_agent, "predict"):
            out.append(M.LayaAgent(predict_fn=laya_agent.predict))
    except ImportError:
        pass
    return out


def _params(q):
    size = max(11, min(MAX_SIZE, int(q.get("size", ["51"])[0])))
    size += (size % 2 == 0)
    radius = max(1, min(5, int(q.get("radius", ["2"])[0])))
    seed = int(q.get("seed", ["7"])[0])
    arrows = q.get("arrows", [None])[0]
    return seed, size, radius, int(arrows) if arrows not in (None, "") else None


def run_payload(seed, size, radius, arrows):
    t0 = time.perf_counter()
    maze = M.generate(size, seed=seed, n_arrows=arrows)
    best, _ = M.oracle_solution(maze)
    gps = M.gps_distances(maze.layout())
    results = []
    for a in agents():
        r = M.run(maze, a, radius, best)
        results.append({
            "name": r["agent"],
            "fullMap": a.full_map,
            "success": r["success"],
            "time": r["time"],
            "steps": r["steps"],
            "events": dict(r["events"]),
            "trace": [[p[0], p[1], round(t, 3), e, s] for p, t, e, s in r["trace"]],
        })
    return {
        "seed": seed, "size": maze.n, "radius": radius,
        "walls": ["".join("#" if w else "." for w in row) for row in maze.walls],
        "start": list(maze.start), "goal": list(maze.goal),
        "puddles": [[r, c, d] for (r, c), d in maze.puddles.items()],
        "muds": [[r, c] for r, c in maze.muds],
        "arrows": [[r, c, d] for (r, c), d in maze.redirects.items()],
        "best": best, "limit": M.TIME_LIMIT_FACTOR * best, "fewestSteps": gps[maze.start],
        "rules": {"slowMoves": M.MUD_SLOW_MOVES, "slowMult": M.SLOW_MULT, "pushCost": M.REDIRECT_COST,
                  "limitFactor": M.TIME_LIMIT_FACTOR},
        "agents": results,
        "computeMs": round((time.perf_counter() - t0) * 1000),
    }


def bench_payload(n, seed, size, radius, arrows):
    names, stats = None, {}
    for i in range(n):
        maze = M.generate(size, seed=seed + i, n_arrows=arrows)
        best, _ = M.oracle_solution(maze)
        for a in agents():
            r = M.run(maze, a, radius, best)
            t = r["time"] if r["success"] else r["limit"]
            s = stats.setdefault(a.name, {"ok": 0, "time": 0.0, "ratio": 0.0})
            s["ok"] += r["success"]
            s["time"] += t
            s["ratio"] += t / best
    return {"n": n, "size": size, "radius": radius, "seedFrom": seed,
            "rows": [{"name": k, "success": v["ok"] / n, "time": v["time"] / n, "ratio": v["ratio"] / n}
                     for k, v in stats.items()]}


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):   # keep the console quiet except for API calls
        if "/api/" in (args[0] if args else ""):
            super().log_message(fmt, *args)

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path == "/api/run":
                return self._json(run_payload(*_params(q)))
            if u.path == "/api/bench":
                n = max(1, min(50, int(q.get("n", ["10"])[0])))
                return self._json(bench_payload(n, *_params(q)))
        except (ValueError, KeyError) as e:
            return self._json({"error": str(e)}, 400)
        return super().do_GET()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), partial(Handler, directory=str(WEB)))
    print(f"Hazard maze viewer running at http://localhost:{args.port}  (Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

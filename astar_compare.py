"""
Full-map comparison: Dijkstra vs A* on the hazard maze (all costs are TIME).

  dijkstra     : no heuristic. Always finds the fastest route, explores the most.
  astar        : A* with Manhattan distance. Every hazard only ADDS time (no shortcuts),
                 so Manhattan never overestimates -> same fastest route, less exploring.
  fewest_steps : GPS route (fewest steps) walked with real hazard costs.

Search state = (tile, slowed moves left), because mud changes the cost of later moves.

Usage
  python astar_compare.py --n 200 --png
  python astar_compare.py --n 10 --size 101      # bigger maze: compute gap becomes visible
"""
import argparse
import heapq
import time

from maze_sim import (MOVES, add, generate, gps_distances, gps_move, oracle_solution, transition)


def manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def search(maze, use_heuristic):
    """Forward best-first search over (tile, slow) states. Returns (time, path, explored cells)."""
    h = (lambda c: manhattan(c, maze.goal)) if use_heuristic else (lambda c: 0.0)
    start = (maze.start, 0)
    g, parent = {start: 0.0}, {start: None}
    pq = [(h(maze.start), 0.0, start)]
    done, explored, goal_state = set(), [], None
    while pq:
        _, d, st = heapq.heappop(pq)
        if st in done or d > g[st]:
            continue
        done.add(st)
        explored.append(st[0])
        if st[0] == maze.goal:
            goal_state = st
            break
        for mv in MOVES:          # neighbours generated on demand: work ~ states explored
            if maze.is_wall(add(st[0], MOVES[mv])):
                continue
            land, s2, w, _ = transition(maze, st[0], st[1], mv)
            nst, nd = (land, s2), d + w
            if nd < g.get(nst, float("inf")):
                g[nst], parent[nst] = nd, st
                heapq.heappush(pq, (nd + h(land), nd, nst))
    path, st = [], goal_state
    while st is not None:
        path.append(st[0])
        st = parent[st]
    return g.get(goal_state, float("inf")), path[::-1], set(explored)


def fewest_steps(maze):
    layout = maze.layout()
    gps = gps_distances(layout)
    pos, slow, t, path = maze.start, 0, 0.0, [maze.start]
    for _ in range(4 * maze.n * maze.n):   # cap: an arrow can push it back onto the same route forever
        if pos == maze.goal:
            return t, path, set(gps)
        pos, slow, dt, _ = transition(maze, pos, slow, gps_move(layout, gps, pos))
        t += dt
        path.append(pos)
    return float("inf"), path, set(gps)


METHODS = {
    "dijkstra": lambda m: search(m, False),
    "astar": lambda m: search(m, True),
    "fewest_steps": fewest_steps,
}


def compare(n, size, seed, arrows):
    stats = {k: {"time": 0.0, "opt": 0, "exp": 0, "ms": 0.0, "gap": 0.0, "stuck": 0} for k in METHODS}
    for i in range(n):
        maze = generate(size, seed=seed + i, n_arrows=arrows)
        best, _ = oracle_solution(maze)
        for name, fn in METHODS.items():
            t0 = time.perf_counter()
            t, _, exp = fn(maze)
            ms = (time.perf_counter() - t0) * 1000
            s = stats[name]
            if t == float("inf"):
                s["stuck"] += 1
                t = 3 * best        # counted at the time limit
            s["time"] += t
            s["opt"] += abs(t - best) < 1e-9
            s["exp"] += len(exp)
            s["ms"] += ms
            s["gap"] += t / best
    print(f"\n{n} mazes, size {size}, {arrows} arrows, FULL map known to every method\n")
    print(f"{'method':<14}{'route time':>11}{'fastest?':>10}{'x best':>9}{'cells explored':>17}{'compute ms':>12}")
    for name, s in stats.items():
        print(f"{name:<14}{s['time']/n:>10.1f}s{100*s['opt']/n:>9.0f}%{s['gap']/n:>9.2f}"
              f"{s['exp']/n:>17.0f}{s['ms']/n:>12.2f}")
    print("\nroute time = seconds to walk the route found; compute ms = how long the algorithm ran.")
    if stats["fewest_steps"]["stuck"]:
        print(f"fewest_steps got stuck behind an arrow in {stats['fewest_steps']['stuck']} mazes (counted as 3x best).")


def picture(seed, size, arrows, out="astar_vs_dijkstra.png"):
    from PIL import Image, ImageDraw
    from render import CS, GAP, HEAD, _base, _font
    maze = generate(size, seed=seed, n_arrows=arrows)
    base = _base(maze)
    colors = {"dijkstra": (220, 60, 60), "astar": (40, 120, 220), "fewest_steps": (230, 120, 20)}
    panels = []
    for name in METHODS:
        t, path, exp = METHODS[name](maze)
        img = Image.new("RGB", (base.width, base.height + HEAD), "white")
        img.paste(base, (0, HEAD))
        if name != "fewest_steps":
            ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
            d = ImageDraw.Draw(ov)
            for c in exp:
                x, y = c[1] * CS, c[0] * CS + HEAD
                d.rectangle([x, y, x + CS - 1, y + CS - 1], fill=colors[name] + (55,))
            img = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")
        d = ImageDraw.Draw(img)
        for c in path:
            x, y = c[1] * CS + CS // 2, c[0] * CS + CS // 2 + HEAD
            d.ellipse([x - 4, y - 4, x + 4, y + 4], fill=colors[name], outline="black")
        d.text((6, 4), name.upper(), fill=colors[name], font=_font(16))
        tt = "stuck" if t == float("inf") else f"{t:.1f}s"
        sub = f"route time {tt}" + ("" if name == "fewest_steps" else f"   explored {len(exp)} cells")
        d.text((6, 24), sub, fill=(40, 40, 40), font=_font(13))
        panels.append(img)
    W = len(panels) * base.width + (len(panels) - 1) * GAP
    out_img = Image.new("RGB", (W, base.height + HEAD), "white")
    for i, p in enumerate(panels):
        out_img.paste(p, (i * (base.width + GAP), 0))
    out_img.save(out)
    print(f"saved {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--size", type=int, default=21)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--arrows", type=int, default=10)
    ap.add_argument("--png", action="store_true")
    a = ap.parse_args()
    compare(a.n, a.size, a.seed, a.arrows)
    if a.png:
        picture(a.seed, a.size, a.arrows)

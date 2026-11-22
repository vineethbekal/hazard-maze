"""
Hazard maze: the fastest route is not the shortest route.

Game-style hazards (all visible; their effect is knowable from where you stand)
  normal : a move takes 1 s
  wall   : blocked (bumping wastes a move)
  puddle : slip. One-off delay of +1..3 s when you step on it.
  mud    : SLOW debuff. Your next 3 moves take 2x as long (stepping on mud again refreshes it).
  arrow  : conveyor. Pushes you ONE tile in its direction (+1 s). Arrows always point away
           from the goal, so they only ever cost you. Pushes don't chain.
  goal   : reach it to finish

Score = total time to reach the goal (time limit = 3x the best possible time).

Agents
  oracle      : full map, Dijkstra on time (state = tile + slow debuff) -> ground truth
  astar       : limited vision + GPS, plain A* on step count (ignores time costs of hazards)
  astar_aware : limited vision + GPS, A* on time using every hazard it has seen
  laya        : limited vision + GPS, same info as astar_aware -> coded separately

GPS knows the wall layout (like roads) but NOT the hazards.
Limited agents see only a (2r+1)x(2r+1) window around themselves, plus their own debuff.

Usage
  python maze_sim.py demo  --seed 7
  python maze_sim.py bench --n 200
  python maze_sim.py dataset --n 500 --out laya_train.jsonl
No dependencies except Pillow (only for demo rendering).
"""
import argparse
import heapq
import json
import random
from collections import Counter, deque

MOVES = {"up": (-1, 0), "down": (1, 0), "left": (0, -1), "right": (0, 1)}
MOVE_ORDER = ["up", "down", "left", "right"]
ARROW = {"up": "^", "down": "v", "left": "<", "right": ">"}
ARROW_DIR = {v: k for k, v in ARROW.items()}

STEP_COST = 1.0          # seconds per move at normal speed
BUMP_COST = 1.0          # a wasted move into a wall
REDIRECT_COST = 1.0      # extra seconds when an arrow pushes you
MUD_SLOW_MOVES = 3       # mud slows this many following moves
SLOW_MULT = 2.0          # slowed moves take this many times longer
TIME_LIMIT_FACTOR = 3.0  # time limit = factor * oracle time
PUDDLE_FRAC, MUD_FRAC = 0.08, 0.05   # hazard density used by generate()
# expected extra seconds hiding in a tile you haven't seen yet (avg puddle 2 s, mud ~3 slowed moves)
UNSEEN_EXTRA = PUDDLE_FRAC * 2.0 + MUD_FRAC * MUD_SLOW_MOVES * (SLOW_MULT - 1)


def add(p, d):
    return (p[0] + d[0], p[1] + d[1])


# --------------------------------------------------------------------------- maze
class Maze:
    """Walls + hazards. The planner builds one of these from what it has seen."""

    def __init__(self, walls, start, goal, puddles=None, muds=None, redirects=None):
        self.walls = walls                  # list[list[bool]]
        self.n = len(walls)
        self.start, self.goal = start, goal
        self.puddles = puddles or {}        # cell -> delay seconds
        self.muds = muds or set()           # cells
        self.redirects = redirects or {}    # cell -> push direction

    def is_wall(self, p):
        r, c = p
        return not (0 <= r < self.n and 0 <= c < self.n) or self.walls[r][c]

    def open_cells(self):
        return [(r, c) for r in range(self.n) for c in range(self.n) if not self.walls[r][c]]

    def layout(self):
        """What the GPS knows: walls, start, goal. No hazards."""
        return Maze(self.walls, self.start, self.goal)

    def tile(self, p):
        if self.is_wall(p):
            return {"tile": "wall"}
        if p == self.goal:
            return {"tile": "goal"}
        if p in self.redirects:
            return {"tile": "arrow", "push": self.redirects[p]}
        if p in self.muds:
            return {"tile": "mud"}
        if p in self.puddles:
            return {"tile": "puddle", "delay": self.puddles[p]}
        return {"tile": "normal"}

    def step(self, pos, slow, move):
        return transition(self, pos, slow, move)


def transition(m, pos, slow, move):
    """One move. State = (tile, slowed moves left). Returns (pos, slow, seconds, event)."""
    mult = SLOW_MULT if slow > 0 else 1.0
    slow2 = max(slow - 1, 0)
    nxt = add(pos, MOVES[move])
    if m.is_wall(nxt):
        return pos, slow2, BUMP_COST * mult, "bump"
    cost, event, land = STEP_COST * mult, "move", nxt
    if nxt in m.redirects:
        pushed = add(nxt, MOVES[m.redirects[nxt]])
        if not m.is_wall(pushed):
            land = pushed
        cost += REDIRECT_COST
        event = "arrow"
    if land in m.puddles:
        cost += m.puddles[land]
        event = "puddle" if event == "move" else event
    if land in m.muds:
        slow2 = MUD_SLOW_MOVES
        event = "mud" if event == "move" else event
    return land, slow2, cost, event


def generate(size=51, seed=None, braid=0.35, puddle_frac=PUDDLE_FRAC, mud_frac=MUD_FRAC, n_arrows=None, on_route_frac=0.4):
    """Random maze with loops, puddles, mud and arrows. size must be odd."""
    rng = random.Random(seed)
    if size % 2 == 0:
        size += 1
    walls = [[True] * size for _ in range(size)]

    stack = [(1, 1)]                      # perfect maze via iterative backtracker
    walls[1][1] = False
    while stack:
        r, c = stack[-1]
        nbrs = [(r + dr, c + dc, dr // 2, dc // 2) for dr, dc in ((-2, 0), (2, 0), (0, -2), (0, 2))
                if 0 < r + dr < size - 1 and 0 < c + dc < size - 1 and walls[r + dr][c + dc]]
        if not nbrs:
            stack.pop()
            continue
        nr, nc, hr, hc = rng.choice(nbrs)
        walls[r + hr][c + hc] = False
        walls[nr][nc] = False
        stack.append((nr, nc))

    knock = []                            # braid: add loops so there are alternative routes
    for r in range(1, size - 1):
        for c in range(1, size - 1):
            if walls[r][c] and ((not walls[r - 1][c] and not walls[r + 1][c]) or
                                (not walls[r][c - 1] and not walls[r][c + 1])):
                knock.append((r, c))
    for r, c in rng.sample(knock, int(len(knock) * braid)):
        walls[r][c] = False

    start, goal = (1, 1), (size - 2, size - 2)
    maze = Maze(walls, start, goal)
    gps = gps_distances(maze)
    route = sorted(set(gps_route(maze, gps)) - {start, goal})
    free = [p for p in maze.open_cells() if p not in (start, goal) and abs(p[0] - start[0]) + abs(p[1] - start[1]) > 1]

    def pick(k, taken):
        """k cells, a share of them on the GPS route so decisions matter."""
        on = [p for p in route if p not in taken]
        k_on = min(len(on), int(k * on_route_frac))
        got = set(rng.sample(on, k_on))
        off = [p for p in free if p not in taken and p not in got]
        got |= set(rng.sample(off, min(len(off), k - k_on)))
        return got

    if n_arrows is None:
        n_arrows = max(4, len(free) // 50)     # scales with map size
    maze.puddles = {p: rng.randint(1, 3) for p in pick(int(len(free) * puddle_frac), set())}
    maze.muds = pick(int(len(free) * mud_frac), set(maze.puddles))

    taken = set(maze.puddles) | maze.muds
    cands = [p for p in route if p not in taken]
    rng.shuffle(cands)
    rest = [p for p in free if p not in taken and p not in cands]
    rng.shuffle(rest)
    for p in cands[: n_arrows // 2] + rest:
        if len(maze.redirects) >= n_arrows:
            break
        dirs = [d for d in MOVE_ORDER if not maze.is_wall(add(p, MOVES[d]))
                and gps.get(add(p, MOVES[d]), 1e9) > gps.get(p, 1e9)]     # point away from goal
        if not dirs:
            continue
        maze.redirects[p] = rng.choice(dirs)
        if not _all_reach_goal(maze):    # an arrow must not seal off the goal
            del maze.redirects[p]
    return maze


def _all_reach_goal(maze):
    dist = time_to_goal(state_edges(maze), maze.goal)
    return all((c, 0) in dist for c in maze.open_cells() if c not in maze.redirects)


# --------------------------------------------------------------------------- GPS
def gps_distances(layout):
    """Fewest steps to goal from every cell, walls only (GPS knows roads, not hazards)."""
    dist = {layout.goal: 0}
    q = deque([layout.goal])
    while q:
        u = q.popleft()
        for d in MOVES.values():
            v = add(u, d)
            if not layout.is_wall(v) and v not in dist:
                dist[v] = dist[u] + 1
                q.append(v)
    return dist


def gps_move(layout, gps, pos):
    best, best_d = None, float("inf")
    for m in MOVE_ORDER:
        v = add(pos, MOVES[m])
        if not layout.is_wall(v) and gps.get(v, float("inf")) < best_d:
            best, best_d = m, gps[v]
    return best


def gps_route(layout, gps):
    pos, route = layout.start, [layout.start]
    while pos != layout.goal and len(route) < layout.n * layout.n:
        pos = add(pos, MOVES[gps_move(layout, gps, pos)])
        route.append(pos)
    return route


# --------------------------------------------------------------------------- Dijkstra on time over (tile, slow) states
def state_edges(m):
    """{(cell, slow): [(move, (cell', slow'), seconds)]} for every reachable-looking state."""
    edges = {}
    for c in m.open_cells():
        for s in range(MUD_SLOW_MOVES + 1):
            out = []
            for mv in MOVE_ORDER:
                if m.is_wall(add(c, MOVES[mv])):
                    continue
                land, s2, w, _ = transition(m, c, s, mv)
                out.append((mv, (land, s2), w))
            edges[(c, s)] = out
    return edges


def time_to_goal(edges, goal):
    """Reverse Dijkstra from every goal state: seconds to goal from each (cell, slow) state."""
    rev = {}
    for st, out in edges.items():
        for _, nst, w in out:
            rev.setdefault(nst, []).append((st, w))
    dist = {(goal, s): 0.0 for s in range(MUD_SLOW_MOVES + 1)}
    pq = [(0.0, st) for st in dist]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist.get(u, float("inf")):
            continue
        for v, w in rev.get(u, []):
            nd = d + w
            if nd < dist.get(v, float("inf")):
                dist[v] = nd
                heapq.heappush(pq, (nd, v))
    return dist


def best_move(edges, dist, st):
    best, best_v = None, float("inf")
    for mv, nst, w in edges.get(st, []):
        v = w + dist.get(nst, float("inf"))
        if v < best_v:
            best, best_v = mv, v
    return best


def oracle_solution(maze):
    """Ground truth: (best time, policy {(cell, slow): move}) with the full map."""
    edges = state_edges(maze)
    dist = time_to_goal(edges, maze.goal)
    policy = {st: best_move(edges, dist, st) for st in edges if st[0] != maze.goal and st in dist}
    return dist.get((maze.start, 0), float("inf")), policy


# --------------------------------------------------------------------------- observation
def observe(maze, pos, slow, gps, visits, t, limit, last_event, radius=2):
    """Everything a limited agent is allowed to know this step."""
    view = []
    for dr in range(-radius, radius + 1):
        row = []
        for dc in range(-radius, radius + 1):
            tl = maze.tile((pos[0] + dr, pos[1] + dc))
            code = {"wall": "#", "goal": "G", "normal": ".", "mud": "m"}.get(tl["tile"])
            if tl["tile"] == "puddle":
                code = f"~{tl['delay']}"
            elif tl["tile"] == "arrow":
                code = ARROW[tl["push"]]
            row.append(code)
        view.append(row)
    neighbors = {}
    for m in MOVE_ORDER:
        p = add(pos, MOVES[m])
        info = maze.tile(p)
        if info["tile"] != "wall":
            info["gps_dist"] = gps.get(p)
            info["visits"] = visits[p]
            if info["tile"] == "arrow":     # where the push lands is knowable from the layout
                land = add(p, MOVES[info["push"]])
                info["lands_gps_dist"] = gps.get(p if maze.is_wall(land) else land)
        neighbors[m] = info
    return {
        "pos": list(pos),
        "slowed": slow,
        "goal_delta": [maze.goal[0] - pos[0], maze.goal[1] - pos[1]],
        "gps_move": gps_move(maze, gps, pos),
        "gps_dist_here": gps.get(pos),
        "time_used": round(t, 2),
        "time_limit": round(limit, 2),
        "last_event": last_event,
        "radius": radius,
        "view": view,
        "neighbors": neighbors,
    }


def obs_to_text(obs):
    """Compact text state, handy as Laya input."""
    dr, dc = obs["goal_delta"]
    vert = f"{abs(dr)} {'down' if dr >= 0 else 'up'}"
    horz = f"{abs(dc)} {'right' if dc >= 0 else 'left'}"
    slow = f"You are slowed (x{SLOW_MULT:g}) for {obs['slowed']} more moves." if obs["slowed"] else "Normal speed."
    parts = [f"Goal is {vert}, {horz}. GPS says {obs['gps_move']} ({obs['gps_dist_here']} steps left).",
             f"{slow} Time {obs['time_used']}s of {obs['time_limit']}s. Last event: {obs['last_event']}."]
    for m in MOVE_ORDER:
        n = obs["neighbors"][m]
        if n["tile"] == "wall":
            parts.append(f"{m}: wall.")
            continue
        if n["tile"] == "puddle":
            desc = f"puddle +{n['delay']}s"
        elif n["tile"] == "mud":
            desc = f"mud (slows next {MUD_SLOW_MOVES} moves)"
        elif n["tile"] == "arrow":
            desc = f"arrow pushes {n['push']}, lands at gps {n['lands_gps_dist']}"
        else:
            desc = n["tile"]
        parts.append(f"{m}: {desc}, gps {n['gps_dist']}, visited {n['visits']}.")
    parts.append("View: " + " / ".join(" ".join(row) for row in obs["view"]))
    return " ".join(parts)


# --------------------------------------------------------------------------- agents
class OracleAgent:
    """Full map. Not a fair competitor: it is the ground truth."""
    name = "oracle"
    full_map = True

    def reset(self, maze):
        _, self.policy = oracle_solution(maze)

    def act(self, obs):
        return self.policy[(tuple(obs["pos"]), obs["slowed"])]


def manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


class AStarAgent:
    """Limited vision + GPS. Remembers every hazard it has seen and replans with A* each step.
    Unseen tiles are assumed normal.

    aware=False -> "astar": plain A* on STEP count. It understands that an arrow physically
                   pushes you (otherwise it walks into the same arrow forever), but ignores
                   every time cost: puddle delays, mud slowdown, the push delay.
    aware=True  -> "astar_aware": A* on TIME with the real cost of every hazard it has seen,
                   including the mud slowdown on later moves, and the expected hazard cost
                   for tiles it hasn't seen yet. Same information as Laya.
    """
    full_map = False

    def __init__(self, aware):
        self.aware = aware
        self.name = "astar_aware" if aware else "astar"

    def reset(self, layout):
        self.belief = Maze(layout.walls, layout.start, layout.goal, {}, set(), {})
        self.seen = set()

    def _update(self, obs):
        pos, r, b = tuple(obs["pos"]), obs["radius"], self.belief
        for i, row in enumerate(obs["view"]):
            for j, code in enumerate(row):
                p = (pos[0] - r + i, pos[1] - r + j)
                self.seen.add(p)
                if code.startswith("~"):
                    b.puddles[p] = int(code[1:])
                elif code == "m":
                    b.muds.add(p)
                elif code in ARROW_DIR:
                    b.redirects[p] = ARROW_DIR[code]

    def _step(self, cell, slow, mv):
        land, s2, w, _ = transition(self.belief, cell, slow, mv)
        if not self.aware:
            return land, 0, 1.0        # every move = 1 step, hazards cost nothing
        if land not in self.seen and land != self.belief.goal:
            w += UNSEEN_EXTRA          # unseen tiles carry their expected hazard cost
        return land, s2, w

    def act(self, obs):
        self._update(obs)
        b = self.belief
        start = (tuple(obs["pos"]), obs["slowed"] if self.aware else 0)
        g, first = {start: 0.0}, {start: None}
        pq = [(manhattan(start[0], b.goal), 0.0, start)]
        done = set()
        while pq:
            _, d, st = heapq.heappop(pq)
            if st in done or d > g[st]:
                continue
            done.add(st)
            if st[0] == b.goal:
                return first[st] or obs["gps_move"]
            for mv in MOVE_ORDER:
                if b.is_wall(add(st[0], MOVES[mv])):
                    continue
                land, s2, w = self._step(st[0], st[1], mv)
                nst, nd = (land, s2), d + w
                if nd < g.get(nst, float("inf")):
                    g[nst] = nd
                    first[nst] = first[st] or mv
                    heapq.heappush(pq, (nd + manhattan(land, b.goal), nd, nst))
        return obs["gps_move"]


class LayaAgent:
    """Hook for Laya. Same info as AStarAgent. Pass predict_fn(state_text, obs) -> move."""
    name = "laya"
    full_map = False

    def __init__(self, predict_fn=None):
        self.predict_fn = predict_fn

    def reset(self, layout):
        pass

    def act(self, obs):
        if self.predict_fn is None:
            raise NotImplementedError("Plug Laya in: LayaAgent(predict_fn=lambda text, obs: 'up'|'down'|'left'|'right')")
        move = self.predict_fn(obs_to_text(obs), obs)
        if move not in MOVES or obs["neighbors"][move]["tile"] == "wall":
            move = obs["gps_move"]   # safety fallback
        return move


# --------------------------------------------------------------------------- simulation
def run(maze, agent, radius=2, oracle_time=None, max_steps=5000, record=None, label_policy=None):
    if oracle_time is None:
        oracle_time, _ = oracle_solution(maze)
    limit = TIME_LIMIT_FACTOR * oracle_time
    layout = maze.layout()
    gps = gps_distances(layout)
    agent.reset(maze if agent.full_map else layout)

    pos, slow, t, last = maze.start, 0, 0.0, "start"
    visits = Counter({pos: 1})
    trace = [(pos, t, last, slow)]
    for _ in range(max_steps):
        if pos == maze.goal or t > limit:
            break
        obs = observe(maze, pos, slow, gps, visits, t, limit, last, radius)
        if record is not None and label_policy is not None and (pos, slow) in label_policy:
            record.append({"text": obs_to_text(obs), "obs": obs, "label": label_policy[(pos, slow)]})
        move = agent.act(obs)
        pos, slow, dt, last = maze.step(pos, slow, move)
        t += dt
        visits[pos] += 1
        trace.append((pos, t, last, slow))
    return {"agent": agent.name, "success": pos == maze.goal and t <= limit, "time": t, "limit": limit,
            "oracle": oracle_time, "steps": len(trace) - 1, "trace": trace,
            "events": Counter(e for _, _, e, _ in trace[1:])}


def default_agents():
    return [OracleAgent(), AStarAgent(aware=False), AStarAgent(aware=True)]


# --------------------------------------------------------------------------- commands
def _gen(args, seed):
    return generate(args.size, seed=seed, n_arrows=args.arrows)


def cmd_bench(args):
    agents = default_agents()
    stats = {a.name: {"ok": 0, "time": 0.0, "ratio": 0.0} for a in agents}
    for i in range(args.n):
        maze = _gen(args, args.seed + i)
        ot, _ = oracle_solution(maze)
        for a in agents:
            r = run(maze, a, args.radius, ot)
            t = r["time"] if r["success"] else r["limit"]    # failures count as the full limit
            s = stats[a.name]
            s["ok"] += r["success"]
            s["time"] += t
            s["ratio"] += t / ot
    print(f"\n{args.n} mazes, size {args.size}, vision {2*args.radius+1}x{2*args.radius+1}, "
          f"limit {TIME_LIMIT_FACTOR:g}x oracle\n")
    print(f"{'agent':<10}{'success':>10}{'avg time':>12}{'time / oracle':>16}")
    for name, s in stats.items():
        print(f"{name:<10}{100*s['ok']/args.n:>9.0f}%{s['time']/args.n:>11.1f}s{s['ratio']/args.n:>16.2f}")


def cmd_dataset(args):
    """Label = oracle's move at every state a limited agent actually visits."""
    rows = []
    for i in range(args.n):
        maze = _gen(args, args.seed + i)
        ot, policy = oracle_solution(maze)
        for a in default_agents():
            run(maze, a, args.radius, ot, record=rows, label_policy=policy)
    with open(args.out, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    print(f"wrote {len(rows)} rows to {args.out}  label counts: {dict(Counter(r['label'] for r in rows))}")


def cmd_demo(args):
    maze = _gen(args, args.seed)
    ot, _ = oracle_solution(maze)
    results = [run(maze, a, args.radius, ot) for a in default_agents()]
    gps = gps_distances(maze.layout())
    print(f"maze seed {args.seed}: {len(maze.puddles)} puddles, {len(maze.muds)} mud, {len(maze.redirects)} arrows, "
          f"fewest steps {gps[maze.start]}, oracle best time {ot:.1f}s, limit {TIME_LIMIT_FACTOR*ot:.1f}s\n")
    for r in results:
        ev = ", ".join(f"{k} {v}" for k, v in sorted(r["events"].items()))
        print(f"{r['agent']:<8} {'OK  ' if r['success'] else 'FAIL'} time {r['time']:6.1f}s  "
              f"x{r['time']/ot:4.2f} oracle  steps {r['steps']:4d}  ({ev})")
    from render import render
    render(maze, results, args.out, radius=args.radius)
    print(f"\nsaved {args.out}.gif and {args.out}.png")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["demo", "bench", "dataset"])
    ap.add_argument("--size", type=int, default=51)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--arrows", type=int, default=None, help="number of conveyor arrows (default: scales with size)")
    ap.add_argument("--radius", type=int, default=2, help="vision radius (2 = 5x5)")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    if args.cmd == "demo":
        args.out = args.out or "maze_demo"
        cmd_demo(args)
    elif args.cmd == "bench":
        cmd_bench(args)
    else:
        args.out = args.out or "laya_train.jsonl"
        cmd_dataset(args)


if __name__ == "__main__":
    main()

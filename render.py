"""Side-by-side GIF replay of agents on one maze (Pillow only)."""
from PIL import Image, ImageDraw, ImageFont

CS = 22          # cell size px
HEAD = 46        # header height px
GAP = 12

C_FLOOR = (236, 236, 230)
C_WALL = (40, 44, 52)
C_PUDDLE = {1: (178, 218, 255), 2: (105, 170, 240), 3: (40, 110, 210)}
C_MUD = (150, 105, 60)
C_ARROW_BG = (255, 214, 214)
C_ARROW = (200, 40, 40)
C_START = (80, 180, 90)
C_GOAL = (240, 180, 30)
AGENT_COLORS = {"oracle": (220, 60, 60), "astar": (230, 120, 20), "astar_aware": (20, 150, 120), "laya": (200, 40, 160)}


def _font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _arrow(d, x, y, direction, col):
    """Triangle pointing in `direction` inside the cell at (x, y)."""
    m, s = CS // 2, max(2, CS // 2 - 3)
    cx, cy = x + m, y + m
    pts = {"up": [(cx, cy - s), (cx - s, cy + s), (cx + s, cy + s)],
           "down": [(cx, cy + s), (cx - s, cy - s), (cx + s, cy - s)],
           "left": [(cx - s, cy), (cx + s, cy - s), (cx + s, cy + s)],
           "right": [(cx + s, cy), (cx - s, cy - s), (cx - s, cy + s)]}[direction]
    d.polygon(pts, fill=col)


def _base(maze):
    n = maze.n
    img = Image.new("RGB", (n * CS, n * CS), C_FLOOR)
    d = ImageDraw.Draw(img)
    f = _font(11)
    for r in range(n):
        for c in range(n):
            x, y = c * CS, r * CS
            box = [x, y, x + CS - 1, y + CS - 1]
            p = (r, c)
            if maze.walls[r][c]:
                d.rectangle(box, fill=C_WALL)
            elif p in maze.redirects:
                d.rectangle(box, fill=C_ARROW_BG)
                _arrow(d, x, y, maze.redirects[p], C_ARROW)
            elif p in maze.muds:
                d.rectangle(box, fill=C_MUD)
                CS >= 14 and d.text((x + CS // 2, y + CS // 2), "M", fill=(255, 235, 210), font=f, anchor="mm")
            elif p in maze.puddles:
                d.rectangle(box, fill=C_PUDDLE[maze.puddles[p]])
                CS >= 14 and d.text((x + CS // 2, y + CS // 2), f"+{maze.puddles[p]}", fill=(20, 40, 90), font=f, anchor="mm")
    for p, col, lab in ((maze.start, C_START, "S"), (maze.goal, C_GOAL, "G")):
        x, y = p[1] * CS, p[0] * CS
        d.rectangle([x, y, x + CS - 1, y + CS - 1], fill=col)
        d.text((x + CS // 2, y + CS // 2), lab, fill="black", font=_font(13), anchor="mm")
    return img


def _panel(base, maze, res, k, radius):
    trace = res["trace"]
    k = min(k, len(trace) - 1)
    pos, t, _, slow = trace[k]
    col = AGENT_COLORS.get(res["agent"], (0, 0, 0))
    img = Image.new("RGB", (base.width, base.height + HEAD), (255, 255, 255))
    img.paste(base, (0, HEAD))
    d = ImageDraw.Draw(img)
    for p, _, _, _ in trace[: k + 1]:
        x, y = p[1] * CS + CS // 2, p[0] * CS + CS // 2 + HEAD
        q = max(1, CS // 7)
        d.ellipse([x - q, y - q, x + q, y + q], fill=col)
    if res["agent"] != "oracle":      # vision window
        x0 = (pos[1] - radius) * CS
        y0 = (pos[0] - radius) * CS + HEAD
        s = (2 * radius + 1) * CS
        d.rectangle([x0, y0, x0 + s - 1, y0 + s - 1], outline=col, width=2)
    x, y = pos[1] * CS + CS // 2, pos[0] * CS + CS // 2 + HEAD
    ring = C_MUD if slow else "black"
    q = max(3, CS // 3)
    d.ellipse([x - q, y - q, x + q, y + q], fill=col, outline=ring, width=3 if slow else 2)

    done = k == len(trace) - 1
    status = ("REACHED" if res["success"] else "FAILED") if done else ("SLOWED" if slow else "")
    over = t > res["limit"]
    d.text((6, 4), res["agent"].upper(), fill=col, font=_font(16))
    d.text((6, 24), f"t = {t:5.1f}s / limit {res['limit']:.1f}s", fill=(200, 0, 0) if over else (40, 40, 40), font=_font(13))
    scol = C_MUD if status == "SLOWED" else ((0, 140, 0) if res["success"] else (200, 0, 0))
    d.text((base.width - 6, 6), status, fill=scol, font=_font(14), anchor="ra")
    return img


def render(maze, results, out, radius=2, max_frames=300, ms=110):
    global CS
    CS = max(6, min(22, 640 // maze.n))   # shrink cells so big maps still fit
    base = _base(maze)
    longest = max(len(r["trace"]) for r in results)
    stride = max(1, -(-longest // max_frames))
    ks = list(range(0, longest, stride)) + [longest - 1]
    W = len(results) * base.width + (len(results) - 1) * GAP
    H = base.height + HEAD
    frames = []
    for k in ks:
        frame = Image.new("RGB", (W, H), (255, 255, 255))
        for i, res in enumerate(results):
            frame.paste(_panel(base, maze, res, k, radius), (i * (base.width + GAP), 0))
        frames.append(frame)
    frames += [frames[-1]] * 15   # pause on final frame
    frames[0].save(out + ".gif", save_all=True, append_images=frames[1:], duration=ms, loop=0)
    frames[-1].save(out + ".png")

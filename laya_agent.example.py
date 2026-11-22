"""
Template for the Laya agent. Copy to laya_agent.py and fill in predict().
server.py and maze_sim.LayaAgent pick it up automatically.

Same information as the obstacle-aware A* agent: a 5x5 view, the GPS hint and its own
slowdown status. No full map.
"""


def predict(state_text: str, obs: dict) -> str:
    """Return "up", "down", "left" or "right".

    state_text : one-sentence description of the situation (see README)
    obs        : the same information as a dict (neighbors, view, slowed, gps_move, ...)
    """
    # Placeholder: follow the GPS. Replace with a Laya call, e.g. a "choice" question with
    # labels ["up", "down", "left", "right"] on state_text.
    return obs["gps_move"]

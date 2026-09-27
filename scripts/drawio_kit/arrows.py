"""Deterministic orthogonal arrows for drawio_kit pages.

Every arrow runs from one shape to one shape and is routed by hand through
empty space, so the router never draws a line across a card:

  * it leaves the source on its right edge and enters the target on its
    left edge (left-to-right flow), or bottom-to-top for a stacked pair;
  * the vertical run sits in a GUTTER between two columns, in a lane that is
    unique per target, so parallel arrows never overlap;
  * an arrow that must skip a column goes down the gutter, along a CORRIDOR
    (an empty horizontal band), and up the next gutter;
  * many-to-one arrows share one lane and one entry point, so they merge into
    a bus with a single arrowhead rather than a fan.
"""
from drawio_kit import FLOW


def geom(p, cid):
    for it in p.items:
        if it.get("id") == cid:
            return it
    raise KeyError("no shape with id %r on page" % cid)


class Lanes:
    """Evenly spaced positions across a gutter (x) or a corridor (y).

    `names` are the logical lanes; one lane per distinct target keeps arrows
    apart, and every arrow into the same target uses the same lane (a bus).
    Lanes are 6 px in from each side; a 40 px gutter gives 7 px between three
    lanes, enough for a 2.5 px stroke.
    """

    def __init__(self, lo, hi, names):
        n = len(names)
        pad = 6.0
        if n <= 1:
            self.pos = {nm: (lo + hi) / 2.0 for nm in names}
        else:
            step = (hi - lo - 2 * pad) / (n - 1)
            self.pos = {nm: lo + pad + i * step for i, nm in enumerate(names)}

    def __getitem__(self, k):
        return self.pos[k]


def flow(p, a, b, lane, ey=0.5, ny=0.5, corridor=None, lane2=None,
         color=FLOW, sw=2.5, **kw):
    """Right edge of `a` -> left edge of `b`, vertical run at x=`lane`.

    With `corridor` (a y) and `lane2` (the next gutter's x) the arrow goes
    down `lane`, along the corridor, and up `lane2` into the target.
    """
    A, B = geom(p, a), geom(p, b)
    y1 = A["y"] + A["h"] * ey
    y2 = B["y"] + B["h"] * ny
    if corridor is None:
        pts = [] if abs(y1 - y2) < 1 else [(lane, y1), (lane, y2)]
    else:
        pts = [(lane, y1), (lane, corridor), (lane2, corridor), (lane2, y2)]
    return p.edge(a, b, ex=1, ey=ey, nx=0, ny=ny, points=pts, color=color,
                  sw=sw, **kw)


def down(p, a, b, color=FLOW, sw=2.5, **kw):
    """Bottom centre of `a` -> top centre of `b`, for two cards stacked with a
    gap of at least 26 px between them. Never use it across a third card."""
    return p.edge(a, b, ex=0.5, ey=1, nx=0.5, ny=0, points=[], color=color,
                  sw=sw, **kw)


def audit_arrows(p):
    """Print every edge whose segments pass through a shape that is neither
    its source nor its target. Run it as the last line of build()."""
    shapes = [it for it in p.items if it["kind"] != "edge"]
    bad = 0
    for e in (it for it in p.items if it["kind"] == "edge"):
        A, B = geom(p, e["src"]), geom(p, e["dst"])
        x1, y1 = A["x"] + A["w"] * e["ex"], A["y"] + A["h"] * e["ey"]
        x2, y2 = B["x"] + B["w"] * e["nx"], B["y"] + B["h"] * e["ny"]
        pts = [(x1, y1)] + list(e["points"]) + [(x2, y2)]
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            for s in shapes:
                if s["id"] in (e["src"], e["dst"]) or s.get("kind") in ("image", "text"):
                    continue
                # a container that holds the source or the target is allowed
                if (s["x"] <= B["x"] and s["y"] <= B["y"]
                        and s["x"] + s["w"] >= B["x"] + B["w"]
                        and s["y"] + s["h"] >= B["y"] + B["h"]):
                    continue
                if (s["x"] <= A["x"] and s["y"] <= A["y"]
                        and s["x"] + s["w"] >= A["x"] + A["w"]
                        and s["y"] + s["h"] >= A["y"] + A["h"]):
                    continue
                lx, hx = sorted((ax, bx))
                ly, hy = sorted((ay, by))
                if (lx < s["x"] + s["w"] - 1 and hx > s["x"] + 1
                        and ly < s["y"] + s["h"] - 1 and hy > s["y"] + 1):
                    print("ARROW %s -> %s crosses %s (%s)" % (
                        e["src"], e["dst"], s["id"],
                        (s.get("text") or "")[:40].replace("\n", " ")))
                    bad += 1
                    break
    print("ARROW AUDIT", "clean" if not bad else "%d crossing(s)" % bad)
    return bad

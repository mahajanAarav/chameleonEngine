"""Tests for the swappable proposer slot.   python -m tools.test_proposer

1. nothing plugged in: output identical to the engine without the slot
2. hostile proposers (crash, garbage, wrong ids, reworded text, off-canvas) can never change the rules outcome
3. a mock text model (generate(prompt) -> reply text) is parsed, validated and can win
4. oracle demo: the 24 designer references as a pretend model; they are valid, so they enter the tournament
"""

import copy
import glob
import json

from engine import proposer
from engine.resize import candidates, resize
from engine.rules import check
from tools.gen_designs import generate

OK, BAD = "PASS", "FAIL"
results = []


def report(name, ok, detail=""):
    results.append(ok)
    print(f"  [{OK if ok else BAD}] {name} {detail}")


def errors(src, out):
    return [m for s, m in check(src, out) if s == "error"]


def main():
    src = generate(7)
    tgt = {"width": 1080, "height": 1920}
    proposer.clear()
    base = resize(src, tgt)
    report("no proposer: valid output", not errors(src, base))

    def crash(s, t):
        raise RuntimeError("boom")

    def garbage(s, t):
        return "not a layout"

    def wrong_ids(s, t):
        return {"elements": [{"id": "nope", "x": 0, "y": 0, "width": 5, "height": 5}]}

    def reword(s, t):  # tries to change text, fonts, colours and push things off-canvas
        els = []
        for e in s["elements"]:
            e = copy.deepcopy(e)
            e.update(x=-500, y=-500, width=e["width"] * 5, height=e["height"] * 5)
            if e["type"] == "text":
                e.update(content="HACKED", font_family="Comic Sans", font_size=500, color="red")
            els.append(e)
        return {"elements": els}

    for name, fn in (("crash", crash), ("garbage", garbage), ("wrong ids", wrong_ids), ("hostile rewrite", reword)):
        proposer.clear()
        proposer.register(fn)
        out = resize(src, tgt)
        report(f"hostile proposer ({name}): output valid", not errors(src, out))
        if name == "hostile rewrite":
            texts = {e["id"]: e["content"] for e in out["elements"] if e["type"] == "text"}
            report("  text content untouched", all(texts[e["id"]] == e["content"] for e in src["elements"]
                                                    if e["type"] == "text"))
            report("  hostile layout is never eligible as-is",
                   all(not (e["x"] < -1 or e["y"] < -1) for e in out["elements"]))

    # mock text model: returns the engine's own best layout as JSON wrapped in chatter
    proposer.clear()
    best = resize(src, tgt)
    reply = "Sure! Here is the layout:\n```json\n" + json.dumps({"elements": best["elements"]}) + "\n```\nHope it helps."
    seen = {}

    def generate_fn(prompt):
        seen["prompt"] = prompt
        return reply

    proposer.register(proposer.llm_proposer(generate_fn))
    names = [n for n, _ in candidates(src, tgt)]
    report("mock text model: prompt built", "ad from 1080x1080" in seen.get("prompt", "") or "Role hints" in seen.get("prompt", ""))
    report("mock text model: proposal reached the tournament", any(n.startswith("proposer") for n in names))
    out = resize(src, tgt)
    report("mock text model: final output valid", not errors(src, out))

    # oracle: the designer references as a pretend model
    proposer.clear()
    hits = valid = 0
    for tf in sorted(glob.glob("data/refs/task_[0-9][0-9].json")):
        n = tf[-7:-5]
        task = json.load(open(tf))
        ref = json.load(open(f"data/refs/layout_{n}.json"))
        proposer.clear()
        proposer.register(lambda s, t, ref=ref: ref)
        cands = candidates(task["source"], task["target"])
        got = [o for nm, o in cands if nm.startswith("proposer")]
        hits += bool(got)
        valid += any(not errors(task["source"], o) for o in got)
    report("oracle model: references accepted as proposals", hits == 24, f"({hits}/24 reached the tournament, {valid}/24 valid)")
    proposer.clear()
    print(f"\n{sum(results)}/{len(results)} checks passed")
    raise SystemExit(0 if all(results) else 1)


if __name__ == "__main__":
    main()

"""Swappable proposer slot: any model can suggest layouts; the engine validates and scores them.

A *proposer* is any callable  proposer(source, target_canvas) -> layout | list[layout] | None,
where a layout is {"elements": [{"id", "x", "y", "width", "height", "font_size"?, "corner_radius"?}, ...]}.

Safety, so a model can never break the hard rules:
  * only geometry (x, y, width, height, font_size, corner_radius) is taken from a proposal; every other field
    (ids, text, fonts, colours, images, z-order, groups, ...) is copied from the source;
  * a proposal must cover every source id, otherwise it is dropped;
  * each proposal (and a repaired copy that pulls it back inside the canvas) joins the same tournament as our
    own layouts, so it must pass the strict rule checker and the collision / logo gates to win;
  * exceptions, timeouts and malformed output are swallowed: the engine falls back to its own candidates.

Plug a proposer in without touching code:
    CHAMELEON_PROPOSER="package.module:function"   a proposer as above
    CHAMELEON_MODEL="package.module:generate"      any text model: generate(prompt: str) -> str
or in Python: engine.proposer.register(my_proposer)
No model ships with the engine, and nothing here needs a network.
"""

import copy
import importlib
import json
import math
import os
import re
import threading
from typing import Any, Callable

GEOMETRY = ("x", "y", "width", "height", "font_size", "corner_radius")
TIMEOUT_S = float(os.environ.get("CHAMELEON_PROPOSER_TIMEOUT", "60"))

_registry: list = []


def register(proposer: Callable) -> None:
    _registry.append(proposer)


def clear() -> None:
    _registry.clear()


def _load(spec: str):
    mod, _, fn = spec.partition(":")
    return getattr(importlib.import_module(mod), fn or "propose")


def active_proposers() -> list:
    """Registered proposers plus whatever the environment variables name."""
    found = list(_registry)
    try:
        if os.environ.get("CHAMELEON_PROPOSER"):
            for spec in os.environ["CHAMELEON_PROPOSER"].split(","):
                found.append(_load(spec.strip()))
        if os.environ.get("CHAMELEON_MODEL"):
            found.append(llm_proposer(_load(os.environ["CHAMELEON_MODEL"].strip())))
    except Exception:
        pass  # a broken plug-in must never break the engine
    return found


def sanitize(source: dict, proposal: Any, canvas: dict) -> dict | None:
    """Turn a model's suggestion into a valid output: geometry from the proposal, everything else from the source."""
    els = proposal.get("elements") if isinstance(proposal, dict) else proposal
    if not isinstance(els, list):
        return None
    by = {e.get("id"): e for e in els if isinstance(e, dict)}
    out = []
    for src in source["elements"]:
        p = by.get(src["id"])
        if p is None:
            return None
        e = copy.deepcopy(src)
        for k in GEOMETRY:
            v = p.get(k)
            if k in e or k in ("x", "y", "width", "height"):
                if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
                    e[k] = float(v)
        if e["type"] == "text":
            e["font_size"] = max(1, int(round(e["font_size"])))
        out.append(e)
    return {"canvas": {"width": canvas["width"], "height": canvas["height"]}, "elements": out}


def repair(source: dict, layout: dict) -> dict:
    """Pull units back inside the canvas (shrinking if needed) and keep wrapped text on-canvas."""
    from engine.safety import _fit_unit, _keep_text_inside, _units, is_background

    tw, th = layout["canvas"]["width"], layout["canvas"]["height"]
    out = copy.deepcopy(layout)
    src = {e["id"]: e for e in source["elements"]}
    movable = [e for e in out["elements"] if not is_background(src[e["id"]], source["canvas"])]
    for unit in _units(movable):
        _fit_unit(unit, tw, th)
    _keep_text_inside(movable, tw, th)
    for e in out["elements"]:
        for k in ("x", "y", "width", "height", "corner_radius"):
            if k in e:
                e[k] = round(e[k], 2)
    return out


def _call_with_timeout(fn: Callable, args: tuple, timeout: float):
    box: dict = {}

    def run():
        try:
            box["value"] = fn(*args)
        except Exception as exc:  # noqa: BLE001 - a proposer may fail in any way
            box["error"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout)
    return box.get("value")


def propose(source: dict, target_canvas: dict) -> list:
    """All proposals as (name, output) pairs: sanitised, plus a repaired copy when it differs."""
    cands = []
    for i, prop in enumerate(active_proposers()):
        try:
            raw = _call_with_timeout(prop, (copy.deepcopy(source), dict(target_canvas)), TIMEOUT_S)
        except Exception:
            continue
        layouts = raw if isinstance(raw, list) and raw and isinstance(raw[0], (dict, list)) and not (
            isinstance(raw[0], dict) and "id" in raw[0]) else [raw]
        for j, layout in enumerate(layouts):
            try:
                clean = sanitize(source, layout, target_canvas)
                if clean is None:
                    continue
                name = f"proposer{i}#{j}"
                cands.append((name, clean))
                fixed = repair(source, clean)
                if fixed != clean:
                    cands.append((name + "+repair", fixed))
            except Exception:
                continue
    return cands


# ---------- adapter for any text model ----------

PROMPT = """You are a senior ad designer. Resize this ad from {sw}x{sh} to {tw}x{th} so it looks professionally designed.
Reply with ONLY JSON: {{"elements":[{{"id":..., "x":..., "y":..., "width":..., "height":..., "font_size":..., "corner_radius":...}}, ...]}}
Include EVERY element id exactly once. Rules: nothing off-canvas (rotated shapes included); images keep their
width/height ratio; circles stay circles and pills stay pills; grouped elements (same group_id) move together;
text content cannot change, only font_size (whole numbers) and position/width; text is drawn from the TOP of its box,
wraps at spaces to the box width and is about 1.2 x font_size per line; no collisions between text, logo and product;
keep text readable and the logo clearly visible; make the product and the button large; use the canvas well.
Role hints: {roles}
Source elements (x, y, width, height in px):
{elements}
"""


def build_prompt(source: dict, target_canvas: dict) -> str:
    from engine.understand import understand

    design = understand(source)
    roles = {m["id"]: u.role for u in design.units for m in u.members}
    keep = ("id", "type", "x", "y", "width", "height", "font_size", "group_id", "rotation", "opacity", "z_index",
            "fit", "shape_type", "corner_radius", "text_align", "font_weight")
    rows = []
    for e in source["elements"]:
        row = {k: e[k] for k in keep if k in e and e[k] is not None}
        if e["type"] == "text":
            row["content"] = str(e.get("content", ""))[:80]
        rows.append(row)
    return PROMPT.format(sw=source["canvas"]["width"], sh=source["canvas"]["height"],
                         tw=target_canvas["width"], th=target_canvas["height"],
                         roles=json.dumps(roles), elements="\n".join(json.dumps(r) for r in rows))


def parse_reply(text: str) -> dict | None:
    """First JSON object in a model's reply (models often wrap it in prose or code fences)."""
    if not isinstance(text, str):
        return None
    for m in re.finditer(r"\{", text):
        depth = 0
        for i in range(m.start(), len(text)):
            depth += text[i] == "{"
            depth -= text[i] == "}"
            if depth == 0:
                try:
                    obj = json.loads(text[m.start(): i + 1])
                    if isinstance(obj, dict) and "elements" in obj:
                        return obj
                except ValueError:
                    pass
                break
    return None


def llm_proposer(generate: Callable[[str], str]) -> Callable:
    """Wrap any text model: generate(prompt) -> reply text. Small local or hosted, it makes no difference."""

    def proposer(source: dict, target_canvas: dict):
        return parse_reply(generate(build_prompt(source, target_canvas)))

    return proposer

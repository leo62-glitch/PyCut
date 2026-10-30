"""Derive default objects for CapCut material groups from the inferred schema.

Usage: python tools/make_capcut_defaults.py capcut_draft_schema.json pycut/resources/capcut_defaults.json
A field observed with a single constant value in every real draft keeps that value;
everything else gets a neutral default (\"\" / 0 / false / [] / {}).
"""
import json
import sys

GROUPS = ["audios", "beats", "audio_fades", "loudnesses", "transitions", "video_effects",
          "chromas", "common_mask", "audio_effects", "stickers"]


def default_for(node):
    types = node.get("types", {})
    if not types:
        return None
    t = max(types, key=types.get)
    if t == "object":
        return {k: default_for(v) for k, v in node.get("properties", {}).items()}
    if t == "array":
        return []
    if t == "bool":
        return False
    if t in ("int", "float"):
        lo, hi = node.get("min"), node.get("max")
        if lo is not None and lo == hi:
            return lo
        return 0 if t == "int" else 0.0
    if t == "str":
        ex = node.get("examples", [])
        if len(ex) == 1 and node.get("presence", 1) == 1.0:
            return ex[0]
        return ""
    return None  # null


def main(schema_path, out_path):
    s = json.load(open(schema_path, encoding="utf-8"))
    mats = s["draft_content"]["properties"]["materials"]["properties"]
    out = {}
    for g in GROUPS:
        items = mats.get(g, {}).get("items", {}).get("properties")
        if items:
            out[g] = {k: default_for(v) for k, v in items.items()}
    meta = s["draft_meta_info"]["properties"]
    out["draft_meta_info"] = {k: default_for(v) for k, v in meta.items()}
    store = s["root_meta_info"]["properties"]["all_draft_store"]["items"]["properties"]
    out["root_store_item"] = {k: default_for(v) for k, v in store.items()}
    json.dump(out, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main(*sys.argv[1:3])

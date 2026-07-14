"""Pure rule evaluation for auto-approve/routing rules.

A rule is ``{"conditions": {...}, "actions": {...}}``:

conditions (all present ones must match — AND semantics, like seerr #1184):
- ``requester``       — chat id or friendly name (case-insensitive)
- ``media_type``      — "tv" | "movie"
- ``max_seasons``     — int; matches TV requests with at most N seasons
- ``min_year`` / ``max_year`` — int bounds on release year
- ``title_contains``  — case-insensitive substring
- ``genre``           — case-insensitive membership in the item's genres

actions:
- ``approve``            — True → the request is auto-approved
- ``quality_profile_id`` — override on the Sonarr/Radarr add
- ``root_folder``        — override on the Sonarr/Radarr add

Evaluation input is a plain dict describing the request:
``{requester, requester_name, media_type, title, year, season_count, genres}``.
Missing request fields fail the condition (unknown ≠ match) — the same
"unknown state = no action" fail-safe the cleanup engine uses.
"""


def rule_matches(conditions: dict, request: dict) -> bool:
    for key, expected in conditions.items():
        if key == "requester":
            actual = {str(request.get("requester", "")).lower(),
                      str(request.get("requester_name", "")).lower()}
            if str(expected).lower() not in actual:
                return False
        elif key == "media_type":
            if request.get("media_type") != expected:
                return False
        elif key == "max_seasons":
            count = request.get("season_count")
            if count is None or int(count) > int(expected):
                return False
        elif key == "min_year":
            year = _as_int(request.get("year"))
            if year is None or year < int(expected):
                return False
        elif key == "max_year":
            year = _as_int(request.get("year"))
            if year is None or year > int(expected):
                return False
        elif key == "title_contains":
            if str(expected).lower() not in str(request.get("title", "")).lower():
                return False
        elif key == "genre":
            genres = [str(g).lower() for g in (request.get("genres") or [])]
            if str(expected).lower() not in genres:
                return False
        else:
            return False  # unknown condition key: never match (fail safe)
    return True


def evaluate_auto_approve(rules: list[dict], request: dict) -> dict | None:
    """First matching auto_approve rule's actions, or None."""
    for rule in rules:
        if rule.get("kind") != "auto_approve":
            continue
        if rule_matches(rule.get("conditions", {}), request):
            return rule.get("actions", {})
    return None


def describe_rule(rule: dict) -> str:
    """One-line human summary of a stored rule."""
    conds = rule.get("conditions", {})
    acts = rule.get("actions", {})
    cond_bits = [f"{k}={v}" for k, v in conds.items()] or ["always"]
    act_bits = []
    if acts.get("approve"):
        act_bits.append("auto-approve")
    if acts.get("quality_profile_id"):
        act_bits.append(f"profile {acts['quality_profile_id']}")
    if acts.get("root_folder"):
        act_bits.append(f"→ {acts['root_folder']}")
    if rule.get("kind") == "retention":
        act_bits = [f"keep newest {acts.get('keep_last', '?')} episodes"]
    return f"#{rule.get('id', '?')} [{rule.get('kind')}] " \
           f"{', '.join(cond_bits)} ⇒ {', '.join(act_bits) or 'no action'}"


def _as_int(value) -> int | None:
    try:
        return int(str(value)[:4])
    except (TypeError, ValueError):
        return None

"""Tests for the deterministic domain router."""
from src.graphs.router import CORE, DOMAIN_KEYWORDS, route


def test_clear_domain_routing():
    assert route("what tv shows am I monitoring?") == "tv"
    assert route("list my movies") == "movies"
    assert route("pause the sabnzbd queue") == "downloads"
    assert route("check youtube subscriptions") == "youtube"
    assert route("download my audible audiobooks") == "audio"
    assert route("verify my snes roms") == "roms"
    assert route("is everything healthy? disk space?") == "system"
    assert route("find duplicates in the library") == "library"


def test_generic_requests_fall_through_to_core():
    # No domain keywords at all
    assert route("add severance") == CORE
    assert route("get me the latest from Denis Villeneuve") == CORE
    assert route("") == CORE


def test_ties_route_to_core():
    # 'movie' (movies) vs 'torrent' (downloads) — one hit each
    assert route("add this movie torrent") == CORE


def test_routing_is_deterministic():
    text = "what tv shows are airing this season?"
    assert all(route(text) == route(text) for _ in range(5))


def test_keyword_sets_are_disjoint_enough():
    # A keyword appearing in two domains makes routing unstable — forbid it.
    seen: dict[str, str] = {}
    for domain, words in DOMAIN_KEYWORDS.items():
        for w in words:
            assert w not in seen, f"{w!r} in both {seen.get(w)} and {domain}"
            seen[w] = domain

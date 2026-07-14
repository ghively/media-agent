"""Domain-scoped tool binding for the LLM path.

92 tool schemas are a heavy lift for a small model: they eat context and
degrade tool selection. When a router-missed message clearly belongs to one
domain, the agent runs with ONLY that domain's tools (plus a tiny core), so
even very lightweight models pick correctly from a short menu. Ambiguous or
domain-free messages still get the full toolset.

The classifier is deterministic keyword matching — no LLM involved — and it
must only fire on *unambiguous* signals: a wrong scope is worse than no
scope, so ties and zero-hit messages return None (→ full agent).
"""
import re

# Included in every scope: cross-domain questions a scoped conversation
# still commonly needs ("is it in the library yet?", "what's downloading?").
CORE_TOOLS = ["emby_search", "check_queue_status", "check_all_health"]

# domain → (keyword regex, tool names). Keep keywords distinctive: generic
# words ("queue", "search", "download") deliberately appear nowhere or in
# one domain only.
DOMAINS: dict[str, tuple[str, list[str]]] = {
    "tv_movies": (
        # "shows?(?! me)": "list my shows" counts, generic "show me" doesn't.
        r"\b(?:tv|shows?(?! me)|series|episodes?|seasons?|movies?|films?|sonarr|"
        r"radarr|airing|cinema|emby|plex|watch(?:ing)?|calendar)\b",
        ["search_tv", "add_tv_show", "list_tv_shows", "get_tv_queue",
         "get_tv_history", "search_missing_episodes", "get_tv_calendar",
         "get_tv_health", "sonarr_list_quality_profiles",
         "sonarr_list_root_folders", "refresh_tv_show", "search_season",
         "search_movie", "add_movie", "list_movies", "get_movie_queue",
         "get_movie_history", "search_missing_movies", "get_movie_health",
         "radarr_list_quality_profiles", "radarr_list_root_folders",
         "refresh_movie", "emby_recent", "emby_libraries", "emby_scan",
         "emby_get_item", "search_media", "download_media"],
    ),
    "downloads": (
        r"\b(?:sabnzbd|usenet|nzb|torrents?|magnet|qbittorrent|qbit|"
        r"download station|seeding|indexers?|prowlarr|downloads?(?:ing)?)\b",
        ["sabnzbd_queue", "sabnzbd_history", "sabnzbd_status", "sabnzbd_pause",
         "sabnzbd_resume", "sabnzbd_add_nzb", "download_station_list",
         "download_station_add", "download_station_pause",
         "download_station_resume", "download_station_info",
         "download_station_stats", "qbittorrent_list", "qbittorrent_add",
         "qbittorrent_pause", "qbittorrent_resume", "prowlarr_search",
         "prowlarr_indexers", "check_disk_space"],
    ),
    "music": (
        r"\b(?:music|songs?|albums?|artists?|bandcamp|lidarr|band|discography)\b",
        ["bandcamp_download", "bandcamp_download_collection", "search_artist",
         "add_artist", "list_artists", "get_music_queue"],
    ),
    "audiobooks": (
        r"\b(?:audio ?books?|audible|asin|narrat(?:or|ed))\b",
        ["audible_list_library", "audible_download", "audible_download_new",
         "audible_setup_auth", "audible_check_auth"],
    ),
    "podcasts": (
        r"\b(?:podcasts?|rss|feeds?)\b",
        ["podcast_subscribe", "podcast_unsubscribe",
         "podcast_list_subscriptions", "podcast_check_new"],
    ),
    "video_online": (
        r"\b(?:youtube|youtu\.be|twitch|streams?(?:ing|er)?|channels?|"
        r"videos?|uploads?|clips?)\b",
        ["youtube_download", "youtube_add_subscription",
         "youtube_list_subscriptions", "youtube_check_subscriptions",
         "youtube_get_info", "youtube_remove_subscription",
         "twitch_check_live", "twitch_record", "twitch_recordings"],
    ),
    "books_comics": (
        r"\b(?:comics?|manga|komga|ebooks?|calibre|epub|books?|novels?)\b",
        ["komga_search", "komga_recent", "komga_scan",
         "calibre_search", "calibre_recent"],
    ),
    "games": (
        r"\b(?:roms?|games?|emulat(?:or|ion)|nes|snes|n64|gba|gbc|psx|ps2|"
        r"genesis|dreamcast|no-intro|redump|dat)\b",
        ["rom_search_archive", "rom_download", "rom_verify_dat",
         "rom_get_collection", "rom_scan_library", "rom_inspect",
         "rom_find_duplicates", "rom_check_problems"],
    ),
    "library_files": (
        r"\b(?:duplicates?|naming|renam(?:e|ing)|inventory|folders?|files?|"
        r"undo|cleanup)\b",
        ["library_build_inventory", "library_find_duplicates",
         "library_check_naming", "library_fix_naming", "library_undo_rename",
         "emby_scan"],
    ),
}

_COMPILED = {name: (re.compile(pattern, re.IGNORECASE), tools)
             for name, (pattern, tools) in DOMAINS.items()}


def classify(text: str) -> str | None:
    """Return the single unambiguous domain for *text*, else None.

    A domain wins only when it has strictly more keyword hits than every
    other domain — ties and no-hits go to the full agent.
    """
    if not text:
        return None
    scores = {name: len(regex.findall(text))
              for name, (regex, _) in _COMPILED.items()}
    best = max(scores, key=scores.get)
    best_score = scores[best]
    if best_score == 0:
        return None
    if sum(1 for s in scores.values() if s == best_score) > 1:
        return None
    return best


def tools_for_domain(domain: str) -> list[str]:
    """Tool names for a domain, core tools included."""
    _, tools = DOMAINS[domain]
    return list(dict.fromkeys(tools + CORE_TOOLS))

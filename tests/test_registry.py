"""Tests that the tool registry loads every tool group and stays consistent."""
from src.tools.registry import all_tools

EXPECTED_TOOLS = {
    # Sonarr
    "search_tv", "add_tv_show", "list_tv_shows", "get_tv_queue",
    "get_tv_history", "search_missing_episodes", "get_tv_calendar", "get_tv_health",
    # Radarr
    "search_movie", "add_movie", "list_movies", "get_movie_queue",
    "get_movie_history", "search_missing_movies", "get_movie_health",
    # Emby
    "emby_search", "emby_recent", "emby_libraries", "emby_scan", "emby_get_item",
    # Health
    "check_all_health", "check_disk_space", "check_queue_status",
    # Library
    "library_inventory", "library_find_duplicates", "library_check_naming",
    "library_fix_naming", "library_undo_rename",
    # Unified search
    "search_media", "download_media",
    # SABnzbd
    "sabnzbd_queue", "sabnzbd_history", "sabnzbd_status",
    "sabnzbd_pause", "sabnzbd_resume", "sabnzbd_add_nzb",
    # Download Station
    "download_station_list", "download_station_add",
    "download_station_pause", "download_station_resume",
    "download_station_info", "download_station_stats",
    # Bandcamp
    "bandcamp_download", "bandcamp_download_collection",
    # Audible
    "audible_list_library", "audible_download", "audible_download_new",
    "audible_setup_auth", "audible_check_auth",
    # ROMs
    "rom_search_archive", "rom_download", "rom_verify_dat", "rom_get_collection",
    # YouTube
    "youtube_download", "youtube_get_info",
    "youtube_add_subscription", "youtube_remove_subscription",
    "youtube_list_subscriptions", "youtube_check_subscriptions",
}


def test_all_expected_tools_registered():
    names = {t.name for t in all_tools}
    missing = EXPECTED_TOOLS - names
    assert not missing, f"Tools missing from registry: {sorted(missing)}"


def test_no_duplicate_tool_names():
    names = [t.name for t in all_tools]
    assert len(names) == len(set(names))


def test_every_tool_has_description():
    for t in all_tools:
        assert t.description and t.description.strip(), f"{t.name} has no description"


def test_system_prompt_only_references_real_tools():
    from src.graphs.conversational import build_system_prompt
    prompt = build_system_prompt(all_tools)
    for t in all_tools:
        assert t.name in prompt

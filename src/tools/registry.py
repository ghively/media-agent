"""Tool registry — imports all tools and exports the combined list.

Each tool group loads independently; if a module fails to import (missing
optional dependency, etc.) the failure is logged and the rest of the agent
keeps working with the remaining tools.
"""
import logging

logger = logging.getLogger(__name__)

all_tools: list = []


def _register(group: str, loader) -> None:
    """Load a tool group, logging (not crashing) on failure."""
    try:
        all_tools.extend(loader())
    except Exception as e:
        logger.warning("Tool group '%s' unavailable: %s: %s", group, type(e).__name__, e)


def _sonarr_tools():
    from src.tools.sonarr import (
        search_tv, add_tv_show, list_tv_shows, get_tv_queue,
        get_tv_history, search_missing_episodes, get_tv_calendar, get_tv_health,
    )
    return [search_tv, add_tv_show, list_tv_shows, get_tv_queue,
            get_tv_history, search_missing_episodes, get_tv_calendar, get_tv_health]


def _radarr_tools():
    from src.tools.radarr import (
        search_movie, add_movie, list_movies, get_movie_queue,
        get_movie_history, search_missing_movies, get_movie_health,
    )
    return [search_movie, add_movie, list_movies, get_movie_queue,
            get_movie_history, search_missing_movies, get_movie_health]


def _emby_tools():
    from src.tools.emby import (
        emby_search, emby_recent, emby_libraries, emby_scan, emby_get_item,
    )
    return [emby_search, emby_recent, emby_libraries, emby_scan, emby_get_item]


def _health_tools():
    from src.tools.health import check_all_health, check_disk_space, check_queue_status
    return [check_all_health, check_disk_space, check_queue_status]


def _library_tools():
    from src.tools.library import (
        library_inventory, library_find_duplicates, library_check_naming,
        library_fix_naming, library_undo_rename,
    )
    return [library_inventory, library_find_duplicates, library_check_naming,
            library_fix_naming, library_undo_rename]


def _search_tools():
    from src.tools.search import search_media, download_media
    return [search_media, download_media]


def _workflow_tools():
    from src.tools.workflows import (
        grab_media, system_report, sync_youtube, library_cleanup,
    )
    return [grab_media, system_report, sync_youtube, library_cleanup]


def _sabnzbd_tools():
    from src.tools.sabnzbd import (
        sabnzbd_queue, sabnzbd_history, sabnzbd_status,
        sabnzbd_pause, sabnzbd_resume, sabnzbd_add_nzb,
    )
    return [sabnzbd_queue, sabnzbd_history, sabnzbd_status,
            sabnzbd_pause, sabnzbd_resume, sabnzbd_add_nzb]


def _download_station_tools():
    from src.tools.download_station import (
        download_station_list, download_station_add,
        download_station_pause, download_station_resume,
        download_station_info, download_station_stats,
    )
    return [download_station_list, download_station_add,
            download_station_pause, download_station_resume,
            download_station_info, download_station_stats]


def _bandcamp_tools():
    from src.providers.bandcamp import bandcamp_download, bandcamp_download_collection
    return [bandcamp_download, bandcamp_download_collection]


def _audible_tools():
    from src.providers.audible import (
        audible_list_library, audible_download, audible_download_new,
        audible_setup_auth, audible_check_auth,
    )
    return [audible_list_library, audible_download, audible_download_new,
            audible_setup_auth, audible_check_auth]


def _rom_tools():
    from src.providers.rom import (
        rom_search_archive, rom_download, rom_verify_dat, rom_get_collection,
    )
    return [rom_search_archive, rom_download, rom_verify_dat, rom_get_collection]


def _youtube_tools():
    from src.providers.youtube import (
        youtube_download, youtube_get_info,
        youtube_add_subscription, youtube_remove_subscription,
        youtube_list_subscriptions, youtube_check_subscriptions,
    )
    return [youtube_download, youtube_get_info,
            youtube_add_subscription, youtube_remove_subscription,
            youtube_list_subscriptions, youtube_check_subscriptions]


_register("sonarr", _sonarr_tools)
_register("radarr", _radarr_tools)
_register("emby", _emby_tools)
_register("health", _health_tools)
_register("library", _library_tools)
_register("search", _search_tools)
_register("workflows", _workflow_tools)
_register("sabnzbd", _sabnzbd_tools)
_register("download_station", _download_station_tools)
_register("bandcamp", _bandcamp_tools)
_register("audible", _audible_tools)
_register("rom", _rom_tools)
_register("youtube", _youtube_tools)

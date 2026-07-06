"""Tool registry — imports all tools and exports the combined list.

All tool groups are first-class: imports are NOT wrapped in try/except, so a
broken tool module fails loudly at startup instead of silently shrinking the
agent's capabilities.

High-impact tools are wrapped with the approval gate (src/tools/approval.py)
according to the ``approvals:`` policy in settings.yaml.
"""
from src.tools.sonarr import (
    search_tv, add_tv_show, list_tv_shows, get_tv_queue,
    get_tv_history, search_missing_episodes, get_tv_calendar, get_tv_health,
    list_tv_profiles, remove_tv_show,
)
from src.tools.radarr import (
    search_movie, add_movie, list_movies, get_movie_queue,
    get_movie_history, search_missing_movies, get_movie_health,
    list_movie_profiles, remove_movie,
)
from src.tools.emby import (
    emby_search, emby_recent, emby_libraries, emby_scan, emby_get_item,
)
from src.tools.health import check_all_health, check_disk_space, check_queue_status
from src.tools.search import search_media, download_media
from src.tools.sabnzbd import (
    sabnzbd_queue, sabnzbd_history, sabnzbd_status,
    sabnzbd_pause, sabnzbd_resume, sabnzbd_add_nzb,
)
from src.tools.download_station import (
    download_station_list, download_station_add,
    download_station_pause, download_station_resume,
    download_station_info, download_station_stats,
)
from src.providers.bandcamp import bandcamp_download, bandcamp_download_collection
from src.providers.audible import (
    audible_list_library, audible_download, audible_download_new,
    audible_setup_auth, audible_check_auth,
)
from src.providers.rom import (
    rom_search_archive, rom_download, rom_verify_dat, rom_get_collection,
)
from src.providers.youtube import (
    youtube_download, youtube_add_subscription,
    youtube_list_subscriptions, youtube_check_subscriptions,
    youtube_remove_subscription, youtube_get_info,
)
from src.library.tools import (
    library_check_naming, library_sort_dir, library_undo_rename, library_inventory,
)
from src.tools.approval import apply_approval_policies
from src.audit import apply_audit

_raw_tools = [
    # TV / Sonarr
    search_tv, add_tv_show, list_tv_shows, get_tv_queue,
    get_tv_history, search_missing_episodes, get_tv_calendar, get_tv_health,
    list_tv_profiles, remove_tv_show,
    # Movies / Radarr
    search_movie, add_movie, list_movies, get_movie_queue,
    get_movie_history, search_missing_movies, get_movie_health,
    list_movie_profiles, remove_movie,
    # Library / Emby
    emby_search, emby_recent, emby_libraries, emby_scan, emby_get_item,
    # Health
    check_all_health, check_disk_space, check_queue_status,
    # Unified search
    search_media, download_media,
    # SABnzbd
    sabnzbd_queue, sabnzbd_history, sabnzbd_status,
    sabnzbd_pause, sabnzbd_resume, sabnzbd_add_nzb,
    # Download Station
    download_station_list, download_station_add,
    download_station_pause, download_station_resume,
    download_station_info, download_station_stats,
    # Bandcamp
    bandcamp_download, bandcamp_download_collection,
    # Audible
    audible_list_library, audible_download, audible_download_new,
    audible_setup_auth, audible_check_auth,
    # ROMs
    rom_search_archive, rom_download, rom_verify_dat, rom_get_collection,
    # YouTube
    youtube_download, youtube_add_subscription,
    youtube_list_subscriptions, youtube_check_subscriptions,
    youtube_remove_subscription, youtube_get_info,
    # Library organization
    library_check_naming, library_sort_dir, library_undo_rename, library_inventory,
]

# All tools for the LangGraph agent. Approval gate innermost, audit
# outermost — so approval-blocked calls are audited too, and every tool's
# output is length-capped before it reaches the model.
all_tools = apply_audit(apply_approval_policies(_raw_tools))

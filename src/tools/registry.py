"""Tool registry — imports all tools and exports the combined list."""
from src.tools.sonarr import (
    search_tv, add_tv_show, list_tv_shows, get_tv_queue,
    get_tv_history, search_missing_episodes, get_tv_calendar, get_tv_health,
    sonarr_list_quality_profiles, sonarr_list_root_folders,
    refresh_tv_show, search_season,
)
from src.tools.radarr import (
    search_movie, add_movie, list_movies, get_movie_queue,
    get_movie_history, search_missing_movies, get_movie_health,
    radarr_list_quality_profiles, radarr_list_root_folders,
    refresh_movie,
)
from src.tools.emby import (
    emby_search, emby_recent, emby_libraries, emby_scan, emby_get_item,
)
from src.tools.health import check_all_health, check_disk_space, check_queue_status
from src.providers.bandcamp import bandcamp_download, bandcamp_download_collection
from src.providers.audible import (
    audible_list_library, audible_download, audible_download_new,
    audible_setup_auth, audible_check_auth,
)
from src.providers.rom import (
    rom_search_archive, rom_download, rom_verify_dat, rom_get_collection,
)

# Optional tools — loaded only if their providers are available
try:
    from src.tools.sabnzbd import (
        sabnzbd_queue, sabnzbd_history, sabnzbd_status,
        sabnzbd_pause, sabnzbd_resume, sabnzbd_add_nzb,
    )
    _sabnzbd_tools = [sabnzbd_queue, sabnzbd_history, sabnzbd_status,
                       sabnzbd_pause, sabnzbd_resume, sabnzbd_add_nzb]
except ImportError:
    _sabnzbd_tools = []

try:
    from src.tools.search import search_media, download_media
    _search_tools = [search_media, download_media]
except ImportError:
    _search_tools = []

try:
    from src.tools.download_station import (
        download_station_list, download_station_add,
        download_station_pause, download_station_resume,
        download_station_info, download_station_stats,
    )
    _download_station_tools = [
        download_station_list, download_station_add,
        download_station_pause, download_station_resume,
        download_station_info, download_station_stats,
    ]
except ImportError:
    _download_station_tools = []

try:
    from src.providers.youtube import (
        youtube_download, youtube_add_subscription,
        youtube_list_subscriptions, youtube_check_subscriptions,
        youtube_get_info, youtube_remove_subscription,
    )
    _youtube_tools = [
        youtube_download, youtube_add_subscription,
        youtube_list_subscriptions, youtube_check_subscriptions,
        youtube_get_info, youtube_remove_subscription,
    ]
except ImportError:
    _youtube_tools = []

# ROM library analysis tools (identify / inspect / dedup / debug)
try:
    from src.tools.rom_tools import (
        rom_scan_library, rom_inspect, rom_find_duplicates, rom_check_problems,
    )
    _rom_library_tools = [
        rom_scan_library, rom_inspect, rom_find_duplicates, rom_check_problems,
    ]
except ImportError:
    _rom_library_tools = []

# Library management tools
try:
    from src.tools.library_tools import (
        library_build_inventory, library_find_duplicates,
        library_check_naming, library_fix_naming, library_undo_rename,
    )
    _library_tools = [
        library_build_inventory, library_find_duplicates,
        library_check_naming, library_fix_naming, library_undo_rename,
    ]
except ImportError:
    _library_tools = []

# All tools for the LangGraph agent
all_tools = (
    # TV / Sonarr
    [search_tv, add_tv_show, list_tv_shows, get_tv_queue,
     get_tv_history, search_missing_episodes, get_tv_calendar, get_tv_health,
     sonarr_list_quality_profiles, sonarr_list_root_folders,
     refresh_tv_show, search_season,
    # Movies / Radarr
     search_movie, add_movie, list_movies, get_movie_queue,
     get_movie_history, search_missing_movies, get_movie_health,
     radarr_list_quality_profiles, radarr_list_root_folders,
     refresh_movie,
    # Library / Emby
     emby_search, emby_recent, emby_libraries, emby_scan, emby_get_item,
    # Health
     check_all_health, check_disk_space, check_queue_status,
    # Bandcamp
     bandcamp_download, bandcamp_download_collection,
    # Audible
     audible_list_library, audible_download, audible_download_new,
     audible_setup_auth, audible_check_auth,
    # ROMs
     rom_search_archive, rom_download, rom_verify_dat, rom_get_collection,
    ] + _sabnzbd_tools + _search_tools + _download_station_tools + _youtube_tools
    + _library_tools + _rom_library_tools
)
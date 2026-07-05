"""Tool registry — imports all tools and exports the combined list."""
from src.tools.sonarr import (
    search_tv, add_tv_show, list_tv_shows, get_tv_queue,
    get_tv_history, search_missing_episodes, get_tv_calendar, get_tv_health,
)
from src.tools.radarr import (
    search_movie, add_movie, list_movies, get_movie_queue,
    get_movie_history, search_missing_movies, get_movie_health,
)
from src.tools.emby import (
    emby_search, emby_recent, emby_libraries, emby_scan, emby_get_item,
)
from src.tools.health import check_all_health, check_disk_space, check_queue_status

# All tools for the LangGraph agent
all_tools = [
    # TV / Sonarr
    search_tv, add_tv_show, list_tv_shows, get_tv_queue,
    get_tv_history, search_missing_episodes, get_tv_calendar, get_tv_health,
    # Movies / Radarr
    search_movie, add_movie, list_movies, get_movie_queue,
    get_movie_history, search_missing_movies, get_movie_health,
    # Library / Emby
    emby_search, emby_recent, emby_libraries, emby_scan, emby_get_item,
    # Health
    check_all_health, check_disk_space, check_queue_status,
]

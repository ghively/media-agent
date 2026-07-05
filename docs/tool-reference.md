# Media Agent Tool Reference

Complete reference for all 49 registered LangGraph tools in the media-agent project (plus 5 additional unregistered source functions documented for reference).

## Summary

| Category | Tools | Description |
|----------|-------|-------------|
| TV/Sonarr | 8 | TV show management via Sonarr API |
| Movies/Radarr | 7 | Movie management via Radarr API |
| Emby Library | 5 | Media library management via Emby API |
| Health | 3 | System health checks across services |
| SABnzbd | 5 | Usenet download client management |
| Download Station | 4 | Synology torrent management |
| Unified Search | 2 | Cross-source media search and download orchestration |
| YouTube | 4 | YouTube downloads and subscription management |
| Bandcamp | 2 | Bandcamp album/track downloads |
| Audible | 5 | Audible audiobook management |
| ROMs | 4 | Retro game ROM downloads and verification |

**Total: 49 tools registered** · 5 additional functions exist in source but are not yet in `registry.py`

---

## TV/Sonarr

### `search_tv(query: str) -> str`

Search for TV shows by name. Returns matching shows with titles, years, and tvdbIds.

**Parameters:**
- `query` (str): Search term for TV show name

**API Called:** Sonarr v3 API - `GET /api/v3/series/lookup`

**Example:**
```bash
search_tv(query="breaking bad")
```

**Returns:** Formatted list of TV shows with tvdbIds, e.g.:
```
Found 2 result(s):
  1. Breaking Bad (2008) [tvdbId: 81189]
  2. Better Call Saul (2015) [tvdbId: 275149]
```

---

### `add_tv_show(tvdb_id: int, title: str) -> str`

Add a TV show to the monitored library by its TVDB ID.

**Parameters:**
- `tvdb_id` (int): TVDB ID of the show (from search_tv)
- `title` (str): Show title

**API Called:** Sonarr v3 API - `POST /api/v3/series`

**Example:**
```bash
add_tv_show(tvdb_id=81189, title="Breaking Bad")
```

**Returns:** Confirmation with show details, e.g.:
```
✅ Added 'Breaking Bad' (tvdbId: 81189) to the library. Searching for episodes...
```

---

### `list_tv_shows() -> str`

List all monitored TV shows.

**Parameters:** None

**API Called:** Sonarr v3 API - `GET /api/v3/series`

**Example:**
```bash
list_tv_shows()
```

**Returns:** Formatted list of monitored shows with season/episode counts, e.g.:
```
Monitoring 12 show(s):
  • Breaking Bad — 5 seasons, 62 episodes
  • The Wire — 5 seasons, 60 episodes
```

---

### `get_tv_queue() -> str`

Check current Sonarr download queue.

**Parameters:** None

**API Called:** Sonarr v3 API - `GET /api/v3/queue`

**Example:**
```bash
get_tv_queue()
```

**Returns:** Queue items with status and progress, e.g.:
```
2 item(s) in queue:
  • Breaking Bad S03E01 — downloading
  • The Wire S01E01 — queued
```

---

### `get_tv_history() -> str`

Show recent Sonarr activity (grabs and imports).

**Parameters:** None

**API Called:** Sonarr v3 API - `GET /api/v3/history?pageSize=15`

**Example:**
```bash
get_tv_history()
```

**Returns:** Recent activity log, e.g.:
```
Recent activity (15 events):
  • [downloadImported] Breaking Bad
  • [grabbed] The Wire
  • [seriesDeleted] Some Show
```

---

### `search_missing_episodes() -> str`

Trigger a search for missing/wanted episodes.

**Parameters:** None

**API Called:** Sonarr v3 API - `POST /api/v3/command` with name "MissingEpisodesSearch"

**Example:**
```bash
search_missing_episodes()
```

**Returns:** Confirmation, e.g.:
```
✅ Missing episodes search triggered.
```

---

### `get_tv_calendar() -> str`

Show upcoming/airing episodes (next 7 days).

**Parameters:** None

**API Called:** Sonarr v3 API - `GET /api/v3/calendar?start=...&end=...`

**Example:**
```bash
get_tv_calendar()
```

**Returns:** Scheduled episodes with dates, e.g.:
```
Upcoming episodes (5):
  • 2025-01-15 — Breaking Bad S03E02 - Down
  • 2025-01-16 — The Wire S01E02 - The Detail
```

---

### `get_tv_health() -> str`

Check Sonarr health status.

**Parameters:** None

**API Called:** Sonarr v3 API - `GET /api/v3/health`

**Example:**
```bash
get_tv_health()
```

**Returns:** Health check results, e.g.:
```
✅ Sonarr health: all checks passing.
```
or
```
⚠️ Sonarr health issues (1):
  • [downloadClientStalled] Download client not responding
```

---

## Movies/Radarr

### `search_movie(query: str) -> str`

Search for movies by name. Returns matching movies with titles, years, and tmdbIds.

**Parameters:**
- `query` (str): Search term for movie name

**API Called:** Radarr v3 API - `GET /api/v3/movie/lookup`

**Example:**
```bash
search_movie(query="the matrix")
```

**Returns:** Formatted list of movies with tmdbIds, e.g.:
```
Found 3 result(s):
  1. The Matrix (1999) [tmdbId: 603]
  2. The Matrix Reloaded (2003) [tmdbId: 604]
  3. The Matrix Revolutions (2003) [tmdbId: 605]
```

---

### `add_movie(tmdb_id: int, title: str) -> str`

Add a movie to the monitored library by its TMDb ID.

**Parameters:**
- `tmdb_id` (int): TMDb ID of the movie (from search_movie)
- `title` (str): Movie title

**API Called:** Radarr v3 API - `POST /api/v3/movie`

**Example:**
```bash
add_movie(tmdb_id=603, title="The Matrix")
```

**Returns:** Confirmation with movie details, e.g.:
```
✅ Added 'The Matrix' (tmdbId: 603) to the library. Searching...
```

---

### `list_movies() -> str`

List all monitored movies.

**Parameters:** None

**API Called:** Radarr v3 API - `GET /api/v3/movie`

**Example:**
```bash
list_movies()
```

**Returns:** Formatted list of monitored movies with download status, e.g.:
```
Monitoring 42 movie(s):
  • The Matrix (1999) [✓]
  • Inception (2010) [✓]
  • Dune (2021) [✗]
```

---

### `get_movie_queue() -> str`

Check current Radarr download queue.

**Parameters:** None

**API Called:** Radarr v3 API - `GET /api/v3/queue`

**Example:**
```bash
get_movie_queue()
```

**Returns:** Queue items with status, e.g.:
```
1 item(s) in queue:
  • Dune (2021) — downloading
```

---

### `get_movie_history() -> str`

Show recent Radarr activity.

**Parameters:** None

**API Called:** Radarr v3 API - `GET /api/v3/history?pageSize=15`

**Example:**
```bash
get_movie_history()
```

**Returns:** Recent activity log, e.g.:
```
Recent activity (15 events):
  • [downloadImported] The Matrix
  • [grabbed] Dune
```

---

### `search_missing_movies() -> str`

Trigger a search for missing/wanted movies.

**Parameters:** None

**API Called:** Radarr v3 API - `POST /api/v3/command` with name "MissingMoviesSearch"

**Example:**
```bash
search_missing_movies()
```

**Returns:** Confirmation, e.g.:
```
✅ Missing movies search triggered.
```

---

### `get_movie_health() -> str`

Check Radarr health status.

**Parameters:** None

**API Called:** Radarr v3 API - `GET /api/v3/health`

**Example:**
```bash
get_movie_health()
```

**Returns:** Health check results, e.g.:
```
✅ Radarr health: all checks passing.
```

---

## Emby Library

### `emby_search(query: str) -> str`

Search across all Emby libraries.

**Parameters:**
- `query` (str): Search term

**API Called:** Emby API - `GET /emby/Items?SearchTerm=...&Recursive=true`

**Example:**
```bash
emby_search(query="breaking bad")
```

**Returns:** Search results from all libraries, e.g.:
```
Found 3 result(s):
  • Breaking Bad (2008) [Series]
  • Breaking Bad - S01E01 [Episode]
  • Better Call Saul (2015) [Series]
```

---

### `emby_recent(limit: int = 20) -> str`

Show recently added items in Emby.

**Parameters:**
- `limit` (int, optional): Maximum items to return (default: 20)

**API Called:** Emby API - `GET /emby/Items/Latest?Limit=...`

**Example:**
```bash
emby_recent(limit=10)
```

**Returns:** Recently added items, e.g.:
```
Recently added (10):
  • Dune (2021) [Movie]
  • Breaking Bad S01 [Season]
  • Pink Floyd - The Wall [MusicAlbum]
```

---

### `emby_libraries() -> str`

List all Emby libraries.

**Parameters:** None

**API Called:** Emby API - `GET /emby/Library/VirtualFolders`

**Example:**
```bash
emby_libraries()
```

**Returns:** List of configured libraries, e.g.:
```
Emby libraries (5):
  • Movies [movies]
  • TV Shows [tvshows]
  • Music [music]
  • Audiobooks [books]
```

---

### `emby_scan() -> str`

Trigger an Emby library scan/refresh.

**Parameters:** None

**API Called:** Emby API - `POST /emby/Library/Refresh`

**Example:**
```bash
emby_scan()
```

**Returns:** Confirmation, e.g.:
```
✅ Library scan triggered.
```

---

### `emby_get_item(item_id: str) -> str`

Get details of a specific Emby media item by ID.

**Parameters:**
- `item_id` (str): Emby item ID (GUID)

**API Called:** Emby API - `GET /emby/Items/{item_id}`

**Example:**
```bash
emby_get_item(item_id="12345678-1234-1234-1234-123456789012")
```

**Returns:** Item details with metadata, e.g.:
```
Name: The Matrix
Type: Movie
Year: 1999
Runtime: 136 min

Overview:
A computer hacker learns from mysterious rebels...
```

---

## Health

### `check_all_health() -> str`

Check health across all media services (Sonarr, Radarr, Emby).

**Parameters:** None

**API Called:**
- Sonarr: `GET /api/v3/health`
- Radarr: `GET /api/v3/health`
- Emby: `GET /emby/System/Info`

**Example:**
```bash
check_all_health()
```

**Returns:** Health status for all services, e.g.:
```
Sonarr: ✅ healthy
Radarr: ✅ healthy
Emby: ✅ healthy
```

---

### `check_disk_space() -> str`

Check disk space on the media server.

**Parameters:** None

**API Called:** Sonarr v3 API - `GET /api/v3/diskspace`

**Example:**
```bash
check_disk_space()
```

**Returns:** Disk usage information, e.g.:
```
Disk space (via Sonarr):
  • /tv/: 500.2 GB free / 2000.0 GB (75% used)
  • /movies/: 1.2 TB free / 4.0 TB (70% used)
```

---

### `check_queue_status() -> str`

Check download queues across all services.

**Parameters:** None

**API Called:**
- Sonarr: `GET /api/v3/queue`
- Radarr: `GET /api/v3/queue`

**Example:**
```bash
check_queue_status()
```

**Returns:** Queue item counts, e.g.:
```
Sonarr queue: 2 item(s)
Radarr queue: 1 item(s)
```

---

## Downloads

## SABnzbd (Usenet)

### `sabnzbd_queue() -> str`

Get the current SABnzbd download queue — active, paused, and queued items.

**Parameters:** None

**API Called:** SABnzbd API - `GET /api?mode=queue&output=json`

**Example:**
```bash
sabnzbd_queue()
```

**Returns:** Detailed queue information, e.g.:
```
SABnzbd Queue — Status: Downloading
  Speed: 5.2 MB/s  |  Paused: False
  Total: 15340 MB  |  Left: 3200 MB
  Items in queue: 3

  1. Breaking.Bad.S01.COMPLETE
     Size: 8.5 GB  |  Left: 0 MB  |  Status: Completed
```

---

### `sabnzbd_history(limit: int = 20) -> str`

Show recent completed and failed SABnzbd downloads.

**Parameters:**
- `limit` (int, optional): Maximum history entries (default: 20)

**API Called:** SABnzbd API - `GET /api?mode=history&limit=...`

**Example:**
```bash
sabnzbd_history(limit=10)
```

**Returns:** Download history with status, e.g.:
```
SABnzbd History (10 entries)
  Total downloaded: 450 GB  |  This month: 120 GB

  ✅ Breaking.Bad.S01.COMPLETE
     Status: Completed  |  Size: 8.5 GB  |  Completed: 2025-01-10
     Category: tv

  ❌ Some.Release.Bad.Parity
     Status: Failed  |  Size: 2.1 GB
     Fail: CRC error in .r01
```

---

### `sabnzbd_status() -> str`

Get SABnzbd server health, disk space, and download speed.

**Parameters:** None

**API Called:**
- SABnzbd: `GET /api?mode=queue`
- SABnzbd: `GET /api?mode=server_stats`

**Example:**
```bash
sabnzbd_status()
```

**Returns:** Server status summary, e.g.:
```
SABnzbd Status
────────────────────────────────────────
  Status:            Downloading
  Paused:            False
  Current Speed:     5.2 MB/s
  Speed Limit:       100%
  Free Disk:         1.2 TB

Servers:
  ✅ NewsHost —  Connections: 20

  Total Downloaded:  15340 MB
  Remaining:         3200 MB
```

---

### `sabnzbd_pause() -> str`

Pause all SABnzbd downloads.

**Parameters:** None

**API Called:** SABnzbd API - `GET /api?mode=pause`

**Example:**
```bash
sabnzbd_pause()
```

**Returns:** Confirmation, e.g.:
```
⏸️  SABnzbd downloads paused.
```

---

### `sabnzbd_resume() -> str`

Resume all paused SABnzbd downloads.

**Parameters:** None

**API Called:** SABnzbd API - `GET /api?mode=resume`

**Example:**
```bash
sabnzbd_resume()
```

**Returns:** Confirmation, e.g.:
```
▶️  SABnzbd downloads resumed.
```

---

### `sabnzbd_add_nzb(nzb_url: str, category: str = "") -> str`

Add an NZB to SABnzbd for download.

**Parameters:**
- `nzb_url` (str): URL to the .nzb file or magnet link
- `category` (str, optional): Category (e.g., 'tv', 'movies', 'music')

**API Called:** SABnzbd API - `GET /api?mode=addurl&name=...`

**Example:**
```bash
sabnzbd_add_nzb(nzb_url="https://example.com/file.nzb", category="tv")
```

**Returns:** Confirmation with queue ID, e.g.:
```
✅ Added NZB to SABnzbd. ID: SABnzbd_nzo_xxxxx
```

---

## Synology Download Station

### `download_station_list() -> str`

List all active torrent and download tasks in Download Station.

**Parameters:** None

**API Called:** Synology DSM API - `SYNO.DownloadStation.Task.list`

**Example:**
```bash
download_station_list()
```

**Returns:** List of tasks with status, e.g.:
```
Download Station — 2 active, 5 complete

── Active (2) ──
  • Ubuntu 24.04 LTS ISO
    Status: downloading  |  45%  |  2147483648 bytes downloaded

── Completed (5) ──
  • Some.Torrent.Release [finished]
  • Another.Release [seeding]
  ... and 3 more completed tasks
```

---

### `download_station_add(url: str) -> str`

Add a torrent/magnet/NZB URL to Download Station for download.

**Parameters:**
- `url` (str): Torrent file URL, magnet link, or NZB URL

**API Called:** Synology DSM API - `SYNO.DownloadStation.Task.create`

**Example:**
```bash
download_station_add(url="magnet:?xt=urn:btih:...")
```

**Returns:** Confirmation, e.g.:
```
✅ Added download to Download Station: magnet:?xt=urn:btih:...
```

---

### `download_station_pause(task_id: str) -> str`

Pause a specific Download Station task by its ID.

**Parameters:**
- `task_id` (str): The task ID from download_station_list()

**API Called:** Synology DSM API - `SYNO.DownloadStation.Task.pause`

**Example:**
```bash
download_station_pause(task_id="dbid_1234")
```

**Returns:** Confirmation, e.g.:
```
⏸️  Paused task dbid_1234.
```

---

### `download_station_resume(task_id: str) -> str`

Resume a paused Download Station task by its ID.

**Parameters:**
- `task_id` (str): The task ID from download_station_list()

**API Called:** Synology DSM API - `SYNO.DownloadStation.Task.resume`

**Example:**
```bash
download_station_resume(task_id="dbid_1234")
```

**Returns:** Confirmation, e.g.:
```
▶️  Resumed task dbid_1234.
```

---

### `download_station_info() -> str`

Get Download Station version and capability info.

**Parameters:** None

**API Called:** Synology DSM API - `SYNO.DownloadStation.Info.getinfo`

**Example:**
```bash
download_station_info()
```

**Returns:** Service information, e.g.:
```
Synology Download Station Info
  Version:      2.5-3201
  Is Manager:   True
  Services:
    ✅ BT
    ✅ NZB
    ✅ HTTP
    ✅ FTP
    ✅ eMule
```

---

### `download_station_stats() -> str`

Get Download Station task statistics summary.

**Parameters:** None

**API Called:** Synology DSM API - `SYNO.DownloadStation.Task.list`

**Example:**
```bash
download_station_stats()
```

**Returns:** Statistics summary, e.g.:
```
Download Station — Task Statistics
  Total tasks:       12
  Downloading:       2
  Seeding:           5
  Paused:            1
  Waiting:           0
  Finished:          4
  Error:             0
  Total size:        150.5 GB
  Total downloaded:  85.2 GB
```

---

## Unified Search

### `search_media(query: str, source_type: str | None = None) -> str`

Search across all media sources (Sonarr, Radarr, Download Station).

Returns a unified ranked list of matching TV shows, movies, and torrents.
The user should NOT specify 'torrent' vs 'usenet' — all sources are searched by default.

**Parameters:**
- `query` (str): The search term (title, name, or keyword)
- `source_type` (str | None, optional): Optional filter — 'tv', 'movie', 'torrent', or None for all

**API Called:**
- Sonarr: `GET /api/v3/series/lookup`
- Radarr: `GET /api/v3/movie/lookup`
- Download Station: `GET /webapi/DownloadStation/task.cgi?method=list`

**Example:**
```bash
search_media(query="matrix")
```
```bash
search_media(query="breaking bad", source_type="tv")
```

**Returns:** Unified, ranked search results, e.g.:
```
Found 3 result(s) for 'matrix':

  1. The Matrix (1999) ← Movies (Radarr)
     A computer hacker learns from mysterious rebels...
     [id: 603]

  2. The Matrix Reloaded (2003) ← Movies (Radarr)
     Neo and the rebels fight back...
     [id: 604]

  3. The Matrix (torrent) ← Torrents (DS)
     Status: finished, Size: 2147483648 bytes
     [id: dbid_5678]

To download a result, use: download_media(result_id)
where result_id is the number from the list above.
```

---

### `download_media(result_id: int) -> str`

Download a media result by its position number from search_media().

This tool triggers the appropriate download action based on the result's source.
For deep integration, re-run search_media and call the specific tool.

**Parameters:**
- `result_id` (int): The 1-based index from the search_media results list

**API Called:** Dispatches to source-specific tools (add_tv_show, add_movie, etc.)

**Example:**
```bash
download_media(result_id=1)
```

**Returns:** Action guidance, e.g.:
```
🔄 Download triggered for result #1.

To complete the action, use the appropriate source-specific tool:
  • TV show:   add_tv_show(tvdb_id=..., title=...)     [sonarr.py]
  • Movie:     add_movie(tmdb_id=..., title=...)       [radarr.py]
  • Torrent:   Run the search again and provide the ID

⚠️  For deep integration, re-run search_media(query) and then
call the specific tool for the result you want.
```

---

## YouTube

### `youtube_download(url: str, content_type: str = "video") -> str`

Download a YouTube video/audio using yt-dlp.

Downloads the best available quality format. For music/concerts, downloads
audio-only (best audio). For 'video', downloads best video+audio.

**Parameters:**
- `url` (str): YouTube video URL to download
- `content_type` (str, optional): Type of content — 'video' (default), 'concert', 'music', 'podcast', or 'clip'

**Tool Called:** yt-dlp (subprocess)

**Example:**
```bash
youtube_download(url="https://youtube.com/watch?v=dQw4w9WgXcQ", content_type="music")
```

**Returns:** Download confirmation with file path, e.g.:
```
✅ Downloaded: /home/user/media/youtube/Rick Astley - Never Gonna Give You Up.mp3
```

---

### `youtube_add_subscription(url: str, content_type: str = "concert") -> str`

Subscribe to a YouTube channel for monitoring new uploads.

Stores the channel URL and content type in a local subscriptions file
for periodic checking via youtube_check_subscriptions().

**Parameters:**
- `url` (str): YouTube channel URL (e.g., https://youtube.com/@channel)
- `content_type` (str, optional): Type of content — 'concert', 'music', 'video', 'podcast', 'vlog' (default: 'concert')

**Tool Called:** yt-dlp (subprocess) for channel resolution

**Example:**
```bash
youtube_add_subscription(url="https://youtube.com/@PinkFloyd", content_type="concert")
```

**Returns:** Subscription confirmation, e.g.:
```
✅ Subscribed to 'Pink Floyd' (concert). Total subscriptions: 5
```

---

### `youtube_check_subscriptions() -> str`

Check all subscribed YouTube channels for new uploads.

Uses yt-dlp to fetch the latest upload for each channel and compares
against the last known upload. Updates the subscriptions file with
the latest results.

**Parameters:** None

**Tool Called:** yt-dlp (subprocess) per channel

**Example:**
```bash
youtube_check_subscriptions()
```

**Returns:** Subscription status with new uploads, e.g.:
```
Checking 5 subscription(s) for new uploads...

  🆕 Pink Floyd: "Another Brick in the Wall (Live 1977)" (2024-12-15)
     https://youtube.com/watch?v=xxxxx
  ✓ Led Zeppelin: no new uploads (last: Stairway to Heaven)

Found 1 new upload(s)!
```

---

### `youtube_list_subscriptions() -> str`

List all active YouTube channel subscriptions with their details.

**Parameters:** None

**Tool Called:** None (reads local subscriptions file)

**Example:**
```bash
youtube_list_subscriptions()
```

**Returns:** List of subscriptions, e.g.:
```
YouTube Subscriptions (5):

  1. Pink Floyd
     Type: concert  |  Added: 2024-01-01
     Last checked: 2025-01-15
     Last upload: video_id_xxxxx

  2. Led Zeppelin
     Type: concert  |  Added: 2024-01-02
     Last checked: 2025-01-15
     Last upload: video_id_yyyyy
```

---

### `youtube_remove_subscription(name_or_url: str) -> str`

Remove a YouTube channel subscription by name or URL.

**Parameters:**
- `name_or_url` (str): The channel name or URL to remove

**Tool Called:** None (writes to local subscriptions file)

**Example:**
```bash
youtube_remove_subscription(name_or_url="Pink Floyd")
```

**Returns:** Confirmation, e.g.:
```
✅ Removed subscription 'Pink Floyd'. 4 remaining.
```

---

### `youtube_get_info(url: str) -> str`

Get metadata and format info about a YouTube video without downloading.

**Parameters:**
- `url` (str): YouTube video URL to inspect

**Tool Called:** yt-dlp (subprocess)

**Example:**
```bash
youtube_get_info(url="https://youtube.com/watch?v=dQw4w9WgXcQ")
```

**Returns:** Video metadata, e.g.:
```
Title:       Rick Astley - Never Gonna Give You Up
Channel:     Rick Astley
Uploaded:    2009-10-25
Duration:    3m 32s
Views:       1400000000
Likes:       15000000

Description:
Rick Astley's official music video for "Never Gonna Give You Up"...
```

---

## Bandcamp

### `bandcamp_download(url: str) -> str`

Download a Bandcamp album/track with full metadata and artwork.
Pass the Bandcamp album or track URL. Returns the download path.

**Parameters:**
- `url` (str): Bandcamp album or track URL

**Tool Called:** bandcamp-dl (subprocess)

**Example:**
```bash
bandcamp_download(url="https://artist.bandcamp.com/album/album-name")
```

**Returns:** Download confirmation with file count, e.g.:
```
✅ Downloaded 12 track(s) to /tmp/bandcamp/album-name
Artist: Artist Name
Album: Album Name

Run `library_sort_dir` to organize into the media library.
```

---

### `bandcamp_download_collection() -> str`

Download all purchased Bandcamp albums from your collection.
Requires bandcamp-dl to be configured with your account credentials.

**Parameters:** None

**Tool Called:** bandcamp-dl (subprocess)

**Example:**
```bash
bandcamp_download_collection()
```

**Returns:** Bulk download confirmation, e.g.:
```
✅ Collection download complete.
Downloaded 45 albums from your Bandcamp collection.
```

---

## Audible

### `audible_list_library() -> str`

List all audiobooks in your Audible library.

**Parameters:** None

**Tool Called:** audible-cli (subprocess) - `audible library list`

**Example:**
```bash
audible_list_library()
```

**Returns:** Library listing, e.g.:
```
Audible library (12 books):
  • Dune by Frank Herbert (21h 3m)
  • The Hobbit by J.R.R. Tolkien (11h 6m)
  • 1984 by George Orwell (8h 23m)
```

---

### `audible_download(asin: str) -> str`

Download an audiobook by ASIN (Amazon Standard Identification Number).
Downloads as AAXC, then decrypts to M4B with embedded metadata.

**Parameters:**
- `asin` (str): Audible ASIN of the book

**Tool Called:** audible-cli (subprocess) - `audible download` + `audible decrypt`

**Example:**
```bash
audible_download(asin="B00X4WHP5E")
```

**Returns:** Download confirmation with file info, e.g.:
```
✅ Downloaded and decrypted: Dune.m4b
   Size: 450.2 MB
   Path: /tmp/audible_downloads/Dune.m4b
   Run `library_sort_dir` to organize into the audiobooks library.
```

---

### `audible_download_new() -> str`

Download audiobooks added to your library since the last sync.

**Parameters:** None

**Tool Called:** audible-cli (subprocess) - `audible library list` + `audible download`

**Example:**
```bash
audible_download_new()
```

**Returns:** Batch download results, e.g.:
```
✅ Downloaded 3 new audiobook(s):
Downloading: The Martian (B00X4WHP5E)
Downloading: Ready Player One (B00X4WHP5F)
Downloading: Neuromancer (B00X4WHP5G)
```

---

### `audible_setup_auth() -> str`

Set up Audible authentication. Run this first to configure audible-cli.
Requires a browser login flow — you'll be prompted for a verification code.

**Parameters:** None

**Tool Called:** None (instructions for manual setup)

**Example:**
```bash
audible_setup_auth()
```

**Returns:** Setup instructions, e.g.:
```
⚠️ Audible authentication setup requires user interaction.

To set up:
1. Run: `audible quickstart --auth-file /config/audible/auth.json`
2. You'll be prompted to open a URL in a browser
3. Log in to Amazon and paste the redirect URL back
4. Once complete, run `audible_check_auth` to verify

The auth file will persist in /config/audible/ and survive container restarts.
Auth tokens expire ~30 days — the agent will prompt you to re-authenticate.
```

---

### `audible_check_auth() -> str`

Check if Audible authentication is still valid.

**Parameters:** None

**Tool Called:** None (checks auth file)

**Example:**
```bash
audible_check_auth()
```

**Returns:** Auth status, e.g.:
```
✅ Auth file found (25 KB). Run `audible_list_library` to verify it works.
```
or
```
❌ Not authenticated. Run `audible_setup_auth` to configure.
```

---

## ROMs

### `rom_search_archive(query: str, platform: str = "") -> str`

Search Internet Archive for No-Intro/Redump ROM sets.
Optionally filter by platform (nes, snes, genesis, n64, gba, psx, etc.).

**Parameters:**
- `query` (str): Search term for ROM set
- `platform` (str, optional): Platform filter

**Tool Called:** internetarchive Python library

**Example:**
```bash
rom_search_archive(query="super mario", platform="snes")
```

**Returns:** Search results, e.g.:
```
Found 10 result(s) on Internet Archive:
  • Super Mario World (USA) [no-intro-snes-super-mario-world] (2.1 MB)
  • Super Mario World 2 - Yoshi's Island (USA) [no-intro-snes-smw2] (4.5 MB)
  • Super Mario All-Stars (USA) [no-intro-snes-allstars] (6.8 MB)

Use `rom_download` with the identifier to download.
```

---

### `rom_download(identifier: str, platform: str = "") -> str`

Download a ROM set from Internet Archive by identifier.
Optionally specify platform to organize the download.

**Parameters:**
- `identifier` (str): Internet Archive item identifier
- `platform` (str, optional): Platform for organization

**Tool Called:** internetarchive Python library

**Example:**
```bash
rom_download(identifier="no-intro-snes-super-mario-world", platform="snes")
```

**Returns:** Download progress and results, e.g.:
```
Downloading 20 file(s) from 'no-intro-snes-super-mario-world'...
  ✓ Super Mario World (USA).sfc
  ✓ Super Mario World (USA).xml
  ...

✅ Downloaded 20 files to /tmp/rom_downloads/snes

Run `rom_verify_dat` to verify checksums against No-Intro DATs.
```

---

### `rom_verify_dat(platform: str) -> str`

Verify ROM collection checksums against No-Intro DAT files.
Platform: nes, snes, genesis, n64, gba, etc.

**Parameters:**
- `platform` (str): Platform to verify

**Tool Called:** hashlib + xml.etree.ElementTree (local DAT file parsing)

**Example:**
```bash
rom_verify_dat(platform="snes")
```

**Returns:** Verification report, e.g.:
```
✅ ROM verification for snes: 145 verified, 5 unknown

Verified: 145/150 files match No-Intro DAT
Unknown: 5 files not in DAT (may be hacks, translations, or bad dumps)

First unknown files:
  • Super Mario World - Hard Hack.sfc
  • Chrono Trigger - French Translation.sfc
```

---

### `rom_get_collection() -> str`

List current ROM collection by platform.

**Parameters:** None

**Tool Called:** None (scans local filesystem)

**Example:**
```bash
rom_get_collection()
```

**Returns:** Collection summary, e.g.:
```
ROM collection by platform:
  • nes: 850 games
  • snes: 1450 games
  • genesis: 920 games
  • n64: 320 games
  • gba: 1100 games
```

---

## Tool Configuration

All tools read configuration from `config/settings.yaml` using the `get_settings()` singleton.

**Required environment variables:**
- `SONARR_API_KEY` - Sonarr API key
- `RADARR_API_KEY` - Radarr API key
- `EMBY_API_KEY` - Emby API key

**Optional environment variables:**
- `DS_USER` - Download Station username
- `DS_PASS` - Download Station password

**Service URLs configured in settings.yaml:**
```yaml
services:
  sonarr:
    url: "http://192.168.0.133:8989"
    api_key: "${SONARR_API_KEY}"
  radarr:
    url: "http://192.168.0.133:7878"
    api_key: "${RADARR_API_KEY}"
  emby:
    url: "http://192.168.0.133:8096"
    api_key: "${EMBY_API_KEY}"
  sabnzbd:
    url: "http://192.168.0.133:8080"
    api_key: "${SABNZBD_API_KEY}"
  download_station:
    url: "http://192.168.0.133:5000"
    username: "${DS_USER}"
    password: "${DS_PASS}"
```

---

## Tool Conventions

1. **All tools are async functions** decorated with `@tool` from `langchain_core.tools`
2. **All tools return `str`** — never dict, never list, never raise exceptions
3. **All tools have try/except** — return `"❌ Error: ..."` on failure
4. **All network calls use `httpx.AsyncClient`** — never the synchronous `requests` library
5. **Emoji conventions:** ✅ success, ❌ error, ⚠️ warning, ⏸️ paused, ▶️ resumed
6. **No secrets in code** — all API keys from `get_settings()` which reads from environment variables

---

## API Endpoints Summary

| Service | Base URL | API Version |
|---------|----------|-------------|
| Sonarr | `/api/v3` | v3 |
| Radarr | `/api/v3` | v3 |
| Emby | `/emby` | Latest |
| SABnzbd | `/api` | Latest |
| Download Station | `/webapi` | DSM V6 |

---

## Unregistered Source Functions (Not in Registry)

The following functions exist in the source code but are **not imported** in `src/tools/registry.py`. They are available to register when needed:

| Function | Source File | Purpose |
|---|---|---|
| `download_station_info` | `src/tools/download_station.py` | Get Download Station task details |
| `download_station_stats` | `src/tools/download_station.py` | Get Download Station global statistics |
| `sabnzbd_add_nzb` | `src/tools/sabnzbd.py` | Add an NZB URL to SABnzbd queue |
| `youtube_get_info` | `src/providers/youtube.py` | Get video metadata without downloading |
| `youtube_remove_subscription` | `src/providers/youtube.py` | Remove a channel subscription |

To activate any of these, add the import to `src/tools/registry.py` and include in `all_tools`.

---

*Generated from media-agent source files. Last updated: 2026-07-05*
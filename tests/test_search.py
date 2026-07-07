"""Tests for unified search scoring and download dispatch."""
import asyncio

import src.tools.search as search_module
from src.tools.search import _score_relevance, download_media


def test_relevance_ordering():
    q = "the wire"
    exact = _score_relevance("The Wire", q)
    prefix = _score_relevance("The Wire Documentary", q)
    substring = _score_relevance("Behind the wire", q)
    word_overlap = _score_relevance("Wire in the Blood", q)
    unrelated = _score_relevance("Breaking Bad", q)
    assert exact > prefix > substring
    assert substring > word_overlap or word_overlap > unrelated
    assert unrelated == 10


def test_download_media_without_search():
    search_module._last_results = []
    result = asyncio.run(download_media.ainvoke({"result_id": 1}))
    assert "No cached search results" in result


def test_download_media_out_of_range():
    search_module._last_results = [
        {"title": "X", "source_type": "tv", "id": 1, "source": "sonarr"},
    ]
    result = asyncio.run(download_media.ainvoke({"result_id": 5}))
    assert "out of range" in result


def test_download_media_torrent_is_informational():
    search_module._last_results = [
        {"title": "Some.Torrent", "source_type": "torrent", "id": "dbid_1",
         "source": "download_station"},
    ]
    result = asyncio.run(download_media.ainvoke({"result_id": 1}))
    assert "already a Download Station task" in result

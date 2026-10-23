#!/usr/bin/env python3
"""yt-dlp, with single-piece files downloaded as byte ranges in parallel.

Used exactly like yt-dlp (same options). The only difference: a file served
over http(s) in a single piece is split into byte ranges, downloaded several
at a time (-N option) by yt-dlp's fragment engine. Progress, resuming and
post-processing remain yt-dlp's own.
"""
import json
import math
import os
import re
import sys

# The yt-dlp archive: passed on by the bridge, otherwise its usual location on this system.
if os.environ.get("YDM_YTDLP"):
    sys.path.insert(0, os.environ["YDM_YTDLP"])
else:
    sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
    from ydm_paths import YTDLP

    sys.path[0] = YTDLP

import yt_dlp
from yt_dlp.downloader import PROTOCOL_MAP
from yt_dlp.downloader.fragment import FragmentFD
from yt_dlp.downloader.http import HttpFD
from yt_dlp.networking import Request
from yt_dlp.networking.exceptions import RequestError

# Size of one range. It sets how the file is split: resuming a partial file
# is only correct if it doesn't change (see _resumable).
CHUNK = 2 * 1024 * 1024


class RangeFD(FragmentFD):
    FD_NAME = "ranges"

    def real_download(self, filename, info_dict):
        size = self._ranged_size(filename, info_dict)
        count = math.ceil(size / CHUNK) if size else 0
        if count < 2 or not self._resumable(filename, count):
            return self._sequential(filename, info_dict)

        # fragment_count is written to the state file: _resumable uses it to recognize its own split.
        ctx = {"filename": filename, "total_frags": count, "fragment_count": count}
        self._prepare_and_start_frag_download(ctx, info_dict)
        # One range = one request. If split again, it overflows its range ("Conflicting range").
        ctx["dl"].params["http_chunk_size"] = None
        fragments = [
            {
                "frag_index": i + 1,
                "fragment_count": count,
                "url": info_dict["url"],
                "byte_range": {"start": i * CHUNK, "end": min((i + 1) * CHUNK, size)},
            }
            for i in range(ctx["fragment_index"], count)
        ]
        # A missing range would corrupt the file: none of them is optional.
        return self.download_and_append_fragments(ctx, fragments, info_dict, is_fatal=lambda idx: True)

    def _ranged_size(self, filename, info_dict):
        """File size if the server accepts range requests, otherwise None."""
        if filename == "-":
            return None
        # The extractor already sets its own chunk size (YouTube): it knows the site's limits.
        if (info_dict.get("downloader_options") or {}).get("http_chunk_size"):
            return None
        headers = {**(info_dict.get("http_headers") or {}), "Range": "bytes=0-0"}
        try:
            response = self.ydl.urlopen(Request(info_dict["url"], headers=headers))
        except RequestError:
            return None
        try:
            match = re.fullmatch(r"bytes 0-0/(\d+)", response.headers.get("Content-Range") or "")
            return int(match[1]) if response.status == 206 and match else None
        finally:
            response.close()

    def _resumable(self, filename, count):
        """A partial file is only resumed in ranges if it was started with this same split."""
        part, state = self.temp_name(filename), self.ytdl_filename(filename)
        if not os.path.isfile(state):
            return not os.path.isfile(part)
        try:
            with open(state, encoding="utf-8") as f:
                return json.load(f)["downloader"].get("fragment_count") == count
        except (OSError, ValueError, KeyError):
            return False

    def _sequential(self, filename, info_dict):
        # A partial file is always a valid start of the file: the plain downloader can continue it.
        # Unless the extractor says otherwise, request the file in chunks: each request starts
        # fast before the site throttles it (0.24 -> 9 MB/s measured on a throttled site).
        chunked = self.params.get("http_chunk_size") or (info_dict.get("downloader_options") or {}).get("http_chunk_size")
        fd = HttpFD(self.ydl, self.params if chunked else {**self.params, "http_chunk_size": CHUNK})
        for hook in self._progress_hooks:
            if hook != self.report_progress:  # its own is already in place, otherwise everything shows up twice
                fd.add_progress_hook(hook)
        return fd.real_download(filename, info_dict)


if __name__ == "__main__":
    PROTOCOL_MAP["http"] = PROTOCOL_MAP["https"] = RangeFD
    yt_dlp.main()

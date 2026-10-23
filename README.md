<p align="center"><img src="extension/icon.svg" width="96" height="96" alt=""></p>

# YDM

Download the videos you're watching, straight from Firefox.

YDM is a small Firefox front end for [yt-dlp](https://github.com/yt-dlp/yt-dlp). Click the toolbar button, pick a quality, and the file lands in your Videos folder. It works on [every site yt-dlp supports](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md), plus plain video files and HLS/DASH streams it spots while a page plays.

Linux, macOS and Windows. English and French.

## Install

Linux and macOS:

```bash
curl -fsSL https://raw.githubusercontent.com/washer696/ydm/main/install.sh | sh
```

Windows, in PowerShell:

```powershell
irm https://raw.githubusercontent.com/washer696/ydm/main/install.ps1 | iex
```

That's it. The command installs Python and FFmpeg if you don't have them, downloads yt-dlp and Deno from their official releases, sets up the small companion app that runs yt-dlp, and opens the extension in Firefox. Click "Add". On a Mac, it needs Homebrew for Python and FFmpeg.

Run it again to update the companion app. The extension updates itself.

## Using it

- The toolbar button shows how many videos YDM found on the page. Open it to pick a quality, or audio only.
- Right-click a link, a video or a page, then "Download with YDM".
- Alt+Shift+D downloads the current tab's video in the best quality.
- The Downloads page holds the history and the queue. Three downloads run at once, the others wait their turn. Settings are at the bottom: folder, language, yt-dlp version.

## Privacy

YDM has no server and no analytics. yt-dlp talks to the video's site and nothing else, and it never gets your cookies. Web pages can't control YDM. Only the extension can start the companion app, and the app accepts a short list of commands. Its log keeps no URLs or titles.

Downloads started in a private window stay out of normal windows and disappear from the history when you close the last private window. The files stay on disk.

## Credit where it's due

YDM is a thin layer. yt-dlp does the hard part, and its maintainers fix sites that break overnight, on their own time. If YDM saves you time, support them. Their sponsor links are in [yt-dlp's Maintainers.md](https://github.com/yt-dlp/yt-dlp/blob/master/Maintainers.md). Reporting broken sites to yt-dlp helps too.

YDM also relies on [FFmpeg](https://ffmpeg.org/donations.html) and [Deno](https://deno.com).

Please only download what you're allowed to.

## Development

From a clone, install with `python3 install.py`, or `py install.py` on Windows. The tests are in `tools/`, and GitHub runs the offline ones on all three systems on every push. `tools/sign.sh` gets a new version signed by Mozilla and `tools/publish.py` releases it. Issues and pull requests are welcome.

## License

GPL-3.0-or-later.

# -*- coding: utf-8 -*-
# Build customizations
# Change this file instead of sconstruct or manifest files, whenever possible.

from site_scons.site_tools.NVDATool.typings import AddonInfo, BrailleTables, SymbolDictionaries
from site_scons.site_tools.NVDATool.utils import _

# Add-on information variables
addon_info = AddonInfo(
	# add-on Name/identifier, internal for NVDA
	addon_name="freeAudio",
	
	# Add-on summary/title, usually the user visible name of the add-on
	# Translators: Summary/title for this add-on
	addon_summary=_("freeAudio: Radio and more"),
	
	# Add-on description
	# Translators: Long description to be shown for this add-on
	addon_description=_("""freeAudio is an internet radio, podcast, audio-book, and local music add-on for NVDA that provides seamless access to thousands of internet radio stations via the Radio Browser open directory, RSS/Atom podcast feeds, the libriVox + GETEM digital library for the visually impaired, and your own local audio files and folders through its built-in jukebox. It features a fully accessible station browser with search, country filter, favourites management, and per-station, per-podcast, per-audio-book, and per-jukebox-track audio profiles. Podcast episodes, audio book chapters, and jukebox tracks resume automatically from where you left off - jukebox folders even pick up on the last track you were playing - with adjustable pitch-preserving playback speed and independent pitch-shift (semitone transpose). Playback is handled by BASS, with support for volume control, audio effects, output device selection, and simultaneous audio mirroring to a second device. Additional features include instant and scheduled recording, time-shift rewind of live radio, sleep and alarm timers, automatic ICY metadata announcements, Shazam-based music recognition, and a liked-songs log with lyrics lookup. All controls and shortcuts are designed for NVDA accessibility."""),
	
	# version
	addon_version="2026.25.2",
	
	# Brief changelog for this version
	# Translators: what's new content for the add-on version
	addon_changelog=_("""
## Changelog for 2026.25.2

### New
- **Bookmarks.** You can bookmark the current position of an audio book part, podcast episode or jukebox track, and jump back to it later.
  - **Adding.** `Ctrl+Win+F12` adds a bookmark from anywhere in Windows, and `F12` does the same inside the Station Browser. A bookmark's default name is its number by position ("Bookmark 1", "Bookmark 2", and so on).
  - **Notes.** Each bookmark can carry a text note and/or a recorded voice note.
  - **Reaching a bookmark.** When playback reaches a bookmark it plays two quick beeps. If the bookmark has a note, playback pauses, NVDA speaks the text and the voice note plays, then playback resumes where it left off.
  - **Bookmark list.** A list sits next to the Podcasts episode list, the Audio Books library (all parts of the selected book) and the Jukebox tracks list. Press `.` to mark items. The context menu offers play from bookmark, rename, delete selected, add or edit text, add voice note, clear notes, repeat between marked bookmarks and stop repeat.
  - **Repeat.** "Repeat Between Marked Bookmarks" loops the section between the earliest and latest marked bookmark.
  - **Notes on play.** "Play from Bookmark" now speaks the text note and plays the voice note first, then starts playback from that position.
  - **Audio book rows.** Rows now read "bookmark name — time — part", and the book name is no longer repeated.
  - **Keys on the lists.** `←`, `→`, `Shift+←`, `Shift+→`, `Page Up` and `Page Down` work on the bookmark lists of all three tabs, as on the item lists.
  - **Clean-up.** The clean-up dialog can delete all bookmarks and their voice notes.
- **Fine seek (1 second).** `Ctrl+Win+Alt+J` and `Ctrl+Win+Alt+K` rewind or forward by 1 second, for live time-shift and for podcasts, audio books and jukebox tracks. `Alt+←` and `Alt+→` do the same in the Station Browser.
- **Record every song.** Press `Ctrl+Win+E` three times to keep recording and start a new file at every track change until you stop it.
  - **Partial songs.** The first and last songs are saved with "(partial)" in the name.
  - **Short pieces.** Pieces shorter than 15 seconds (jingles, flickering titles) are discarded.
  - **Limits.** It does not work on HLS stations or stations without in-band track titles, and stopping playback does not stop it.
  - **Double press.** A double press still records the current song, but it now starts about 350 ms after the second press so a third press can change what the sequence means.
- **Clean-up dialog.** A new **Clean up: reset settings and delete saved data...** button on the settings page lets you reset settings and delete saved data. That covers favourites, podcast subscriptions, audio book libraries, GETEM login, Jukebox list, resume positions, bookmarks, timers, recording plans and more. Nothing is selected by default, and deletion needs a second confirmation. Recordings and liked songs are never touched.

### Fixed
- **Song recordings included the start of the next track.** Recordings now end at the exact point where the station announces a new track. Stop requests take effect immediately, which also helps instant recordings. The old 5-second title polling stays as a fallback for streams without in-band metadata, such as HLS.
- **Music recognition failed on some stations.**
  - **HTTP 403 on HLS.** ffmpeg now identifies itself with a VLC User-Agent, and retries with a browser one if the server answers 401 or 403. HLS playlist URLs with query strings are detected correctly.
  - **SHOUTcast `.nsv` timeouts.** For non-HLS streams, freeAudio records a short sample itself and lets ffmpeg decode that file. It does this up front for `.nsv` URLs and as a fallback whenever the direct read fails.
  - **Errors.** If both attempts fail, the message shows the reason for each.
- **Choppy playback of ABC (Australia) HLS stations.** These stations now play through a small local compatibility server that re-wraps the audio in a layout BASS can read. The audio itself is not re-encoded. NVDA announces this once per station per session, and the announcement follows **Mute notifications**.
"""),
	
	# Author(s)
	addon_author="Çağrı Doğan <cagrid@hotmail.com>",
	
	# URL for the add-on documentation support
	addon_url="https://github.com/Surveyor123/freeAudio",
	
	# URL for the add-on repository where the source code can be found
	addon_sourceURL="https://github.com/Surveyor123/freeAudio",
	
	# Documentation file name
	addon_docFileName="readme.html",
	
	# Minimum NVDA version supported
	addon_minimumNVDAVersion="2025.1.0",
	
	# Last NVDA version supported/tested
	addon_lastTestedNVDAVersion="2026.2.0",
	
	# Add-on update channel (None denotes stable releases)
	addon_updateChannel=None,
	
	# Add-on license
	addon_license="GPL-2.0",
	addon_licenseURL=None,
)

# Define the python files that are the sources of your add-on.
# We point to the specific directory where your code lives.
pythonSources: list[str] = [
	"addon/globalPlugins/freeAudio/*.py",
	"addon/appModules/*.py",
]

# Files that contain strings for translation. Usually your python sources
i18nSources: list[str] = pythonSources + ["buildVars.py"]

# Files that will be ignored when building the nvda-addon file
excludedFiles: list[str] = []

# Base language for the NVDA add-on
# Since your code strings (e.g. _("Table")) are in English, we keep this as "en".
baseLanguage: str = "en"

# Markdown extensions for add-on documentation
markdownExtensions: list[str] = []

# Custom braille translation tables
brailleTables: BrailleTables = {}

# Custom speech symbol dictionaries
symbolDictionaries: SymbolDictionaries = {}
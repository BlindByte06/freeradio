# -*- coding: utf-8 -*-
# freeAudio - Player-side bookmark support, mixed into RadioPlayer:
#   - a watcher thread that notices when playback reaches a bookmark
#   - A-B repeat between two positions of the current item
#   - helpers to seek to / preset a resume position

import logging
import threading
import time

log = logging.getLogger(__name__)


class BookmarkPlayerMixin:

	def _init_bookmark_watcher(self):
		# Called once from RadioPlayer.__init__.
		self.on_bookmark_reached = None   # callback(station, bookmark), runs on its own thread
		self._bm_hold = False             # True while a bookmark note is being played
		self._bm_resync = False
		self._loop_range = None           # (key, start_seconds, end_seconds)
		self._loop_mismatch_since = None
		threading.Thread(
			target=self._bookmark_loop, daemon=True, name="freeAudio-bookmarks"
		).start()

	# -- public helpers ----------------------------------------------------

	def bookmark_key(self, station=None):
		"""Bookmark/resume key of *station* (default: the current one), or
		None if it isn't an audio book part, podcast episode or jukebox
		track."""
		from .radioPlayer import _is_seekable_media
		if station is None:
			station = self._current_station
		if not _is_seekable_media(station):
			return None
		return self._podcast_position_key(station)

	def set_resume_position(self, key, position):
		"""Make the item with *key* start at *position* seconds the next
		time it is played."""
		if not key:
			return
		with self._podcast_positions_lock:
			old = self._podcast_positions.get(key, {})
			self._podcast_positions[key] = {
				"position": round(float(position), 1),
				"listened": False,
				"name": old.get("name", ""),
				"updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
			}
		self._write_podcast_positions()

	def seek_to(self, seconds):
		"""Seek the currently open item to an absolute position."""
		ok, pos, _length = self.get_playback_position()
		if not ok:
			return False
		done, _new = self.seek_relative(float(seconds) - pos)
		return bool(done)

	def set_loop_range(self, key, start, end):
		self._loop_mismatch_since = None
		self._loop_range = (key, float(start), float(end))

	def clear_loop(self):
		self._loop_range = None
		self._loop_mismatch_since = None

	def get_loop_range(self):
		return self._loop_range

	def bookmark_hold_release(self):
		self._bm_resync = True
		self._bm_hold = False

	# -- watcher -------------------------------------------------------------

	def _fire_bookmark(self, station, bookmark):
		cb = self.on_bookmark_reached
		if not cb:
			return
		if bookmark.has_note():
			self._bm_hold = True

		def _run():
			try:
				cb(station, bookmark)
			except Exception:
				log.error("freeAudio: bookmark callback failed", exc_info=True)
				self.bookmark_hold_release()

		threading.Thread(target=_run, daemon=True, name="freeAudio-bookmark-cb").start()

	def _bookmark_loop(self):
		from . import bookmarks
		from .radioPlayer import _is_seekable_media
		last_pos = None
		last_key = None
		while True:
			interval = 0.2 if self._loop_range else 0.35
			if self._watchdog_stop.wait(interval):
				return
			try:
				if self._current_url is None:
					self._loop_range = None
					self._loop_mismatch_since = None
				if self._bm_resync:
					self._bm_resync = False
					last_pos = None
				if self._bm_hold or not self._is_playing:
					last_pos = None
					continue
				station = self._current_station
				if not _is_seekable_media(station):
					last_pos = None
					continue
				key = self._podcast_position_key(station)
				loop = self._loop_range
				if loop:
					if loop[0] == key:
						self._loop_mismatch_since = None
					else:
						# A repeat range for some other item: ignore it,
						# and drop it if that item stays unplayed.
						now = time.time()
						if self._loop_mismatch_since is None:
							self._loop_mismatch_since = now
						elif now - self._loop_mismatch_since > 20:
							self._loop_range = None
							self._loop_mismatch_since = None
						loop = None
				mgr = bookmarks.get_manager()
				marks = mgr.get(key) if mgr.has_bookmarks(key) else []
				if not marks and not loop:
					last_pos = None
					last_key = key
					continue
				ok, pos, _length = self.get_playback_position()
				if not ok:
					last_pos = None
					continue
				if key != last_key:
					last_key = key
					last_pos = None
				if loop and 0 <= pos - loop[2] < 5.0:
					self.seek_relative(loop[1] - pos)
					last_pos = None
					continue
				if last_pos is not None and marks:
					window = 3.0 * max(1.0, self._playback_rate) + 0.5
					if 0 <= pos - last_pos <= window:
						for bm in marks:
							if last_pos < bm.position <= pos:
								self._fire_bookmark(station, bm)
								break
				last_pos = pos
			except Exception:
				log.debug("freeAudio: bookmark watcher error", exc_info=True)

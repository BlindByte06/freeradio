# -*- coding: utf-8 -*-
# freeAudio - Bookmarks for audio books, podcast episodes and jukebox tracks
#
# Bookmarks are stored per playable item, keyed by the same key the player
# uses for resume positions (RadioPlayer._podcast_position_key()): for a
# podcast episode its URL, for an audio book part the part's stable upstream
# URL, for a jukebox track its file path.
#
# Each bookmark can carry an optional text note (spoken by NVDA
# when playback reaches it) and/or a recorded voice note (a .wav file
# stored next to the bookmarks file).

import json
import logging
import os
import threading
import time
import uuid

import addonHandler
addonHandler.initTranslation()
import globalVars

_tr = globals()["_"]
_ = _tr
del _tr
log = logging.getLogger(__name__)


class Bookmark:
	def __init__(self, bid, position, name="", text="", audio="", created=None):
		self.id = bid
		self.position = float(position)
		self.name = name or ""      # "" = default (ordinal) name
		self.text = text or ""
		self.audio = audio or ""    # absolute path of a .wav voice note, or ""
		self.created = created if created is not None else time.time()

	def has_note(self):
		return bool(self.text or self.audio)

	def to_dict(self):
		return {
			"id": self.id,
			"position": self.position,
			"name": self.name,
			"text": self.text,
			"audio": self.audio,
			"created": self.created,
		}

	@classmethod
	def from_dict(cls, data):
		return cls(
			data.get("id") or uuid.uuid4().hex[:12],
			data.get("position", 0.0),
			data.get("name", ""),
			data.get("text", ""),
			data.get("audio", ""),
			data.get("created"),
		)


class BookmarkManager:
	def __init__(self):
		self._lock = threading.RLock()
		self._data = {}   # key -> [Bookmark]
		self._load()

	def _base_dir(self):
		return globalVars.appArgs.configPath

	def _get_path(self):
		return os.path.join(self._base_dir(), "freeAudio_bookmarks.json")

	def audio_dir(self):
		path = os.path.join(self._base_dir(), "freeAudio_bookmark_audio")
		os.makedirs(path, exist_ok=True)
		return path

	def audio_path_for(self, bookmark_id):
		return os.path.join(self.audio_dir(), bookmark_id + ".wav")

	def _load(self):
		path = self._get_path()
		if not os.path.exists(path):
			return
		try:
			with open(path, "r", encoding="utf-8") as f:
				raw = json.load(f)
			items = raw.get("items", {}) if isinstance(raw, dict) else {}
			for key, lst in items.items():
				self._data[key] = [Bookmark.from_dict(d) for d in lst if isinstance(d, dict)]
		except Exception as e:
			log.warning("freeAudio Bookmarks: failed to load: %s", e)
			self._data = {}

	def _save(self):
		path = self._get_path()
		tmp_path = path + ".tmp"
		try:
			with self._lock:
				payload = {"items": {k: [b.to_dict() for b in v] for k, v in self._data.items() if v}}
			with open(tmp_path, "w", encoding="utf-8") as f:
				json.dump(payload, f, ensure_ascii=False, indent=2)
			os.replace(tmp_path, path)
		except Exception as e:
			log.warning("freeAudio Bookmarks: failed to save: %s", e)
			try:
				os.remove(tmp_path)
			except OSError:
				pass

	# -- queries ---------------------------------------------------------

	def has_bookmarks(self, key):
		return bool(key) and bool(self._data.get(key))

	def get(self, key):
		"""Bookmarks of *key*, sorted by position."""
		if not key:
			return []
		with self._lock:
			return sorted(self._data.get(key, []), key=lambda b: b.position)

	def find(self, key, bookmark_id):
		with self._lock:
			for b in self._data.get(key, []):
				if b.id == bookmark_id:
					return b
		return None

	def display_name(self, key, bookmark):
		"""Custom name, or the bookmark's ordinal position among the item's
		bookmarks (1 = earliest) as the default name."""
		if bookmark.name:
			return bookmark.name
		ordered = self.get(key)
		for i, b in enumerate(ordered):
			if b.id == bookmark.id:
				# Translators: Default name of a bookmark; %d is its ordinal among the item's bookmarks, sorted by position.
				return _("Bookmark %d") % (i + 1)
		# Translators: Fallback default bookmark name if its ordinal can't be determined.
		return _("Bookmark")

	# -- changes ---------------------------------------------------------

	def add(self, key, position):
		bm = Bookmark(uuid.uuid4().hex[:12], max(0.0, round(float(position), 1)))
		with self._lock:
			self._data.setdefault(key, []).append(bm)
		self._save()
		return bm

	def rename(self, key, bookmark_id, name):
		bm = self.find(key, bookmark_id)
		if bm is None:
			return False
		bm.name = (name or "").strip()
		self._save()
		return True

	def set_text(self, key, bookmark_id, text):
		bm = self.find(key, bookmark_id)
		if bm is None:
			return False
		bm.text = (text or "").strip()
		self._save()
		return True

	def set_audio(self, key, bookmark_id, path):
		"""Attach (or, with an empty *path*, detach and delete) the voice
		note of a bookmark."""
		bm = self.find(key, bookmark_id)
		if bm is None:
			return False
		if not path and bm.audio:
			self._delete_file(bm.audio)
		bm.audio = path or ""
		self._save()
		return True

	def remove(self, key, bookmark_ids):
		ids = set(bookmark_ids)
		removed = []
		with self._lock:
			lst = self._data.get(key, [])
			keep = []
			for b in lst:
				(removed if b.id in ids else keep).append(b)
			if keep:
				self._data[key] = keep
			else:
				self._data.pop(key, None)
		for b in removed:
			if b.audio:
				self._delete_file(b.audio)
		if removed:
			self._save()
		return len(removed)

	def clear_all(self):
		"""Forget every bookmark in memory (used by the clean-up dialog,
		which then deletes the bookmarks file and the voice-note folder)."""
		with self._lock:
			self._data = {}

	@staticmethod
	def _delete_file(path):
		try:
			if path and os.path.isfile(path):
				os.remove(path)
		except OSError:
			pass


_manager = None
_manager_lock = threading.Lock()


def get_manager():
	"""Shared BookmarkManager, used by the player, the plugin and the dialog."""
	global _manager
	with _manager_lock:
		if _manager is None:
			_manager = BookmarkManager()
		return _manager
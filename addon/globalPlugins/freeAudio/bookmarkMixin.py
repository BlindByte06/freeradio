# -*- coding: utf-8 -*-
# freeAudio - Bookmarks: global add-bookmark command and what happens when
# playback reaches a bookmark (two quick beeps, then - if the bookmark has a
# text and/or voice note - the note is spoken/played and playback resumes).
#
# Mixed into GlobalPlugin. The default gesture is listed in GlobalPlugin's
# __gestures dict in __init__.py (see the comment there).

import logging
import os
import threading
import time
import winsound

import config
import ui
import wx
from scriptHandler import script

import addonHandler
addonHandler.initTranslation()
_tr = globals()["_"]
_ = _tr
del _tr

from . import _notify, _format_duration
from . import bookmarks

log = logging.getLogger(__name__)


class BookmarkMixin:

	def _init_bookmarks(self):
		self._player.on_bookmark_reached = self._on_bookmark_reached

	@script(
		# Translators: Name of an NVDA command; adds a bookmark at the current playback position of an audio book part, podcast episode or jukebox track.
		description=_("Add a bookmark at the current position (audio books, podcasts, jukebox)"),
		category=_("freeAudio"),
		gesture="kb:control+windows+f12",
	)
	def script_addBookmark(self, gesture):
		self._add_bookmark_at_current()

	def _add_bookmark_at_current(self):
		"""Also called from the station browser dialog (F12)."""
		if not self._player.has_media():
			# Translators: Spoken when the add-bookmark command is used while nothing is playing.
			ui.message(_("No station is playing"))
			return
		key = self._player.bookmark_key()
		if not key:
			# Translators: Spoken when the add-bookmark command is used on a live radio station.
			ui.message(_("Bookmarks are available for audio books, podcasts and jukebox tracks only"))
			return
		ok, pos, _length = self._player.get_playback_position()
		if not ok:
			pos = self._player.get_podcast_position(key)
			if pos <= 0:
				# Translators: Spoken when the current playback position can't be read, so no bookmark is added.
				ui.message(_("Could not read the playback position"))
				return
		mgr = bookmarks.get_manager()
		bm = mgr.add(key, pos)
		# Translators: Spoken after adding a bookmark; %(name)s is its default name (ordinal), %(time)s the position.
		_notify(_("Bookmark added: %(name)s, %(time)s") % {
			"name": mgr.display_name(key, bm),
			"time": _format_duration(bm.position),
		})
		dialog = getattr(self, "_dialog", None)
		if dialog:
			try:
				wx.CallAfter(dialog.refresh_bookmarks)
			except Exception:
				pass

	# -- reaching a bookmark during playback -------------------------------

	@staticmethod
	def _bookmark_beeps():
		try:
			winsound.Beep(1400, 55)
			time.sleep(0.05)
			winsound.Beep(1400, 55)
		except Exception:
			pass

	def _on_bookmark_reached(self, station, bookmark):
		"""Runs on a worker thread, started by the player's bookmark watcher."""
		has_note = bookmark.has_note()
		try:
			self._bookmark_beeps()
			if not has_note:
				return
			key = self._player.bookmark_key(station)
			self._player.pause()
			self._deliver_bookmark_notes(bookmark)
			# Continue where playback was left - unless the user has
			# meanwhile stopped it or moved on to something else.
			if (
				self._player.has_media()
				and not self._player.is_playing()
				and self._player.bookmark_key() == key
			):
				self._player.resume()
		finally:
			if has_note:
				self._player.bookmark_hold_release()

	def _deliver_bookmark_notes(self, bookmark):
		"""Speak the bookmark's text note, then play its voice note; returns
		when both are finished. Must run on a worker thread (blocks)."""
		if bookmark.text:
			self._speak_blocking(bookmark.text)
		if bookmark.audio and os.path.isfile(bookmark.audio):
			try:
				winsound.PlaySound(bookmark.audio, winsound.SND_FILENAME)
			except Exception:
				log.warning("freeAudio: could not play bookmark voice note", exc_info=True)

	def play_bookmark_notes_then(self, bookmark, callback):
		"""Used by "Play from Bookmark": first let the bookmark's notes (if
		any) be spoken/played - pausing whatever is playing meanwhile - and
		then call *callback* on the main thread to start playback from the
		bookmark's position."""
		if not bookmark.has_note():
			callback()
			return

		def _run():
			try:
				if self._player.has_media() and self._player.is_playing():
					self._player.pause()
				self._deliver_bookmark_notes(bookmark)
			except Exception:
				log.warning("freeAudio: could not deliver bookmark notes", exc_info=True)
			finally:
				wx.CallAfter(callback)

		threading.Thread(target=_run, daemon=True, name="freeAudio-bookmark-notes").start()

	@staticmethod
	def _speak_blocking(text):
		"""Speak *text* with NVDA's own speech and return only when NVDA has
		finished speaking it (or after a safety timeout, e.g. if speech is
		turned off and the end-of-speech marker never arrives)."""
		done = threading.Event()

		def _speak():
			try:
				import speech
				from speech.commands import CallbackCommand
				speech.speak([text, CallbackCommand(done.set)])
			except Exception:
				log.warning("freeAudio: could not speak bookmark text", exc_info=True)
				done.set()
				return
			try:
				import braille
				braille.handler.message(text)
			except Exception:
				pass

		wx.CallAfter(_speak)
		done.wait(timeout=min(60.0, 5.0 + len(text) / 5.0))

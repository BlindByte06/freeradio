# -*- coding: utf-8 -*-
# freeAudio - Time-shift (rewind/fast-forward) controls
#
# Extracted from GlobalPlugin in __init__.py. Mixed into GlobalPlugin, so
# `self` here is a GlobalPlugin instance - self._player and self._dialog
# (defined elsewhere on GlobalPlugin) are used as normal instance
# attributes via the class's MRO, no import needed for those.
#
# NOTE: every script here with a default gesture= must also be listed in
# GlobalPlugin's __gestures dict in __init__.py (see the __gestures
# comment there for why).

import logging
import time
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
from .radioPlayer import _is_seekable_media

log = logging.getLogger(__name__)

# How big a jump each successive *distinct* tap of the seek gesture makes,
# within TAP_WINDOW of the previous one - see
# TimeshiftMixin._handle_podcast_seek()'s docstring for the full
# tap-vs-hold design. Index 0 is unused (tap counts start at 1) so
# _SEEK_TAP_AMOUNTS[count] reads naturally; counts beyond the list length
# are clamped to the last (largest) amount.
_SEEK_TAP_AMOUNTS = [None, 12, 60, 300]  # seconds: 1 tap, 2 taps, 3+ taps
# The amount used for each individual step while the key is being held down
# (auto-repeating) - unchanged from this gesture's original, tap-count-less
# behavior, since holding a key was never meant to escalate to minutes-long
# jumps.
_SEEK_HOLD_AMOUNT = 5  # seconds
# Consecutive invocations less than this many seconds apart are treated as
# the *same* physical key-press auto-repeating (held down), not a fresh,
# deliberate tap - see the docstring below for why this particular value.
_SEEK_HOLD_GAP = 0.15  # seconds
# How long to wait after a deliberate tap before committing to whatever tap
# count was reached, in case one more tap is still coming. Also doubles as
# the cutoff for two deliberate taps still counting as the same sequence
# (must be larger than _SEEK_HOLD_GAP above, or a slow key-repeat rate could
# be mistaken for two separate taps).
_SEEK_TAP_WINDOW_S  = 0.35
_SEEK_TAP_WINDOW_MS = int(_SEEK_TAP_WINDOW_S * 1000)

# When a rewind would run past the start of an audio-book part or
# jukebox-folder track (see _handle_track_boundary()), the *first* such
# rewind just clamps to 0:00 of the current part/track instead of
# jumping straight to the previous one. If another rewind that would
# again run past the start arrives within this many seconds, *that*
# press jumps to the previous part/track. (Forward/end-of-track always
# jumps to the next part/track immediately - this window only applies
# to rewind, see _handle_track_boundary()'s docstring for why.) This
# mirrors _SEEK_TAP_WINDOW_S above in spirit (a short window to catch a
# deliberate follow-up press) but is deliberately its own, much longer
# constant - a boundary is something the user reaches once and then may
# pause on for a while before deciding whether to actually back out of
# the current part/track, unlike the sub-second taps _SEEK_TAP_WINDOW_S
# is tuned for.
_BOUNDARY_JUMP_WINDOW_S = 10.0  # seconds

# Step of the fine seek commands (Ctrl+Win+Alt+J/K, Alt+Left/Right in the dialog).
_FINE_SEEK_AMOUNT = 1  # seconds


class TimeshiftMixin:
	"""Rewind/fast-forward the time-shift buffer (or seek within a podcast
	file), and toggle the time-shift buffer on/off."""

	def _announce_seek_position(self):
		"""Elapsed/remaining position after a podcast or audiobook seek, or
		None if the current position isn't available for some reason
		(caller should fall back to a generic message in that case).

		Used instead of a fixed "5 seconds forward/back" message: the
		listener already knows how big a seek they just did (it's always
		the same 5 seconds), what they actually want to know is *where
		that landed them* in the episode/chapter. Reuses the exact same
		"%(elapsed)s elapsed, %(remaining)s remaining" string
		TrackInfoMixin.script_whatsPlaying() (Ctrl+Win+I) already uses
		for this identical piece of information, so no new translatable
		string is introduced for it."""
		ok, pos, length = self._player.get_playback_position()
		if not ok:
			return None
		if length > 0:
			# Translators: Spoken after a podcast/audiobook seek to report the resulting position; see this method's docstring above for why the wording is shared with TrackInfoMixin.script_whatsPlaying().
			return _("%(elapsed)s elapsed, %(remaining)s remaining") % {
				"elapsed": _format_duration(pos),
				"remaining": _format_duration(max(0.0, length - pos)),
			}
		# Translators: Same position announcement as above, used when the total length isn't known so only elapsed time can be reported.
		return _("%(elapsed)s elapsed") % {"elapsed": _format_duration(pos)}

	def _handle_track_boundary(self, seconds):
		"""If seeking by *seconds* would run past the start or end of the
		current audio-book part or jukebox-folder track - i.e. less time
		remains in that direction than the seek itself - handle it here
		instead of letting the caller do a plain in-file seek that would
		just clamp at 0:00 or the very end.

		Rewind (*seconds* < 0) and forward (*seconds* > 0) are handled
		differently:

		  - Forward: jumps to the next part/track immediately, same as
		    this always worked. If you've fast-forwarded past the end,
		    you want the next part/track, no second press needed.
		  - Rewind: two-stage, mirroring how many media players treat
		    "rewind near the very start" - reaching the edge once just
		    parks you at 0:00, and only a *second* rewind that again
		    runs past the start within _BOUNDARY_JUMP_WINDOW_S actually
		    jumps to the previous part/track:
		      - 1st press to hit the start: seeks straight to 0:00 and
		        announces the resulting position, same as any other seek.
		      - 2nd press to hit the start again within
		        _BOUNDARY_JUMP_WINDOW_S: jumps to the previous part/
		        track instead.

		Either kind of jump goes through playbackCoreMixin's
		dialog-independent _advance_getem_chapter_headless()/
		_advance_jukebox_folder_headless() - the same functions natural
		end-of-part/track auto-advance already uses, so this works
		identically whether the freeAudio window is open or not, and the
		dialog (if open) simply resyncs its own display from the player
		the next time that tab is shown, exactly as it already does
		after a natural auto-advance or an NVDA-startup resume.

		Deliberately limited to audio books and jukebox-folder tracks -
		the two media kinds that actually have a well-defined "previous/
		next" to jump to and where the user explicitly asked for this
		(podcast episodes keep their existing plain-seek/clamp behavior).

		Returns True if this call fully handled the press (seek-to-start
		or jump, plus announcement - caller should not also seek); False
		if there was nothing to do here (single/standalone track, not
		actually at the boundary, or position/length unknown) - the
		caller should then fall through to a normal in-file seek."""
		station = self._player.get_current_station()
		if not station:
			return False
		media_kind = station.get("media_kind")
		if media_kind not in ("audiobook", "jukebox"):
			return False
		ok, pos, length = self._player.get_playback_position()
		if not ok or length <= 0:
			return False
		remaining = pos if seconds < 0 else (length - pos)
		if remaining > abs(seconds):
			return False
		direction = -1 if seconds < 0 else 1

		if seconds > 0:
			# Forward: jump straight to the next part/track, as before.
			if media_kind == "audiobook":
				return self._advance_getem_chapter_headless(station, direction)
			return self._advance_jukebox_folder_headless(station, direction)

		# Rewind: two-stage - park at 0:00 first, only jump to the
		# previous part/track if the start is hit again within the window.
		boundary_attr = "_seek_rew_boundary_time"
		now = time.monotonic()
		last_boundary_time = getattr(self, boundary_attr, None)

		if last_boundary_time is not None and now - last_boundary_time < _BOUNDARY_JUMP_WINDOW_S:
			# Hit the start again within the window - actually jump.
			setattr(self, boundary_attr, None)
			if media_kind == "audiobook":
				return self._advance_getem_chapter_headless(station, direction)
			return self._advance_jukebox_folder_headless(station, direction)

		# First time hitting the start - just park at 0:00 and remember
		# when, so a follow-up rewind within the window escalates to an
		# actual jump above.
		setattr(self, boundary_attr, now)
		ok, new_pos = self._player.seek_relative(-pos)
		if not ok:
			# Translators: Spoken if seeking to the start of an audio-book part/jukebox track (the boundary clamp itself) fails.
			_notify(_("Could not seek"))
			return True
		# No dedicated "Start of track" wording here - the elapsed/
		# remaining position _announce_seek_position() reports (0:00
		# elapsed) already makes that obvious on its own. Its
		# only-if-unavailable fallback reuses the same generic wording
		# the failure case above already uses.
		# Translators: Fallback spoken if _announce_seek_position() can't report a position after seeking to the start/end of an audio-book part or jukebox track.
		_notify(self._announce_seek_position() or _("Could not seek"))
		return True

	def _seek_and_announce(self, seconds):
		"""Seek by *seconds* (negative = backward) in the current podcast/
		audio-book file and announce the resulting position - shared tail
		end of both the tap and hold paths in
		_handle_podcast_seek() below.

		For an audio book or jukebox-folder track, first checks whether
		this seek would run past the part/track's start or end - see
		_handle_track_boundary() - which either parks at that start/end
		itself or (on a 2nd press within its jump window) jumps to the
		previous/next part/track; either way it does its own seek and
		announcement (the jump case announces the new part/track's name
		via playbackCoreMixin._play_station()), so nothing further is
		done here in that case."""
		if self._handle_track_boundary(seconds):
			return
		ok, pos = self._player.seek_relative(seconds)
		if not ok:
			# Translators: Spoken if a plain (non-boundary) podcast/audiobook seek fails.
			_notify(_("Could not seek"))
			return
		fallback = (
			# Translators: Fallback spoken only if _announce_seek_position() can't report a position; %d is the number of seconds seeked.
			_("Forwarded %d seconds") % seconds if seconds > 0
			else _("Rewound %d seconds") % -seconds
		)
		_notify(self._announce_seek_position() or fallback)

	def _handle_podcast_seek(self, direction):
		"""Handle one press of the seek-forward/back gesture while a
		podcast or audio-book is playing (*direction* is +1 or -1).
		Distinguishes a key being held down (auto-repeating) from
		distinct, deliberate taps, and sizes the seek accordingly:

		  - Held down: keeps doing the small, original per-step amount
		    (_SEEK_HOLD_AMOUNT) on every repeat, immediately and with no
		    delay, exactly like this gesture always has - holding it
		    down is not meant to escalate into minutes-long jumps.
		  - 1 deliberate tap: seeks _SEEK_TAP_AMOUNTS[1] (12s).
		  - 2 deliberate taps within _SEEK_TAP_WINDOW_S of each other:
		    seeks _SEEK_TAP_AMOUNTS[2] (1 min) - NOT the 12s tap's amount
		    plus the 1 min amount; only one seek ever actually happens,
		    sized for however many taps were ultimately counted, since
		    the 1st tap's seek is held back (see below) precisely so it
		    doesn't fire before a 2nd tap has a chance to arrive.
		  - 3+ taps: seeks _SEEK_TAP_AMOUNTS[3] (5 min); further taps in
		    the same burst don't escalate any further.

		Held-vs-tap detection is a self-contained, time-based heuristic
		(see _SEEK_HOLD_GAP's comment above) rather than anything from
		NVDA's own scriptHandler.getLastScriptRepeatCount(): that counter
		can't tell a key being auto-repeated by Windows apart from
		several genuine separate presses in a row either - both just
		look like "the same script running again soon after the last
		time" - so it can't resolve the hold-vs-tap question on its own.
		This mirrors the manual time-based counter
		TrackInfoMixin._whats_playing_from_dialog() already uses for the
		same underlying reason (there: F2 is a dialog-local key, not an
		NVDA gesture, so getLastScriptRepeatCount() doesn't apply to it
		at all; here: it applies, but doesn't carry the information we
		actually need).

		A deliberate tap's seek is never executed immediately - it's
		scheduled via wx.CallLater(_SEEK_TAP_WINDOW_MS) so a follow-up
		tap arriving in time can cancel it and reschedule for the larger
		amount instead, the same debounce shape
		PlaybackCoreMixin.script_pauseResume() already uses for its own
		double/triple-press actions. A 3rd tap commits immediately
		instead of scheduling, since no 4th tap can escalate it further."""
		now = time.monotonic()
		state_attr = "_seek_fwd" if direction > 0 else "_seek_rew"
		last_t     = getattr(self, state_attr + "_last_time", 0.0)
		tap_count  = getattr(self, state_attr + "_tap_count", 0)
		delta = now - last_t
		setattr(self, state_attr + "_last_time", now)

		# Cancel any not-yet-committed tap from earlier in this same
		# burst - only the latest press's timer should end up running.
		old_timer = getattr(self, state_attr + "_tap_timer", None)
		if old_timer:
			old_timer.Stop()
			setattr(self, state_attr + "_tap_timer", None)

		if tap_count > 0 and delta < _SEEK_HOLD_GAP:
			# Still the same held-down key auto-repeating - not a fresh
			# tap. Reset the tap sequence (a real hold shouldn't leave a
			# stray tap count lying around for whatever the user does
			# next) and act immediately, every time, for responsiveness.
			setattr(self, state_attr + "_tap_count", 0)
			self._seek_and_announce(direction * _SEEK_HOLD_AMOUNT)
			return

		# A genuine, deliberate press: either the very first one, or one
		# that followed the previous one too slowly to be auto-repeat.
		# Still within the tap window of the previous *deliberate* tap?
		# Extend that sequence; otherwise this is the start of a new one.
		tap_count = tap_count + 1 if delta < _SEEK_TAP_WINDOW_S else 1
		tap_count = min(tap_count, len(_SEEK_TAP_AMOUNTS) - 1)
		setattr(self, state_attr + "_tap_count", tap_count)

		amount = direction * _SEEK_TAP_AMOUNTS[tap_count]
		if tap_count >= len(_SEEK_TAP_AMOUNTS) - 1:
			# Topped out (3rd tap) - nothing further to wait for.
			setattr(self, state_attr + "_tap_count", 0)
			self._seek_and_announce(amount)
			return

		def _commit(amt=amount):
			setattr(self, state_attr + "_tap_count", 0)
			setattr(self, state_attr + "_tap_timer", None)
			self._seek_and_announce(amt)

		setattr(self, state_attr + "_tap_timer", wx.CallLater(_SEEK_TAP_WINDOW_MS, _commit))

	def _live_rewind(self, seconds, gesture):
		"""Rewind the live time-shift buffer by *seconds*."""
		if not config.conf["freeAudio"].get("timeshift_enabled", False):
			# Translators: Spoken when Ctrl+Win+J (rewind) is pressed while the time-shift feature itself is turned off in settings.
			_notify(_("Time-shift buffer is disabled. Enable it in freeAudio settings."))
			return
		if not self._player.has_media():
			if gesture is not None:
				gesture.send()
			return

		ok, position, buffered, reason = self._player.rewind_timeshift(seconds)
		if not ok:
			_TIMESHIFT_REASON_MESSAGES = {
				# Translators: One of the reasons a rewind/forward can fail, mapped from rewind_timeshift()'s return reason to a spoken message (continues for the next six lines: feature disabled, wrong backend, HLS unsupported, not enough buffer yet, buffer file not ready, engine error).
				"bass_disabled":   _("Time-shift requires the BASS audio backend, which is currently disabled."),
				"feature_disabled": _("Time-shift buffer is disabled. Enable it in freeAudio settings."),
				"wrong_backend":   _("Time-shift is not available for the current playback backend."),
				"hls_unsupported": _("Time-shift is not supported for this station's stream (no seekable audio could be extracted)."),
				"no_buffer_yet":   _("Not enough buffered audio to rewind yet. Wait a few seconds after the station starts playing and try again."),
				"no_buffer_file":  _("Time-shift buffer file is not ready yet."),
				"engine_error":    _("Could not switch to time-shifted playback."),
			}
			# Translators: Generic fallback spoken if the rewind fails for a reason not covered by the specific messages above.
			_notify(_TIMESHIFT_REASON_MESSAGES.get(reason, _("Could not rewind")))
			return
		# Translators: Spoken after a successful rewind, reporting how far behind live the buffer now is; %.0f is the number of seconds.
		_notify(_("Rewound to %.0f seconds behind live") % (buffered - position))

	def _live_forward(self, seconds):
		"""Fast-forward the live time-shift buffer by *seconds*."""
		if not config.conf["freeAudio"].get("timeshift_enabled", False):
			# Translators: Same message as the rewind command, spoken here when Ctrl+Win+K (forward) is pressed with time-shift turned off.
			_notify(_("Time-shift buffer is disabled. Enable it in freeAudio settings."))
			return
		if not self._player.is_timeshifted():
			# Translators: Spoken when fast-forward is pressed but playback is already at the live edge (not time-shifted).
			_notify(_("Already listening live"))
			return

		ok, position, at_live_edge = self._player.forward_timeshift(seconds)
		if not ok:
			# Translators: Generic fallback spoken if the fast-forward operation fails.
			_notify(_("Could not fast-forward"))
			return
		if at_live_edge:
			# Translators: Spoken when a fast-forward catches all the way up to the live edge.
			_notify(_("Back to live"))
		else:
			buffered = self._player.get_timeshift_buffered_seconds()
			# Translators: Spoken after a fast-forward that has not yet caught up to live; %.0f is how many seconds behind live remain.
			_notify(_("Fast-forwarded, still %.0f seconds behind live") %
				(buffered - position))

	@script(
		# Translators: Name of an NVDA command (Ctrl+Win+J); rewinds the live time-shift buffer, or seeks backward within a podcast/audiobook file if one is playing.
		description=_("Time-shift: rewind 15 seconds (enters time-shift mode if not already active)"),
		category=_("freeAudio"),
		gesture="kb:control+windows+j",
	)
	def script_timeshiftRewind(self, gesture):
		# Podcast/sesli kitap oynatılıyorsa dosya içinde geri sar - bkz.
		# _handle_podcast_seek()'in tap/hold ayrımı.
		station = self._player.get_current_station()
		if _is_seekable_media(station):
			self._handle_podcast_seek(-1)
			return

		self._live_rewind(15, gesture)

	@script(
		# Translators: Name of an NVDA command (Ctrl+Win+K); fast-forwards the live time-shift buffer (snapping to live once caught up), or seeks forward within a podcast/audiobook file if one is playing.
		description=_("Time-shift: fast-forward 15 seconds, or return to live if already caught up"),
		category=_("freeAudio"),
		gesture="kb:control+windows+k",
	)
	def script_timeshiftForward(self, gesture):
		# Podcast/sesli kitap oynatılıyorsa dosya içinde ileri sar - bkz.
		# _handle_podcast_seek()'in tap/hold ayrımı.
		station = self._player.get_current_station()
		if _is_seekable_media(station):
			self._handle_podcast_seek(1)
			return

		self._live_forward(15)

	@script(
		# Translators: Name of an NVDA command (Ctrl+Win+Alt+J); fine rewind by 1 second.
		description=_("Fine rewind: 1 second (time-shift buffer, podcast, audiobook or jukebox)"),
		category=_("freeAudio"),
		gesture="kb:control+windows+alt+j",
	)
	def script_timeshiftRewindFine(self, gesture):
		if _is_seekable_media(self._player.get_current_station()):
			self._seek_and_announce(-_FINE_SEEK_AMOUNT)
			return
		self._live_rewind(_FINE_SEEK_AMOUNT, gesture)

	@script(
		# Translators: Name of an NVDA command (Ctrl+Win+Alt+K); fine fast-forward by 1 second.
		description=_("Fine forward: 1 second (time-shift buffer, podcast, audiobook or jukebox)"),
		category=_("freeAudio"),
		gesture="kb:control+windows+alt+k",
	)
	def script_timeshiftForwardFine(self, gesture):
		if _is_seekable_media(self._player.get_current_station()):
			self._seek_and_announce(_FINE_SEEK_AMOUNT)
			return
		self._live_forward(_FINE_SEEK_AMOUNT)

	@script(
		# Translators: Name of an NVDA command (Ctrl+Win+T); toggles the time-shift buffer feature on/off.
		description=_("Enable or disable the time-shift (rewind) buffer"),
		category=_("freeAudio"),
		gesture="kb:control+windows+t",
	)
	def script_toggleTimeshift(self, gesture):
		current = config.conf["freeAudio"].get("timeshift_enabled", False)
		new_value = not current
		config.conf["freeAudio"]["timeshift_enabled"] = new_value

		if self._player is not None:
			try:
				self._player.set_timeshift_enabled(new_value)
			except Exception as e:
				log.warning("freeAudio: could not apply timeshift_enabled change: %s", e, exc_info=True)

		# Best-effort: keep the Settings panel's checkbox in sync if it
		# happens to be open right now (mirrors script_toggleBassBackend's
		# approach for its own checkbox).
		if self._dialog is not None and hasattr(self._dialog, "_timeshift_enabled"):
			try:
				self._dialog._timeshift_enabled.SetValue(new_value)
			except Exception:
				pass

		# Translators: Spoken after toggling the time-shift buffer; the 'enabled'/'disabled' word is the same one used throughout freeAudio's other toggle announcements.
		ui.message(_("Time-shift buffer %s") % (_("enabled") if new_value else _("disabled")))
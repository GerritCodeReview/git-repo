# Copyright (C) 2009 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import sys
import time

try:
    import threading as _threading
except ImportError:
    import dummy_threading as _threading

from repo_trace import IsTraceToStderr

_NOT_TTY = not os.isatty(2)

# This will erase all content in the current line (wherever the cursor is).
# It does not move the cursor, so this is usually followed by \r to move to
# column 0.
CSI_ERASE_LINE = "\x1b[2K"

# This will erase all content in the current line after the cursor.  This is
# useful for partial updates & progress messages as the terminal can display
# it better.
CSI_ERASE_LINE_AFTER = "\x1b[K"


def convert_to_hms(total):
    """Converts a period of seconds to hours, minutes, and seconds."""
    hours, rem = divmod(total, 3600)
    mins, secs = divmod(rem, 60)
    return int(hours), int(mins), secs


def duration_str(total):
    """A less noisy timedelta.__str__.

    The default timedelta stringification contains a lot of leading zeros and
    uses microsecond resolution.  This makes for noisy output.
    """
    hours, mins, secs = convert_to_hms(total)
    ret = "%.3fs" % (secs,)
    if mins:
        ret = "%im%s" % (mins, ret)
    if hours:
        ret = "%ih%s" % (hours, ret)
    return ret


def elapsed_str(total):
    """Returns seconds in the format [H:]MM:SS.

    Does not display a leading zero for minutes if under 10 minutes. This should
    be used when displaying elapsed time in a progress indicator.
    """
    hours, mins, secs = convert_to_hms(total)
    ret = f"{int(secs):>02d}"
    if total >= 3600:
        # Show leading zeroes if over an hour.
        ret = f"{mins:>02d}:{ret}"
    else:
        ret = f"{mins}:{ret}"
    if hours:
        ret = f"{hours}:{ret}"
    return ret


class Progress(object):
    def __init__(
        self,
        title,
        total=0,
        units="",
        print_newline=False,
        delay=True,
        quiet=False,
        show_elapsed=False,
    ):
        self._title = title
        self._total = total
        self._done = 0
        self._start = time.time()
        self._show = not delay
        self._units = units
        self._print_newline = print_newline
        # Only show the active jobs section if we run more than one in parallel.
        self._show_jobs = False
        self._active = 0

        # Save the last message for displaying on refresh.
        self._last_msg = None
        self._show_elapsed = show_elapsed
        self._update_event = _threading.Event()
        self._update_thread = _threading.Thread(
            target=self._update_loop,
        )
        self._update_thread.daemon = True

        # When quiet, never show any output.  It's a bit hacky, but reusing the
        # existing logic that delays initial output keeps the rest of the class
        # clean.  Basically we set the start time to years in the future.
        if quiet:
            self._show = False
            self._start += 2**32
        elif show_elapsed:
            self._update_thread.start()

    def _update_loop(self):
        while True:
            if self._update_event.is_set():
                return
            self.update(inc=0, msg=self._last_msg)
            time.sleep(1)

    def start(self, name):
        self._active += 1
        if not self._show_jobs:
            self._show_jobs = self._active > 1
        self.update(inc=0, msg="started " + name)

    def finish(self, name):
        self.update(msg="finished " + name)
        self._active -= 1

    def update(self, inc=1, msg=""):
        self._done += inc
        self._last_msg = msg

        if _NOT_TTY or IsTraceToStderr():
            return

        elapsed_sec = time.time() - self._start
        if not self._show:
            if 0.5 <= elapsed_sec:
                self._show = True
            else:
                return

        if self._total <= 0:
            sys.stderr.write(
                "\r%s: %d,%s" % (self._title, self._done, CSI_ERASE_LINE_AFTER)
            )
            sys.stderr.flush()
        else:
            p = (100 * self._done) / self._total
            if self._show_jobs:
                jobs = "[%d job%s] " % (
                    self._active,
                    "s" if self._active > 1 else "",
                )
            else:
                jobs = ""
            if self._show_elapsed:
                elapsed = f" {elapsed_str(elapsed_sec)} |"
            else:
                elapsed = ""
            sys.stderr.write(
                "\r%s: %2d%% %s(%d%s/%d%s)%s %s%s%s"
                % (
                    self._title,
                    p,
                    jobs,
                    self._done,
                    self._units,
                    self._total,
                    self._units,
                    elapsed,
                    msg,
                    CSI_ERASE_LINE_AFTER,
                    "\n" if self._print_newline else "",
                )
            )
            sys.stderr.flush()

    def end(self):
        self._update_event.set()
        if _NOT_TTY or IsTraceToStderr() or not self._show:
            return

        duration = duration_str(time.time() - self._start)
        if self._total <= 0:
            sys.stderr.write(
                "\r%s: %d, done in %s%s\n"
                % (self._title, self._done, duration, CSI_ERASE_LINE_AFTER)
            )
            sys.stderr.flush()
        else:
            p = (100 * self._done) / self._total
            sys.stderr.write(
                "\r%s: %3d%% (%d%s/%d%s), done in %s%s\n"
                % (
                    self._title,
                    p,
                    self._done,
                    self._units,
                    self._total,
                    self._units,
                    duration,
                    CSI_ERASE_LINE_AFTER,
                )
            )
            sys.stderr.flush()

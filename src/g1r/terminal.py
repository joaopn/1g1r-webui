"""The screen a command draws on a terminal, rebuilt from what it writes.

igir draws its progress bars only on a terminal: it writes finished lines, and repaints a
block of bars below them in place by moving the cursor up and clearing lines. `Screen` keeps
what a terminal with endless scrollback would show, with each character's colour, from the
few control sequences igir uses: cursor up, down and to a column, clear (part of) a line,
clear below, colours. Anything else is skipped. A repaint wrapped in a synchronized update
counts as drawn only once it is complete.
"""

import codecs
import re

from g1r.config import TerminalConfig

ESC = "\x1b"
# A control sequence: optional private marker, parameters, final letter.
CSI = re.compile(r"\x1b\[([?>=]?)([0-9;]*)([@-~])")
# The start of a control sequence cut off at the end of what was read so far.
PARTIAL = re.compile(r"\x1b(\[[?>=]?[0-9;]*)?$")
NEWLINES = re.compile(r"(\r\n|\r|\n)")
# The synchronized update a repaint is wrapped in (DEC private mode 2026), and the private
# marker of DEC modes.
SYNC_MODE = "2026"
PRIVATE = "?"

# A run of text in one style: [text, style]. Style: a colour name, "faint", both
# ("green faint"), or "" for the terminal's own.
Segment = list[str]


class Screen:
    def __init__(self, config: TerminalConfig):
        self.config = config
        self.rows: list[list[tuple[str, str]]] = [[]]
        self.row = 0
        self.col = 0
        self.color = ""
        self.faint = False
        self.updating = False
        self.pending = ""
        self.decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    def feed(self, data: bytes) -> None:
        text = self.pending + self.decoder.decode(data)
        cut = PARTIAL.search(text)
        self.pending, text = (text[cut.start() :], text[: cut.start()]) if cut else ("", text)
        done = 0
        for match in CSI.finditer(text):
            self._text(text[done : match.start()])
            self._control(*match.groups())
            done = match.end()
        self._text(text[done:])

    @property
    def drawn(self) -> bool:
        """Not in the middle of a repaint: `lines` is what the terminal shows."""
        return not self.updating

    def lines(self) -> list[list[Segment]]:
        """The screen, top to bottom, without trailing blank lines; each line as its runs of
        text in one style, without trailing blanks."""
        out = [_segments(row) for row in self.rows]
        while out and not out[-1]:
            out.pop()
        return out

    def text(self) -> list[str]:
        return ["".join(text for text, _ in line) for line in self.lines()]

    def _text(self, text: str) -> None:
        for part in NEWLINES.split(text):
            if part in ("\r\n", "\n"):
                self._down(1)
                self.col = 0
            elif part == "\r":
                self.col = 0
            elif part:
                self._write(part.replace(ESC, ""))

    def _write(self, text: str) -> None:
        row = self.rows[self.row]
        style = self._style()
        if len(row) < self.col:
            row.extend([(" ", "")] * (self.col - len(row)))
        for offset, char in enumerate(text):
            cell = (char, style)
            if self.col + offset < len(row):
                row[self.col + offset] = cell
            else:
                row.append(cell)
        self.col += len(text)

    def _down(self, count: int) -> None:
        self.row += count
        while len(self.rows) <= self.row:
            self.rows.append([])

    def _control(self, private: str, params: str, final: str) -> None:
        if private == PRIVATE:
            if SYNC_MODE in params.split(";"):
                self.updating = final == "h"
            return
        if private:
            return
        count = max(int(params), 1) if params.isdigit() else 1
        row = self.rows[self.row]
        if final == "A":
            self.row = max(self.row - count, 0)
        elif final == "B":
            self._down(count)
        elif final == "G":
            self.col = count - 1
        elif final == "K":
            # 0 or nothing: to the end of the line; 1: to the cursor; 2: the whole line.
            mode = params or "0"
            if mode == "0":
                del row[self.col :]
            elif mode == "1":
                row[: self.col + 1] = [(" ", "")] * min(self.col + 1, len(row))
            else:
                row.clear()
        elif final == "J" and (params or "0") == "0":
            del row[self.col :]
            del self.rows[self.row + 1 :]
        elif final == "m":
            self._sgr(params)

    def _sgr(self, params: str) -> None:
        config = self.config
        if params.split(";")[0] in config.extended:
            # One colour given by several parameters ("38;5;240").
            self.color = config.colors.get(params, "")
            return
        for code in params.split(";"):
            if code in config.resets:
                self.color, self.faint = "", False
            elif code == config.plain:
                self.color = ""
            elif code == config.faint_on:
                self.faint = True
            elif code == config.faint_off:
                self.faint = False
            elif code in config.colors:
                self.color = config.colors[code]

    def _style(self) -> str:
        return " ".join(part for part in (self.color, "faint" if self.faint else "") if part)


def _segments(row: list[tuple[str, str]]) -> list[Segment]:
    end = len(row)
    while end and row[end - 1][0] == " ":
        end -= 1
    segments: list[Segment] = []
    for char, style in row[:end]:
        if segments and segments[-1][1] == style:
            segments[-1][0] += char
        else:
            segments.append([char, style])
    return segments

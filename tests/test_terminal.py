from g1r.config import load_settings
from g1r.terminal import Screen


def screen():
    return Screen(load_settings({}, {}).igir.terminal)


def test_a_repainted_bar_shows_its_last_frame_with_its_colours():
    s = screen()
    s.feed(b"banner\r\n\r\n")
    s.feed(b"\x1b[?25l\x1b[?2026h\x1b[1G \x1b[36m\xe2\x86\xbb\x1b[39m Scanning\x1b[0K\r\n")
    s.feed("   \x1b[90m■\x1b[39m\x1b[38;5;240m■■\x1b[39m 0/3\x1b[0K\r\n".encode())
    # In the middle of a repaint: not drawn yet.
    assert not s.drawn
    s.feed(b"\x1b[1G\x1b[?2026l")
    assert s.drawn
    assert s.lines() == [
        [["banner", ""]],
        [],
        [[" ", ""], ["↻", "cyan"], [" Scanning", ""]],
        [["   ", ""], ["■", "gray"], ["■■", "dark"], [" 0/3", ""]],
    ]
    # Repaint the bar line only: up one, overwrite, clear the rest of the line.
    s.feed("\x1b[?2026h\x1b[1A\x1b[1G   \x1b[32m■■■\x1b[39m 3/3\x1b[0K\r\n".encode())
    s.feed(b"\x1b[1G\x1b[?2026l")
    assert s.text()[-1] == "   ■■■ 3/3"
    # The region is cleared and a finished line written where it was.
    s.feed("\x1b[?2026h\x1b[2A\x1b[1G\x1b[0J \x1b[32m✓\x1b[39m Scanning ".encode())
    s.feed("\x1b[2m»\x1b[22m 3 files\r\n".encode())
    s.feed(b"\x1b[1G\x1b[?2026l\x1b[?25h")
    assert s.lines()[-1] == [
        [" ", ""],
        ["✓", "green"],
        [" Scanning ", ""],
        ["»", "faint"],
        [" 3 files", ""],
    ]
    assert s.text() == ["banner", "", " ✓ Scanning » 3 files"]


def test_sequences_and_characters_cut_between_reads():
    s = screen()
    data = "\x1b[32mok\x1b[0m ✓ fine\r\n".encode()
    for byte in data:
        s.feed(bytes([byte]))
    assert s.lines() == [[["ok", "green"], [" ✓ fine", ""]]]


def test_carriage_return_and_partial_clears():
    s = screen()
    s.feed(b"12345\rab\x1b[1K\r\n")
    s.feed(b"xyz\x1b[2Kq\r\n")
    assert s.text() == ["   45", "   q"]

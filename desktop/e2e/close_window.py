"""Ask an X window to close, as a window manager's close button does (WM_DELETE_WINDOW).

    uv run --no-project --with python-xlib python e2e/close_window.py WINDOW_ID

The end-to-end walkthrough closes the review window this way, so the app sees an ordinary
close: WebDriver's own "close window" removes only the web view.
"""

import sys

from Xlib import X, display, protocol


def main() -> None:
    screen = display.Display()
    window = screen.create_resource_object("window", int(sys.argv[1]))
    event = protocol.event.ClientMessage(
        window=window,
        client_type=screen.intern_atom("WM_PROTOCOLS"),
        data=(32, [screen.intern_atom("WM_DELETE_WINDOW"), X.CurrentTime, 0, 0, 0]),
    )
    window.send_event(event, event_mask=X.NoEventMask)
    screen.flush()


if __name__ == "__main__":
    main()

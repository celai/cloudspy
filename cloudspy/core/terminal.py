import os
import sys

_STD_OUTPUT_HANDLE = -11
_STD_ERROR_HANDLE = -12
_ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
_CODE_PAGE_UTF8 = 65001

_UNICODE_PROBE = "☁─│╭╮╰╯›·○✗●↳→…✓⠿"
_ASCII_ENV = ("0", "false", "no", "off")

_initialized = False

UNICODE = True
ANSI = True


def _force_utf8():
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleCP(_CODE_PAGE_UTF8)
            kernel32.SetConsoleOutputCP(_CODE_PAGE_UTF8)
        except Exception:
            pass
    for name in ("stdin", "stdout", "stderr"):
        stream = getattr(sys, name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _init_colorama():
    for entry in ("just_fix_windows_console", "init"):
        try:
            import colorama

            getattr(colorama, entry)()
            return True
        except Exception:
            continue
    return False


def _enable_ansi():
    if os.name != "nt":
        return True
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        kernel32.GetStdHandle.restype = wintypes.HANDLE

        enabled = False
        for handle_id in (_STD_OUTPUT_HANDLE, _STD_ERROR_HANDLE):
            handle = kernel32.GetStdHandle(handle_id)
            if not handle:
                continue
            mode = wintypes.DWORD()
            if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                continue
            if kernel32.SetConsoleMode(
                handle, mode.value | _ENABLE_VIRTUAL_TERMINAL_PROCESSING
            ):
                enabled = True
        if enabled:
            return True
    except Exception:
        pass
    return _init_colorama()


def _detect_unicode():
    forced = os.environ.get("CLOUDSPY_ASCII", "").strip().lower()
    if forced and forced not in _ASCII_ENV:
        return False
    forced = os.environ.get("CLOUDSPY_UNICODE", "").strip().lower()
    if forced and forced not in _ASCII_ENV:
        return True

    encoding = getattr(sys.stdout, "encoding", None) or ""
    try:
        _UNICODE_PROBE.encode(encoding)
    except (LookupError, TypeError, UnicodeError):
        return False

    if os.name == "nt":
        modern = ("WT_SESSION", "WT_PROFILE_ID", "TERM_PROGRAM", "TERM", "ConEmuANSI")
        return any(os.environ.get(name) for name in modern)
    return True


def setup():
    global _initialized, UNICODE, ANSI
    if _initialized:
        return
    _initialized = True
    _force_utf8()
    ANSI = _enable_ansi()
    UNICODE = _detect_unicode()


def clear(console=None):
    stream = getattr(console, "file", None) or sys.stdout
    try:
        is_tty = stream.isatty()
    except Exception:
        is_tty = False
    if not is_tty:
        return
    if ANSI:
        try:
            stream.write("\033[3J\033[2J\033[H")
            stream.flush()
            return
        except Exception:
            pass
    if console is not None:
        try:
            console.clear()
            return
        except Exception:
            pass
    os.system("cls" if os.name == "nt" else "clear")


setup()

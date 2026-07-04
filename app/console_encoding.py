"""Console encoding helpers for Windows terminals."""
import builtins
import sys


def configure_console_encoding() -> None:
    """Make stdout/stderr and print() tolerate UTF-8 on Windows consoles."""
    if sys.platform != "win32":
        return

    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    original_print = builtins.print

    def safe_print(*args, **kwargs) -> None:
        try:
            original_print(*args, **kwargs)
        except UnicodeEncodeError:
            encoded_args = tuple(
                str(arg).encode("ascii", errors="backslashreplace").decode("ascii")
                for arg in args
            )
            original_print(*encoded_args, **kwargs)

    builtins.print = safe_print

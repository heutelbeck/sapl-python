from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

ERROR_BUFFER_OVERFLOW = "SSE buffer exceeded 1MB limit, aborting stream"
ERROR_UTF8_DECODE = "SSE stream contained invalid UTF-8, skipping chunk"

_MAX_BUFFER_BYTES = 1024 * 1024  # 1 MB


class SseBufferOverflowError(Exception):
    """Raised when the SSE line buffer exceeds the maximum allowed size."""


async def parse_sse_stream(byte_stream: AsyncIterator[bytes]) -> AsyncIterator[str]:
    """Parse SSE wire format from a raw byte stream.

    REQ-SSE-1: Incremental UTF-8 decoding -- handles partial multi-byte
    sequences across chunk boundaries.

    REQ-SSE-2: Line parsing -- recognizes CR, LF, and CRLF as line endings.

    REQ-SSE-3: Extract ``data:`` field values. Multiple consecutive data
    lines are joined with newline characters. An empty line dispatches the
    accumulated event data.

    REQ-SSE-4: Parse failures (invalid UTF-8) are logged and the offending
    chunk is skipped; the stream continues.

    REQ-SSE-5: Buffer limit of 1 MB. If a single line exceeds this, the
    stream is aborted with ``SseBufferOverflowError``.

    Comment lines (starting with ``:``) are silently ignored.
    """
    logger = structlog.get_logger(__name__)
    decoder = _IncrementalUtf8Decoder()
    line_buffer = ""
    data_lines: list[str] = []
    has_data = False

    async for chunk in byte_stream:
        try:
            text = decoder.decode(chunk)
        except UnicodeDecodeError:
            logger.warning(ERROR_UTF8_DECODE)
            continue

        line_buffer += text

        while True:
            line, separator, remainder = _split_first_line(line_buffer)
            if not separator:
                break

            line_buffer = remainder
            event_line = _process_sse_line(line, data_lines, has_data)

            if event_line is _DISPATCH:
                if has_data:
                    yield "\n".join(data_lines)
                data_lines = []
                has_data = False
            elif event_line is _DATA:
                has_data = True
            # _SKIP means comment or ignored field -- do nothing

        if len(line_buffer.encode("utf-8")) > _MAX_BUFFER_BYTES:
            logger.error(ERROR_BUFFER_OVERFLOW)
            raise SseBufferOverflowError(ERROR_BUFFER_OVERFLOW)

    # Flush any remaining data after stream ends (no trailing blank line)
    if has_data and data_lines:
        yield "\n".join(data_lines)


class _IncrementalUtf8Decoder:
    """Handles incremental UTF-8 decoding across chunk boundaries."""

    def __init__(self) -> None:
        self._pending = b""

    def decode(self, chunk: bytes) -> str:
        data = self._pending + chunk
        try:
            text = data.decode("utf-8")
            self._pending = b""
            return text
        except UnicodeDecodeError:
            # Try decoding all but the last few bytes (max 3 for partial UTF-8)
            for trim in range(1, 4):
                try:
                    text = data[:-trim].decode("utf-8")
                    self._pending = data[-trim:]
                    return text
                except UnicodeDecodeError:
                    continue

            # Pending bytes from a previous chunk may be unrecoverable.
            # Discard them and retry with only the new chunk.
            if self._pending:
                self._pending = b""
                return self.decode(chunk)

            # Entire chunk is undecodable even without pending bytes.
            self._pending = b""
            raise


class _SseLineResult:
    """Marker for SSE line processing results."""

    def __init__(self, name: str) -> None:
        self._name = name

    def __repr__(self) -> str:
        return f"<{self._name}>"


_DISPATCH = _SseLineResult("DISPATCH")
_DATA = _SseLineResult("DATA")
_SKIP = _SseLineResult("SKIP")


def _split_first_line(text: str) -> tuple[str, str, str]:
    """Split text at the first line ending (CR, LF, or CRLF).

    Returns (line, separator, remainder). If no line ending is found,
    separator is empty and remainder is empty.
    """
    for i, char in enumerate(text):
        if char == "\r":
            if i + 1 < len(text) and text[i + 1] == "\n":
                return text[:i], "\r\n", text[i + 2 :]
            return text[:i], "\r", text[i + 1 :]
        if char == "\n":
            return text[:i], "\n", text[i + 1 :]
    return text, "", ""


def _process_sse_line(
    line: str,
    data_lines: list[str],
    has_data: bool,
) -> _SseLineResult:
    """Process a single SSE line.

    Returns _DISPATCH for an empty line (event boundary), _DATA when a data
    field is appended, or _SKIP for comments and unrecognized fields.
    """
    if not line:
        return _DISPATCH

    if line.startswith(":"):
        return _SKIP

    if line.startswith("data:"):
        value = line[5:]
        if value.startswith(" "):
            value = value[1:]
        data_lines.append(value)
        return _DATA

    if line == "data":
        data_lines.append("")
        return _DATA

    # Unrecognized field (event, id, retry, etc.) -- ignore per spec
    return _SKIP

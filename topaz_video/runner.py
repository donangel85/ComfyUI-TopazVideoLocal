"""Run Topaz FFmpeg commands.

Two things need care:

* stdin must be written from a separate thread while stdout/stderr are drained. Writing a
  multi-megabyte payload from the main thread deadlocks as soon as the pipe buffer fills.
* stdout must be discarded and never logged. Topaz prints an ``[TopazAuthManager]`` blob
  there containing an auth token; the video always goes to a file instead.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import dataclass

from .command import FFmpegCommand
from .errors import classify, is_encoder_failure
from .logging_util import get_logger, scrub

logger = get_logger()

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


@dataclass
class RunResult:
    exit_code: int
    stderr: str
    duration: float
    command: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


def run(command: FFmpegCommand, *, env: dict, cwd: str | None = None,
        stdin_payload: bytes | None = None, timeout: float | None = None,
        progress=None, interrupt_check=None) -> RunResult:
    """Execute *command*.

    ``progress`` receives ``(frames_done, message)`` as Topaz reports frames.
    ``interrupt_check`` is polled; if it raises or returns True the process is terminated.
    """
    argv = command.build()
    pretty = command.pretty()
    logger.debug("ffmpeg command:\n%s", pretty)

    start = time.time()
    proc = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE if stdin_payload is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=cwd,
        creationflags=_CREATE_NO_WINDOW,
    )

    stderr_lines: list[str] = []
    feed_error: list[BaseException] = []

    def drain_stderr():
        try:
            for raw in proc.stderr:
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                stderr_lines.append(line)
                if progress is not None:
                    frames = _parse_frame_count(line)
                    if frames is not None:
                        try:
                            progress(frames, line)
                        except Exception:
                            pass
        except Exception:
            pass

    def drain_stdout():
        # Read and drop. This carries the auth blob; it must not be logged or kept.
        try:
            while proc.stdout.read(1 << 16):
                pass
        except Exception:
            pass

    def feed_stdin():
        try:
            proc.stdin.write(stdin_payload)
            proc.stdin.flush()
        except BrokenPipeError:
            pass  # ffmpeg exited early; the real error is in stderr
        except BaseException as exc:  # noqa: BLE001
            feed_error.append(exc)
        finally:
            try:
                proc.stdin.close()
            except OSError:
                pass

    threads = [
        threading.Thread(target=drain_stderr, daemon=True),
        threading.Thread(target=drain_stdout, daemon=True),
    ]
    if stdin_payload is not None:
        threads.append(threading.Thread(target=feed_stdin, daemon=True))
    for thread in threads:
        thread.start()

    deadline = (start + timeout) if timeout else None
    interrupted = False
    while proc.poll() is None:
        if deadline and time.time() > deadline:
            logger.warning("timeout after %.0fs; terminating Topaz", timeout)
            _terminate(proc)
            break
        if interrupt_check is not None:
            try:
                if interrupt_check():
                    interrupted = True
                    logger.info("interrupted; terminating Topaz")
                    _terminate(proc)
                    break
            except Exception:
                interrupted = True
                _terminate(proc)
                break
        time.sleep(0.05)

    proc.wait()
    for thread in threads:
        thread.join(timeout=5)

    if interrupted:
        raise InterruptedError("Topaz processing was interrupted")
    if feed_error:
        raise feed_error[0]

    return RunResult(
        exit_code=proc.returncode,
        stderr=scrub("\n".join(stderr_lines)),
        duration=time.time() - start,
        command=pretty,
    )


def run_checked(command: FFmpegCommand, *, env: dict, cwd: str | None = None,
                stdin_payload: bytes | None = None, timeout: float | None = None,
                progress=None, interrupt_check=None,
                model: str | None = None, frame_count: int | None = None,
                min_frames: int | None = None,
                encoder_fallbacks: list[list[str]] | None = None) -> RunResult:
    """Run, and raise a classified error on failure.

    ``encoder_fallbacks`` are tried only when the failure is unambiguously an encoder
    failure *and* the command actually has an encoder. This is the corrected version of
    the behaviour described in section 5 of the handover document: a decoder message such
    as "The current mfx implementation is not supported" no longer triggers a pointless
    encoder swap.
    """
    result = run(command, env=env, cwd=cwd, stdin_payload=stdin_payload,
                 timeout=timeout, progress=progress, interrupt_check=interrupt_check)
    if result.ok:
        return result

    for fallback in (encoder_fallbacks or []):
        if not is_encoder_failure(result.stderr, command.output_encoder):
            break
        logger.warning("output encoder %s failed; retrying with %s",
                       command.output_encoder, " ".join(fallback))
        retry = command.with_encoder(fallback)
        result = run(retry, env=env, cwd=cwd, stdin_payload=stdin_payload,
                     timeout=timeout, progress=progress,
                     interrupt_check=interrupt_check)
        if result.ok:
            return result
        command = retry

    raise classify(
        result.exit_code,
        result.stderr,
        command=result.command,
        output_encoder=command.output_encoder,
        model=model,
        frame_count=frame_count,
        min_frames=min_frames,
    )


def _terminate(proc) -> None:
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _parse_frame_count(line: str):
    """Pull ``frame= 123`` out of an FFmpeg status line."""
    if "frame=" not in line:
        return None
    try:
        after = line.split("frame=", 1)[1].strip()
        digits = ""
        for char in after:
            if char.isdigit():
                digits += char
            elif digits:
                break
        return int(digits) if digits else None
    except (ValueError, IndexError):
        return None

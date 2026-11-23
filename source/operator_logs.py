import logging
import tempfile
import time
from pathlib import Path

from .build_profile import IS_PRODUCTION_BUILD

LAST_OPERATOR_LOG_PATH = Path(tempfile.gettempdir()) / "moldboxer_silicone_last_operator.log"
_BLENDER_DRAW_WARNING_MARKER = "Draw window and swap:"

_handler: logging.Handler | None = None
_capture_depth = 0
_logger_states: dict[str, tuple[int, bool]] = {}
_operator_start_time: float | None = None


def _without_blender_draw_warnings(log_text: str) -> str:
    return "\n".join(
        line
        for line in log_text.splitlines()
        if _BLENDER_DRAW_WARNING_MARKER not in line
    )


def get_last_operator_log_path() -> Path:
    return LAST_OPERATOR_LOG_PATH


def log_background_event(event_logger, message: str, *args) -> None:
    """Keep timer-driven diagnostic events in the copyable development log."""
    event_logger.info(message, *args)
    if IS_PRODUCTION_BUILD or _handler is not None:
        return
    try:
        # No capture is active: append without resetting the previous operation.
        with LAST_OPERATOR_LOG_PATH.open("a", encoding="utf-8") as stream:
            record = event_logger.makeRecord(
                event_logger.name, logging.INFO, "", 0, message, args, None
            )
            formatter = logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
            stream.write(formatter.format(record) + "\n")
    except OSError:
        event_logger.debug("Could not append background diagnostic log", exc_info=True)


def _remove_stale_operator_log() -> None:
    try:
        LAST_OPERATOR_LOG_PATH.unlink(missing_ok=True)
    except OSError:
        pass


def _moldboxer_logger_names() -> tuple[str, ...]:
    names: set[str] = set()
    marker_names = {"moldboxer_silicone", "moldboxer_silicone_native"}

    package_parts = (__package__ or "").split(".")
    for index, part in enumerate(package_parts):
        if part in marker_names:
            names.add(".".join(package_parts[: index + 1]))

    for logger_name in logging.Logger.manager.loggerDict:
        parts = logger_name.split(".")
        for index, part in enumerate(parts):
            if part in marker_names:
                names.add(".".join(parts[: index + 1]))
                break

    if not names and __package__:
        names.add(__package__.split(".source", 1)[0])
    return tuple(sorted(names))


def begin_operator_log(operator_id: str, operator_label: str) -> bool:
    global _handler, _capture_depth, _logger_states, _operator_start_time

    if IS_PRODUCTION_BUILD:
        _remove_stale_operator_log()
        return False

    _capture_depth += 1
    if _capture_depth > 1:
        return False

    _operator_start_time = time.perf_counter()
    LAST_OPERATOR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(LAST_OPERATOR_LOG_PATH, mode="w", encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger_states: dict[str, tuple[int, bool]] = {}
    for logger_name in _moldboxer_logger_names():
        package_logger = logging.getLogger(logger_name)
        logger_states[logger_name] = (package_logger.level, package_logger.propagate)
        package_logger.setLevel(logging.DEBUG)
        package_logger.propagate = False
        package_logger.addHandler(handler)
    _logger_states = logger_states
    _handler = handler
    logging.getLogger(__name__).info(
        "Started operator %s (%s)", operator_id, operator_label
    )
    return True


def end_operator_log(operator_id: str, operator_label: str, result=None) -> None:
    global _handler, _capture_depth, _logger_states, _operator_start_time

    if IS_PRODUCTION_BUILD:
        return

    if _capture_depth <= 0:
        return

    _capture_depth -= 1
    if _capture_depth > 0:
        return

    elapsed = (
        time.perf_counter() - _operator_start_time
        if _operator_start_time is not None
        else None
    )
    if elapsed is None:
        logging.getLogger(__name__).info(
            "Finished operator %s (%s) result=%s",
            operator_id,
            operator_label,
            result,
        )
    else:
        logging.getLogger(__name__).info(
            "Finished operator %s (%s) result=%s total_time=%.3fs",
            operator_id,
            operator_label,
            result,
            elapsed,
        )
    _operator_start_time = None

    handler = _handler
    _handler = None
    if handler is None:
        return

    for logger_name, (previous_level, previous_propagate) in _logger_states.items():
        package_logger = logging.getLogger(logger_name)
        package_logger.removeHandler(handler)
        package_logger.setLevel(previous_level)
        package_logger.propagate = previous_propagate
    _logger_states = {}
    handler.flush()
    handler.close()


def read_last_operator_log() -> str:
    if IS_PRODUCTION_BUILD:
        return ""
    if not LAST_OPERATOR_LOG_PATH.is_file():
        return ""
    return _without_blender_draw_warnings(
        LAST_OPERATOR_LOG_PATH.read_text(encoding="utf-8")
    )


def last_operator_log_mtime() -> float:
    if IS_PRODUCTION_BUILD:
        return 0.0
    if not LAST_OPERATOR_LOG_PATH.is_file():
        return 0.0
    return LAST_OPERATOR_LOG_PATH.stat().st_mtime


def last_operator_log_age_seconds() -> float:
    if IS_PRODUCTION_BUILD:
        return 0.0
    mtime = last_operator_log_mtime()
    if not mtime:
        return 0.0
    return max(0.0, time.time() - mtime)

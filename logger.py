import logging

logger = logging.getLogger()


def _log(message: str, context: str = "Global", level: int = logging.INFO) -> None:
    for line in message.split('\n'):
        logger.log(level, f"[{context.center(22, '=')}] {line}")


def log(*args, **kwargs):
    _log(*args, **kwargs)


def cmd_log_handler(func):
    global _log
    _log = func
    return func

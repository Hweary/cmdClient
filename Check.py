from __future__ import annotations

from functools import wraps
from typing import Callable, Optional

from .Context import Context


class Check:
    """
    A `check` to be executed during or before command execution.

    Parameters
    ----------
    name: str
        Name of the check to use in logs.
    msg: str
        The string to post when a check fails before a command.
    check_func: Callable[..., bool]
        The check function used to evaluate the check.
        This must take a `Context` as the first argument.
        It must accept arbitrary arguments and keyword arguments.
        It must return `True` if the check passed, and `False` if the check failed.
    parents: List[Check]
        A list of `Checks` which superscede the current check.
        Precisely, if one of the parent checks pass, this check will also pass.
    requires: List[Check]
        A list of `Checks` required by the current check.
        All of these checks must pass for the current check to pass.
        These are checked after the parents.
    """
    def __init__(
        self,
        name: str,
        msg: str,
        check_func: Callable[..., bool],
        parents: Optional[list[Check]] = None,
        requires: Optional[list[Check]] = None
    ) -> None:
        self.name: str = name
        self.msg: str = msg
        self.check_func: Callable[..., bool] = check_func

        self.parents: list[Check] = parents or []
        self.required: list[Check] = requires or []

    def __call__(self, *args, **kwargs):
        """
        Returns a function decorator which adds this check before the function.
        Throws FailedCheck if the check fails.
        TODO: figure out proper typing.
        """
        def decorator(func):
            @wraps(func)
            async def wrapper(ctx: Context, *fargs, **fkargs):
                result: bool = await self.run(ctx, *args, **kwargs)
                
                if not result:
                    raise FailedCheck(self)

                return await func(ctx, *fargs, **fkargs)

            return wrapper

        return decorator

    async def run(self, ctx, *args, **kwargs) -> bool:
        """
        Executes this check and returns `True` if it passes or `False` if it fails.
        """
        # First check the parents
        for check in self.parents:
            if await check.run(ctx, *args, **kwargs):
                return True

        # Then check the requirements
        for check in self.required:
            if not await check.run(ctx, *args, **kwargs):
                return False

        # Now if we have passed all these, check the main function
        return await self.check_func(ctx, *args, **kwargs)


class FailedCheck(Exception):
    """
    Custom exception to throw when a pre-command check fails.
    Stores the check which failed.
    """
    def __init__(self, check: Check) -> None:
        super().__init__()
        self.check: Check = check


def check(*args, **kwargs) -> Callable[[Callable[..., bool]], Check]:
    """
    Helper decorator for creating new checks.
    All arguments are passed to `Check` along with the decorated function as `check_func`.
    """
    def decorator(func: Callable[..., bool]) -> Check:
        return Check(check_func=func, *args, **kwargs)

    return decorator

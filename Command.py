from __future__ import annotations

import logging
import traceback
import asyncio
import textwrap
from typing import Optional, Callable, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .Module import Module
    from .Context import Context

from .logger import log
from .Check import FailedCheck
from .lib import SafeCancellation, flag_parser


class Command:
    """
    Object wrapping function to make it into a text command.

    Parameters
    ----------
    name: str
        Name of the command.
    func: Callable
        Function the command wraps around.
    module: Module
        Module the command belongs to.
    handle_edits: bool
        Rerun the command on message edit.
    aliases: list[str]
        Other names the command goes under.
    flags: list[str]
        Flags to pass additional arguments to command.
    hidden: bool
        Don't display the command in public help messages.
    short_help: str
        Brief help message for the command.
    """
    def __init__(self, name: str, func: Callable, module: Module, **kwargs) -> None:
        self.name: str = name
        self.func: Callable = func
        self.module: Module = module

        self.handle_edits: bool = kwargs.pop("handle_edits", True)

        self.aliases: list[str] = kwargs.pop("aliases", [])
        self.flags: list[str] = kwargs.pop("flags", [])
        self.hidden: bool = kwargs.pop("hidden", False)
        self.short_help: Optional[str] = kwargs.pop("short_help", None)
        self.long_help: list[tuple[str, str]] = self.parse_help()

        self.__dict__.update(kwargs)

    async def run(self, ctx: Context) -> None:
        """
        Safely execute this command with the current context.
        Respond and log any exceptions that arise.
        """
        try:
            task: asyncio.Task = asyncio.ensure_future(self.exec_wrapper(ctx))
            ctx.tasks.append(task)
            await task
        except FailedCheck as e:
            log(
                f"Command failed check: {e.check.name}",
                context=f"mid:{ctx.msg.id}",
                level=logging.DEBUG
            )

            if e.check.msg:
                await ctx.error_reply(e.check.msg)
        except SafeCancellation as e:
            log(
                f"Caught a safe command cancellation: {e.__class__.__name__}: {e.details}",
                context=f"mid:{ctx.msg.id}",
                level=logging.DEBUG
            )

            if e.msg is not None:
                await ctx.error_reply(e.msg)
        except asyncio.TimeoutError:
            log(
                "Caught an unhandled TimeoutError",
                context=f"mid:{ctx.msg.id}",
                level=logging.WARNING
            )

            await ctx.error_reply("Operation timed out.")
        except asyncio.CancelledError:
            log(
                "Command was cancelled, probably due to a message edit.",
                context=f"mid:{ctx.msg.id}",
                level=logging.DEBUG
            )
        except Exception as e:
            full_traceback: str = traceback.format_exc()
            only_error: str = "".join(traceback.TracebackException.from_exception(e).format_exception_only())

            log(
                "Caught the following exception while running command:\n{}".format(full_traceback),
                context=f"mid:{ctx.msg.id}",
                level=logging.ERROR
            )

            await ctx.reply(
                "An unexpected internal error occurred while running your command! "
                "Please report the following error to the developer:\n`{}`".format(only_error)
            )
        else:
            log(
                "Command completed execution without error.",
                context=f"mid:{ctx.msg.id}",
                level=logging.DEBUG
            )

    async def exec_wrapper(self, ctx: Context) -> None:
        """
        Execute the command in the current context.
        May raise an exception if not handled by the module on_exception handler.
        """
        try:
            await self.module.pre_command(ctx)
            if self.flags:
                flags, ctx.args = flag_parser(ctx.arg_str, self.flags)
                await self.func(ctx, flags=flags)
            else:
                await self.func(ctx)
            await self.module.post_command(ctx)
        except Exception as e:
            await self.module.on_exception(ctx, e)

    def parse_help(self) -> list[tuple[str, str]]:
        """
        Convert the docstring of the command function into a list of pairs.
        Each pair consists of the field name and the field's content.
        """
        if not self.func.__doc__:
            return []

        # Split the docstring into lines
        lines: list[str] = textwrap.dedent(self.func.__doc__).strip().splitlines()
        help_fields: list[tuple[str, str]] = []
        field_name: str = ""
        field_content: list[str] = []

        for line in lines:
            if line.endswith(':'):
                # New field!
                if field_content:
                    # Add the previous field to the table
                    field = textwrap.dedent("\n".join(field_content))
                    help_fields.append((field_name, field))

                # Initialise the new field
                field_name = line[:-1].strip()
                field_content = []
            else:
                # Add the line to the current field content
                field_content.append(line)

        # Add the last field to the table if it exists
        if field_content:
            # Add the previous field to the table
            field = textwrap.dedent("\n".join(field_content))
            help_fields.append((field_name, field))

        return help_fields

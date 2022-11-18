from __future__ import annotations

import discord
import asyncio
from typing import NamedTuple, Optional, Callable, Union, Any, TYPE_CHECKING

from . import lib

if TYPE_CHECKING:
    from .cmdClient import cmdClient
    from .Command import Command


class FlatContext(NamedTuple):
    mid: Optional[int]
    cid: Optional[int]
    gid: Optional[int]
    uid: Optional[int]
    arg_str: Optional[str]
    cmd: Optional[str]
    alias: Optional[str]
    prefix: Optional[str]
    cleanup_on_edit: bool
    reparse_on_edit: bool
    sent_messages: tuple[int, ...]


class Context:
    """
    The data relevant with respect to a command.

    Parameters
    ----------
    client: cmdClient
        Client to which command was sent.
    msg: discord.Message
        Message in which command was detected.
    ch: Union[discord.TextChannel, discord.VoiceChannel, discord.Thread, discord.DMChannel]
        Channel in which command was sent.
    guild: discord.Guild
        Guild in which command was sent.
    args: str
        Argument string, intended to be overriden by argument parsers.
    arg_str: str
        Raw argument string.
    cmd: Command
        Command that was sent.
    alias: str
        Name in message under which command was called.
    author: discord.User
        User that called the command.
    prefix: str
        Prefix of command.
    sent_messages: list[discord.Message]
        Cache of messages sent in this context.
    cleanup_on_edit: bool
        Remove generated messages if their original message is edited.
    reparse_on_edit: bool
        Reparse the command if its original message is edited.
    tasks: list[asyncio.Task]
        Context tasks, including for the final wrapped command.
    """
    __slots__ = (
        "client",
        "msg",
        "ch",
        "guild",
        "args",
        "arg_str",
        "cmd",
        "alias",
        "author",
        "prefix",
        "sent_messages",
        "cleanup_on_edit",
        "reparse_on_edit",
        "tasks"
    )

    def __init__(self, client: cmdClient, **kwargs) -> None:
        self.client: cmdClient = client
        
        self.msg: Optional[discord.Message] = kwargs.pop("message", None)
        
        self.ch: Optional[Union[discord.TextChannel, discord.VoiceChannel, discord.Thread, discord.DMChannel]]
        self.ch = self.msg.channel if self.msg is not None else kwargs.pop("channel", None)
        
        self.guild: Optional[discord.Guild] = self.msg.guild if self.msg is not None else kwargs.pop("guild", None)
        self.author: Optional[discord.User] = self.msg.author if self.msg is not None else kwargs.pop("author", None)

        self.arg_str: Optional[str] = kwargs.pop("arg_str", None)
        self.cmd: Optional[Command] = kwargs.pop("cmd", None)
        self.alias: Optional[str] = kwargs.pop("alias", None)
        self.prefix: Optional[str] = kwargs.pop("prefix", None)

        self.cleanup_on_edit: bool = kwargs.pop("cleanup_on_edit", self.cmd.handle_edits if self.cmd is not None else True)
        self.reparse_on_edit: bool = kwargs.pop("reparse_on_edit", self.cmd.handle_edits if self.cmd is not None else True)

        self.args: Optional[str] = self.arg_str
        self.sent_messages: list[discord.Message] = []
        self.tasks: list[asyncio.Task] = []

    @classmethod
    def util(cls, util_func: Callable[..., Any]) -> None:
        """
        Decorator to make a utility function available as a Context instance method.
        """
        setattr(cls, util_func.__name__, util_func)

    def flatten(self) -> FlatContext:
        """
        Returns a flat version of the current context for debugging or caching.
        Does not store `objects`.
        Intended to be overriden if different cache data is needed.
        """
        return FlatContext(
            mid=self.msg.id if self.msg else None,
            cid=self.ch.id if self.ch else None,
            gid=self.guild.id if self.guild else None,
            uid=self.author.id if self.author else None,
            arg_str=self.arg_str,
            cmd=self.cmd.name if self.cmd else None,
            alias=self.alias,
            prefix=self.prefix,
            cleanup_on_edit=self.cleanup_on_edit,
            reparse_on_edit=self.reparse_on_edit,
            sent_messages=tuple([message.id for message in self.sent_messages])
        )


@Context.util
async def reply(ctx: Context, content: Optional[str] = None, allow_everyone: bool = False, **kwargs) -> discord.Message:
    """
    Helper function to reply in the current channel.
    """
    if not allow_everyone:
        if content:
            content = lib.sterilise_content(content)

    message: discord.Message = await ctx.ch.send(content=content, **kwargs)
    ctx.sent_messages.append(message)
    return message


@Context.util
async def error_reply(ctx: Context, error_str: str) -> discord.Message:
    """
    Notify the user of a user level error.
    Typically, this will occur in a red embed, posted in the command channel.
    """
    embed: discord.Embed = discord.Embed(
        colour=discord.Colour.red(),
        description=error_str,
        timestamp=discord.utils.utcnow()
    )

    message: discord.Message

    try:
        message = await ctx.ch.send(embed=embed)
    except discord.Forbidden:
        message = await ctx.reply(error_str)
        
    ctx.sent_messages.append(message)
    return message

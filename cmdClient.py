from __future__ import annotations

import imp
import sys
import os
import traceback
import logging
import asyncio
import discord
import itertools
from cachetools import LRUCache
from typing import ClassVar, Type, Optional, Callable, Union, Any
from types import ModuleType
from bisect import bisect

from .logger import log
from .Module import Module
from .Context import Context, FlatContext
from .Command import Command


class cmdClient(discord.Client):
    baseModule: ClassVar[Type[Module]] = Module
    default_module: ClassVar[Module] = None
    # List of loaded modules
    modules: list[Module] = []
    # Command name cache, including aliases
    cmd_names: dict[str, Command] = {}

    def __init__(
        self,
        prefix: Optional[str] = None,
        owners: Optional[list[int]] = None,
        ctx_cache: Optional[LRUCache] = None,
        baseContext: Type[Context] = Context,
        intents: discord.Intents = discord.Intents.default(),
        **kwargs
    ) -> None:
        # Message intents is necessary in this model
        intents.message_content = True
        super().__init__(intents=intents, **kwargs)

        self.prefix: Optional[str] = prefix
        self.owners: list[int] = owners or []
        self.objects = {}

        self.baseContext: Type[Context] = baseContext
        
        # Previous Context cache else new one
        # Cache entries look like {mid: FlatContext}
        self.ctx_cache: LRUCache = ctx_cache or LRUCache(1000)
        self.active_contexts: dict[int, Context] = {}

        self.extra_message_parsers = []

    @property
    def cmds(self) -> list[Command]:
        """
        A list of current available commands.
        """
        return list(itertools.chain(*[module.cmds for module in self.modules if module.enabled]))

    @classmethod
    def get_default_module(cls) -> Module:
        """
        Returns the default module, instantiating it if it does not exist.
        """
        if cls.default_module is None:
            cls.default_module = cls.baseModule()
        return cls.default_module

    @classmethod
    def cmd(cls, *args, module: Optional[Module] = None, **kwargs) -> Callable[[Callable], Command]:
        """
        Helper decorator to create a command with an optional module.
        If no module is specified, uses the class default module.
        """
        module: Module = module or cls.get_default_module()
        return module.cmd(*args, **kwargs)

    @classmethod
    def update_cmdnames(cls) -> None:
        """
        Updates the command name cache.
        """
        cmds: dict[str, Command] = {}

        for module in cls.modules:
            if module.enabled:
                for cmd in module.cmds:
                    cmds[cmd.name] = cmd

                    for alias in cmd.aliases:
                        cmds[alias] = cmd
        
        cls.cmd_names = cmds

    async def valid_prefixes(self, message: discord.Message) -> tuple[str, ...]:
        if self.prefix:
            return (self.prefix,)
        else:
            log(
                "No prefix set and no prefix function implemented.",
                level=logging.ERROR
            )
            
            await self.close()
            return ()

    def set_valid_prefixes(self, func: Callable) -> None:
        setattr(self, "valid_prefixes", func.__get__(self))

    def initialise_modules(self) -> None:
        log("Initialising all client modules.")

        for module in self.modules:
            if module.enabled:
                module.initialise(self)

    async def launch_modules(self) -> None:
        log("Launching all client modules.")
        
        for module in self.modules:
            if module.enabled:
                await module.launch(self)

    async def on_ready(self) -> None:
        """
        Client has logged into discord and completed initialisation.
        Log a ready message with some basic statistics and info.
        """
        await self.launch_modules()

        ready_str = (
            f"Logged in as {self.user}""\n"
            f"User id {self.user.id}""\n"
            f"Logged in to {len(self.guilds)} guilds""\n"
            "------------------------------\n"
            f"Default prefix is '{self.prefix}'""\n"
            f"Loaded {len(self.cmds)} commands""\n"
            "------------------------------\n"
            "Ready to take commands!\n"
        )
        
        log(ready_str)

    async def on_error(self, event_method: str, *args, **kwargs):
        """
        An exception was caught in one of the event handlers.
        Log the exception with a traceback, and continue on.
        """
        log(
            f"Ignoring exception in {event_method}""\n"f"{traceback.format_exc()}",
            level=logging.ERROR
        )

    async def on_message(self, message: discord.Message) -> None:
        """
        Event handler for `message`.
        Intended to be overridden.
        """
        await self.parse_message(message)

    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if (before.content != after.content):
            if after.id in self.ctx_cache:
                flatctx: FlatContext = self.ctx_cache[after.id]
                
                # Cleanup if required
                if flatctx.cleanup_on_edit:
                    if after.id in self.active_contexts and self.active_contexts[after.id].tasks:
                        ctx: Context = self.active_contexts[after.id]
                         
                        for task in ctx.tasks:
                            task.cancel()
                        
                        # Wait for the task to be removed from active contexts
                        while after.id in self.active_contexts:
                            await asyncio.sleep(0.1)
                        
                        asyncio.ensure_future(self.active_command_response_cleaner(ctx))
                    else:
                        asyncio.ensure_future(self.flat_command_response_cleaner(flatctx))
                
                # Reparse if required
                if flatctx.reparse_on_edit:
                    await self.parse_message(after)
            else:
                # If the message isn't in cache, treat as a new message
                await self.on_message(after)

    async def flat_command_response_cleaner(self, flatctx: FlatContext) -> None:
        ch: Optional[Union[discord.TextChannel, discord.VoiceChannel, discord.Thread, discord.DMChannel]]
        ch = self.get_channel(flatctx.cid)
        
        if ch is not None:
            for msgid in flatctx.sent_messages:
                try:
                    msg: discord.Message = await ch.fetch_message(msgid)
                    asyncio.ensure_future(msg.delete())
                except Exception:
                    pass

    async def active_command_response_cleaner(self, ctx: Context) -> None:
        try:
            if ctx.guild and ctx.ch.permissions_for(ctx.guild.me).manage_messages:
                await ctx.ch.delete_messages(ctx.sent_messages)
            else:
                await asyncio.gather(*(msg.delete() for msg in ctx.sent_messages))
        except discord.NotFound:
            pass

    async def parse_message(self, message: discord.Message) -> None:
        """
        Parse incoming messages.
        If the message contains a valid command, pass the message to run_cmd
        """
        content: str = message.content.strip()

        # Get valid prefixes
        prefixes: tuple[str, ...] = await self.valid_prefixes(message)
        prefixes = tuple(prefix for prefix in prefixes if content.startswith(prefix))
        
        for prefix in sorted(prefixes, reverse=True):
            # If the message starts with a valid command, pass it along to run_cmd
            stripcontent: str = content[len(prefix):].strip()
            cmdnames: list[str] = [cmdname for cmdname in self.cmd_names if stripcontent[:len(cmdname)].lower() == cmdname]

            if cmdnames:
                cmdname: str = max(cmdnames, key=len)
                await self.run_cmd(message, cmdname, stripcontent[len(cmdname):].strip(), prefix)
                return

        # Run the extra message parsers
        for parser in self.extra_message_parsers:
            asyncio.ensure_future(parser[0](self, message), loop=self.loop)

    async def run_cmd(self, message: discord.Message, cmdname: str, arg_str: str, prefix: str) -> None:
        """
        Run a command and pass it the command message and the `arg_str`.

        Parameters
        ----------
        message: discord.Message
            The original command message.
        cmdname: str
            The name of the command to execute.
        arg_str: str
            The remaining content of the command message after the prefix and command name.
        prefix: str
            Prefix used in invoking command.
        """
        cmd: Command = self.cmd_names[cmdname]
        content: str = "\n".join(("\t" + line for line in message.content.splitlines()))

        log(
            f"Executing command '{cmdname}' from module '{cmd.module.name}' "
            f"from user '{message.author}' (uid:{message.author.id}) "
            f"in guild '{message.guild}' (gid:{message.guild.id if message.guild else None}) "
            f"in channel '{message.channel}' (cid:{message.channel.id})"".""\n"
            f"{content}",
            context=f"mid:{message.id}"
        )

        if not cmd.module.enabled:
            log(
                "Skipping command due to disabled module.",
                context=f"mid:{message.id}"
            )
            
            self.update_cmdnames()

        # Build the context
        ctx: Context = self.baseContext(
            client=self,
            message=message,
            arg_str=arg_str,
            alias=cmdname,
            cmd=cmd,
            prefix=prefix
        )

        # Add command to command cache and active contexts
        self.ctx_cache[message.id] = ctx.flatten()
        self.active_contexts[message.id] = ctx

        try:
            await cmd.run(ctx)
        except Exception:
            log(
                f"The following exception was encountered executing command '{cmdname}'.""\n"f"{traceback.format_exc()}",
                context=f"mid:{message.id}",
                level=logging.ERROR
            )
        finally:
            # Renew command in command cache
            self.ctx_cache[message.id] = ctx.flatten()
            # Remove message from active contexts
            self.active_contexts.pop(message.id, None)

    def load_dir(self, dirpath: str) -> None:
        """
        Import all modules in a directory.
        Primarily for the use of importing new commands.
        """
        loaded: int = 0
        initial_cmds: int = len(self.cmds)

        for fn in os.listdir(dirpath):
            path: str = os.path.join(dirpath, fn)
            
            if fn.endswith(".py"):
                sys.path.append(dirpath)
                module: ModuleType = imp.load_source("bot_module_" + str(fn), path)
                sys.path.remove(dirpath)

                if "load_into" in dir(module):
                    module.load_into(self)

                loaded += 1

        log(f"Imported {loaded} modules from '{dirpath}', with {len(self.cmds) - initial_cmds} new commands!")

    def add_message_parser(self, func: Callable[[cmdClient, discord.Message], Any], priority:int = 0) -> None:
        """
        Add a message parser to execute when the command message parser fails.

        Parameters
        ----------
        func: Callable[[cmdClient, discord.Message], Any]
            Function taking the client and the discord message to process.
        priority: int
            Priority indiciating which order the parsers should be run.
            The command message parser is always executed first.
            After that, parsers are executed in order of increasing priority.
        """
        async def new_func(client: cmdClient, message: discord.Message) -> None:
            try:
                await func(client, message)
            except Exception:
                log(
                    f"Exception encountered executing parser '{func.__name__}' for a message "
                    f"from user '{message.author}' (uid:{message.author.id}) "
                    f"in guild '{message.guild}' (gid:{message.guild.id if message.guild else None}) "
                    f"in channel '{message.channel}' (cid:{message.channel.id}).""\n"
                    "Traceback:\n{traceback}\n"
                    "Content:\n{content}".format(
                        content='\n'.join(('\t' + line for line in message.content.splitlines())),
                        traceback='\n'.join(('\t' + line for line in traceback.format_exc().splitlines()))
                    ),
                    context=f"mid:{message.id}",
                    level=logging.ERROR
                )

        self.extra_message_parsers.insert(
            bisect([parser[1] for parser in self.extra_message_parsers], priority),
            (new_func, priority)
        )

        log(f"Adding message parser '{func.__name__}' with priority '{priority}'")

    def add_after_event(self, event: str, func: Optional[Callable] = None, priority: int = 0) -> Optional[Callable]:
        """
        Add an event handler to execute after the central event handler.

        Parameters
        ----------
        event: str
            Name of a valid discord.py event.
        func: Function(Client, ...)
            Function taking the client as its first argument, and the event parameters as the rest.
        priority: int
            Priority indiciating which order the event handlers should be executed.
            The core event handler is always executed first.
            After that, handlers are executed in order of increasing priority.
        """
        def wrapper(func: Callable) -> None:
            async def new_func(*args, **kwargs) -> None:
                try:
                    await func(*args, **kwargs)
                except Exception:
                    log(
                        f"Exception encountered executing event handler '{func.__name__}' for event '{event}'. "
                        "Traceback:\n"f"{traceback.format_exc()}",
                        level=logging.ERROR
                    )

            after_handler: str = "after_" + event
            
            if not hasattr(self, after_handler):
                setattr(self, after_handler, [])
            
            handlers: list[tuple[Callable, int]] = getattr(self, after_handler)
            handlers.insert(bisect([handler[1] for handler in handlers], priority), (new_func, priority))
            
            log(f"Adding after_event handler '{func.__name__}' for event '{event}' with priority '{priority}'")

        if func is None:
            return wrapper
        else:
            return wrapper(func)

    def dispatch(self, event: str, *args, **kwargs) -> None:
        super().dispatch(event, *args, **kwargs)
        after_handler: str = "after_" + event
        
        if hasattr(self, after_handler):
            for handler in getattr(self, after_handler):
                asyncio.ensure_future(handler[0](self, *args, **kwargs), loop=self.loop)


cmd = cmdClient.cmd

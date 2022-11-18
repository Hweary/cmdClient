from __future__ import annotations

import asyncio
from typing import Type, Optional, Callable, TYPE_CHECKING

from . import cmdClient
from .Command import Command
from .logger import log

if TYPE_CHECKING:
    from .Context import Context

class Module:
    """
    Data type for bundle of related commands.

    Parameters
    ----------
    name: str
        Name of the module.
    baseCommand: Type[Command]
        Type of command for the module, should inherit `Command`.
    """
    name: str = "Base Module"

    def __init__(self, name: Optional[str] = None, baseCommand: Type[Command] = Command) -> None:
        if name:
            self.name = name

        self.baseCommand: Type[Command] = baseCommand

        self.cmds: list[Command] = []
        self.initialised: bool = False
        self.ready: bool = False
        self.enabled: bool = True

        self.launch_tasks: list[Callable] = []
        self.init_tasks: list[Callable] = []

        cmdClient.cmdClient.modules.append(self)

        log("New module created.", context=self.name)

    def cmd(self, name: str, cmdClass: Optional[Type[Command]] = None, **kwargs) -> Callable:
        """
        Decorator to create a command in this module with the given `name`.
        Creates the command using the provided `cmdClass`.
        Adds the command to the module command list and updates the client cache.
        Transparently passes the rest of the arguments to the `Command` constructor.
        """
        log(f"Adding command '{name}'.", context=self.name)

        cmdClass: Type[Command] = cmdClass or self.baseCommand

        def decorator(func: Callable) -> cmdClass:
            cmd = cmdClass(name, func, self, **kwargs)
            self.cmds.append(cmd)
            cmdClient.cmdClient.update_cmdnames()
            return cmd

        return decorator

    def attach(self, func: Callable) -> None:
        """
        Decorator which attaches the provided function to the current instance.
        """
        setattr(self, func.__name__, func)
        log(f"Attached '{func.__name__}'.", context=self.name)

    def launch_task(self, func: Callable) -> Callable:
        """
        Decorator which adds a launch function to complete during the default launch procedure.
        """
        self.launch_tasks.append(func)
        log(f"Adding launch task '{func.__name__}'.", context=self.name)
        return func

    def init_task(self, func: Callable) -> Callable:
        """
        Decorator which adds an init function to complete during the default initialise procedure.
        """
        self.init_tasks.append(func)
        log(f"Adding initialisation task '{func.__name__}'.", context=self.name)
        return func

    def initialise(self, client: cmdClient.cmdClient) -> None:
        """
        Initialise hook.
        Executed by `client.initialise_modules`,
        or possibly by modules which depend on this one.
        """
        if not self.initialised:
            log("Running initialisation tasks.", context=self.name)

            for task in self.init_tasks:
                log(f"Running initialisation task '{task.__name__}'.", context=self.name)
                task(client)

            self.initialised = True
        else:
            log("Already initialised, skipping initialisation.", context=self.name)

    async def launch(self, client: cmdClient.cmdClient) -> None:
        """
        Launch hook.
        Executed in `client.on_ready`.
        Must set `ready` to `True`, otherwise all commands will hang.
        """
        if not self.ready:
            log("Running launch tasks.", context=self.name)

            for task in self.launch_tasks:
                log("Running launch task '{}'.".format(task.__name__), context=self.name)
                await task(client)

            self.ready = True
        else:
            log("Already launched, skipping launch.", context=self.name)

    async def pre_command(self, ctx: Context) -> None:
        """
        Pre-command hook.
        Executed before a command is run.
        """
        if not self.ready:
            log(f"Waiting for module '{self.name}' to be ready.", context=f"mid:{ctx.msg.id}")
            
            while not self.ready:
                await asyncio.sleep(1)

    async def post_command(self, ctx: Context) -> None:
        """
        Post-command hook.
        Executed after a command is run without exception.
        """
        pass

    async def on_exception(self, ctx: Context, exception: Exception) -> None:
        """
        Exception hook.
        Executed when a command function throws an exception.
        This is executed before "standard" exceptions are caught.
        """
        raise exception
        pass

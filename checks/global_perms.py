from ..Check import check
from ..Context import Context


@check(
    name="IS_OWNER",
    msg="You need to be a bot owner to use this command!"
)
async def is_owner(ctx: Context, *args, **kwargs) -> bool:
    return ctx.author.id in ctx.client.owners


@check(
    name="IN_GUILD",
    msg="You need to be in a guild to use this command!"
)
async def in_guild(ctx: Context, *args, **kwargs) -> bool:
    return ctx.guild is not None

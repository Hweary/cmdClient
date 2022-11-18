import re
from typing import Optional


class SafeCancellation(Exception):
    default_msg: Optional[str] = None

    def __init__(self, msg: Optional[str] = None, details: Optional[str] = None) -> None:
        self.msg: Optional[str] = msg or self.default_msg
        self.details: Optional[str] = details or self.msg


class UserCancelled(SafeCancellation):
    default_msg = "User cancelled the session!"


class ResponseTimedOut(SafeCancellation):
    default_msg = "Session timed out waiting for user response!"


class InvalidContext(Exception):
    """
    Throw when the context available doesn't match the context expected.
    """
    pass


def sterilise_content(content: str) -> str:
    """
    Sterilse everyone and here mentions in the provided string.
    Specifically, adds a zero width space after the `@` symbol.

    Parameters
    ----------
    content: str
        String to sterilise.
    """
    content = content.replace("@everyone", "@​everyone")
    content = content.replace("@here", "@​here")
    asciimsg: str = content.encode('ascii', errors='ignore').decode()
    if "@everyone" in asciimsg or "@here" in asciimsg:
        content = content.replace("@", "@​")

    return content


def flag_parser(args: str, flags: list[str] = []) -> tuple[dict[str, str], str]:
    """
    Parses flags in args from the flags given in flags.
    Flag formats:
        'a': boolean flag, checks if present.
        'a=': Eats one "word".
        'a==': Eats all words up until next flag.
    Returns a tuple (flag_values, remaining).
    flags_present is a dictionary {flag: value} with value being:
        False if a flag isn't present.
        True if a boolean flag is present.
        The value of the flag for a long flag.
    If -- is present in the input as a word, all flags afterwards are ignored.
    TODO: Make this more efficient, then typehint it properly.
    """
    # Split across whitespace, keeping the whitespace
    params: list[str] = re.split(r'(\S+)', args)
    # Final list of command parameters, excluding flags and flag arguments
    final_params: list[str] = []
    # Dictionary of flags and flag values
    final_flags: dict[str, str] = {}
    # Indices in the params list where the flags appear
    indices: list[int] = []
    # The tail of the parameter list, after -- appears
    end_params: list[str] = [] 

    # Handle appearence of the flag terminator
    if "--" in params:
        i = params.index('--')
        end_params = params[i + 1:] if i < len(params) - 1 else []
        params = params[:i]

    # Find the param indicies of the flags
    for flag in flags:
        clean_flag = flag.strip("=")

        if ("-" + clean_flag) in params:
            index = params.index("-" + clean_flag)
        elif ("--" + clean_flag) in params:
            index = params.index("--" + clean_flag)
        elif ("—" + clean_flag) in params:
            index = params.index("—" + clean_flag)
        else:
            final_flags[clean_flag] = False
            continue
        indices.append((index, flag))

    # Sort the indices to ensure we step through the flags in order of appearance
    indices = sorted(indices)

    # Add any parameters that appear before the first flag
    if len(indices) > 0:
        final_params = params[0:indices[0][0]]
    else:
        final_params = params

    # Build the parameters and flag arguments
    for (i, (index, flag)) in enumerate(indices):
        # Get the parameters between this flag and the next, or the end
        if len(params) > index + 1:
            if len(indices) > i + 1:
                flag_params = params[index + 1:indices[i + 1][0]]
            else:
                flag_params = params[index + 1:]
        else:
            flag_params = []

        # Split these into flag arguments and final parameters depending on flag type
        if flag.endswith('=='):
            flag_arg = ''.join(flag_params).strip()
        elif flag.endswith('='):
            # Find the first non-whitespace param, if it exists
            j, arg = next(((j, arg) for j, arg in enumerate(flag_params) if arg.strip()), (len(flag_params), None))

            flag_arg = arg or ''

            # If there are any more params, add them to the final bunch
            if len(flag_params) > j + 1:
                final_params.append(''.join(flag_params[j+1:]).rstrip())
        else:
            flag_arg = True
            final_params.append(''.join(flag_params).rstrip())

        # Set the flag arguments
        final_flags[flag.strip('=')] = flag_arg

    # Add any tail parameters
    final_params += end_params

    # Generate the remaining args
    remaining = ''.join(final_params).strip()
    return (final_flags, remaining)

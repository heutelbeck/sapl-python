import sys
from functools import wraps
from pathlib import Path
from typing import Optional, Iterable, Dict, Union, List

import iniconfig
from _pytest.config.findpaths import get_common_ancestor, get_dirs_from_args
from _pytest.pathlib import absolutepath


class NoHandlerException(Exception):
    """Raised when an object, which is not a ConstraintHandler is added to the ConstraintHandlerService"""
    pass


def double_wrap(f):
    """
    a decorator, allowing the decorator to be used as:
    @decorator(with, arguments, and=kwargs) or @decorator

    :type f: function or method
    :param f: function or method use the decorator
    """

    @wraps(f)
    def new_dec(*args, **kwargs):
        if len(args) == 1 and len(kwargs) == 0 and callable(args[0]):
            # actual decorated fn
            return f(args[0])
        else:
            # decorator arguments
            return lambda real_fn: f(real_fn, *args, **kwargs)

    return new_dec


def get_configuration():
    frame = sys._getframe()
    filename: str
    while frame.f_back:
        frame = frame.f_back
        filename = frame.f_code.co_filename
        if filename.startswith('<frozen'):
            continue
        if filename.endswith(('sapl_util.py', 'sapl_base\\__init__.py')):
            continue
        break

    filename = filename.replace('\\', '::')
    dirs = get_dirs_from_args(filename)

    ancestor = get_common_ancestor(dirs)
    inicfg = _locate_config([ancestor])
    return inicfg


def _locate_config(
        args: Iterable[Path],
) -> Dict[str, Union[str, List[str]]]:
    """Search in the list of arguments for a valid ini-file for sapl,
    and return a cfg-dict."""
    config_names = [
        "sapl.ini",
        "pyproject.toml",
        "sapl.ini",
        "setup.cfg",
    ]
    args = [x for x in args if not str(x).startswith("-")]
    if not args:
        args = [Path.cwd()]
    for arg in args:
        argpath = absolutepath(arg)
        for base in (argpath, *argpath.parents):
            for config_name in config_names:
                p = base / config_name
                if p.is_file():
                    ini_config = _load_config_dict_from_file(p)
                    if ini_config is not None:
                        return ini_config
    return {}


def _load_config_dict_from_file(
        filepath: Path,
) -> Optional[Dict[str, Union[str, List[str]]]]:
    """Load sapl configuration from the given file path, if supported.

    Return None if the file does not contain valid sapl configuration.
    """

    # Configuration from ini files are obtained from the [sapl] section, if present.
    if filepath.suffix == ".ini":
        iniconfig = _parse_ini_config(filepath)

        if "sapl" in iniconfig:
            return dict(iniconfig["sapl"].items())
        else:
            # "pytest.ini" files are always the source of configuration, even if empty.
            if filepath.name == "sapl.ini":
                return {}

    # '.cfg' files are considered if they contain a "[tool:pytest]" section.
    elif filepath.suffix == ".cfg":
        iniconfig = _parse_ini_config(filepath)

        if "tool:sapl" in iniconfig.sections:
            return dict(iniconfig["tool:sapl"].items())


    # '.toml' files are considered if they contain a [tool.sapl.ini_options] table.
    elif filepath.suffix == ".toml":
        import tomli

        toml_text = filepath.read_text(encoding="utf-8")
        try:
            config = tomli.loads(toml_text)
        except tomli.TOMLDecodeError as exc:
            raise Exception

        result = config.get("tool", {}).get("sapl", {}).get("ini_options", None)
        if result is not None:
            return result

    return None


def _parse_ini_config(path: Path) -> iniconfig.IniConfig:
    """Parse the given generic '.ini' file using legacy IniConfig parser, returning
    the parsed object.

    Raise UsageError if the file cannot be parsed.
    """
    try:
        return iniconfig.IniConfig(str(path))
    except iniconfig.ParseError as exc:
        raise Exception


configuration = get_configuration()

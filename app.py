"""Fetches committee data from the Massachusetts Legislature website."""

from argparse import ArgumentParser
from dataclasses import dataclass
from typing import Optional

from dotenv import dotenv_values, load_dotenv

from components.interfaces import Config
from components.options import runner_loop, one_run_mode, scheduled_mode
from components.utils import Cache
from components.auditing import RunLogger


@dataclass
class Mode:
    """Command-line arguments"""

    manual: bool = False
    """Run a loop with verbose prompts and menu options"""
    one_run: bool = False
    """Run through a compliance run end-to-end once"""
    scheduled: Optional[str] = None
    """Time to run scheduled tasks (e.g., '02:00' for daily at 2 AM)
    (Be aware of verification prompts)"""
    check_extensions: bool = False
    """Check for bill extensions (only applies to one-run and scheduled
    modes)"""


def main(cfg: Config, yaml: Cache, mode: Mode) -> None:
    """Entry point for the compliance pipeline"""
    # Wrap execution with audit logging
    with RunLogger(cfg, mode):
        match mode:
            case Mode(manual=True):
                runner_loop(cfg, yaml)
            case Mode(one_run=True, check_extensions=check_ext):
                one_run_mode(cfg, yaml, check_ext)
            case Mode(scheduled=None):
                runner_loop(cfg, yaml)
            case Mode(scheduled=at_time, check_extensions=check_ext):
                scheduled_mode(cfg, yaml, at_time, check_ext)
            case _:
                runner_loop(cfg, yaml)


if __name__ == "__main__":
    load_dotenv()
    for key in (keys := dotenv_values().keys()):
        print(f'Loaded "{key}"!')
    if not keys:
        print("Warning: No keys loaded, uploads will fail.")
    config = Config("config.yaml")
    cache = Cache(auto_save=False)
    parser = ArgumentParser(description="Massachusetts Legislature compliance scraper")
    mode_group = parser.add_mutually_exclusive_group(required=False)
    mode_group.add_argument(
        "-m", "--manual", action="store_true", help=Mode.manual.__doc__
    )
    mode_group.add_argument(
        "-o", "--one-run", action="store_true", help=Mode.one_run.__doc__
    )
    parser.add_argument(
        "-s",
        "--scheduled",
        type=str,
        metavar="TIME",
        help="Time to run scheduled tasks (e.g., '02:00' for daily at 2 AM). "
        "Required when using --scheduled.",
    )
    parser.add_argument(
        "--check-extensions",
        action="store_true",
        help="Check for bill extensions (only applies to one-run and "
        "scheduled modes)",
    )
    args = parser.parse_args()
    run_mode = Mode(**vars(args))
    main(config, cache, run_mode)

"""Fetches committee data from the Massachusetts Legislature website.
"""

from argparse import ArgumentParser
from dataclasses import dataclass

from components.interfaces import Config
from components.options import runner_loop, one_run_mode, scheduled_mode
from components.utils import Cache


@dataclass
class Mode:
    """Command-line arguments"""

    manual: bool = False
    """Run a loop with verbose prompts and menu options"""
    one_run: bool = False
    """Run through a compliance run end-to-end once"""
    check_extensions: bool = False
    """Check for bill extensions (only applies to one-run and scheduled
    modes)"""
    scheduled: bool = False
    """Run on a schedule (be aware of verification prompts)"""
    at: str | None = None
    """Time to run scheduled tasks (e.g., '02:00' for daily at 2 AM)"""


def main(cfg: Config, yaml: Cache, mode: Mode) -> None:
    """Entry point for the compliance pipeline"""
    match mode:
        case Mode(manual=True):
            runner_loop(cfg, yaml)
        case Mode(one_run=True, check_extensions=check_ext):
            one_run_mode(cfg, yaml, check_ext)
        case Mode(scheduled=True, at=at_time, check_extensions=check_ext):
            if not at_time:
                raise ValueError(
                    "Scheduled mode requires --at argument "
                    "(e.g., --at '02:00')"
                )
            scheduled_mode(cfg, yaml, at_time, check_ext)
        case _:
            runner_loop(cfg, yaml)


if __name__ == "__main__":
    config = Config("config.yaml")
    cache = Cache(auto_save=False)
    parser = ArgumentParser(
        description="Massachusetts Legislature compliance scraper"
    )
    mode_group = parser.add_mutually_exclusive_group(required=False)
    mode_group.add_argument(
        "-m", "--manual", action="store_true", help=Mode.manual.__doc__
    )
    mode_group.add_argument(
        "-o", "--one-run", action="store_true", help=Mode.one_run.__doc__
    )
    parser.add_argument(
        "--check-extensions", action="store_true",
        help="Check for bill extensions (only applies to one-run and "
             "scheduled modes)"
    )
    mode_group.add_argument(
        "-s", "--scheduled", action="store_true", help=Mode.scheduled.__doc__
    )
    parser.add_argument(
        "--at", type=str, metavar="TIME",
        help="Time to run scheduled tasks (e.g., '02:00' for daily at 2 AM). "
             "Required when using --scheduled."
    )
    args = parser.parse_args()
    run_mode = Mode(**vars(args))
    main(config, cache, run_mode)

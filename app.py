"""Fetches committee data from the Massachusetts Legislature website.
"""

from argparse import ArgumentParser
from dataclasses import dataclass

from components.interfaces import Config
from components.options import runner_loop
from components.utils import Cache


@dataclass
class Mode:
    """Command-line arguments"""

    manual: bool = False
    """Run a loop with verbose prompts and menu options"""
    one_run: bool = False
    """Run through a compliance run end-to-end once"""
    scheduled: bool = False
    """Run on a schedule (be aware of verification prompts)"""


def main(cfg: Config, yaml: Cache, mode: Mode) -> None:
    """Entry point for the compliance pipeline"""
    match mode:
        case Mode(manual=True):
            runner_loop(cfg, yaml)
        case Mode(one_run=True):
            raise NotImplementedError("One-run mode not implemented")
        case Mode(scheduled=True):
            raise NotImplementedError("Scheduled mode not implemented")
        case _:
            raise ValueError("Invalid run mode")


if __name__ == "__main__":
    config = Config("config.yaml")
    cache = Cache(auto_save=False)
    parser = ArgumentParser(
        description="Massachusetts Legislature compliance scraper"
    )
    parser.add_argument(
        "-m", "--manual", action="store_true", help=Mode.manual.__doc__
    )
    parser.add_argument(
        "-o", "--one-run", action="store_true", help=Mode.one_run.__doc__
    )
    parser.add_argument(
        "-s", "--scheduled", action="store_true", help=Mode.scheduled.__doc__
    )
    args = parser.parse_args()
    run_mode = Mode(**vars(args))
    main(config, cache, run_mode)

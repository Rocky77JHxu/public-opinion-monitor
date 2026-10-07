from __future__ import annotations

import argparse

from opinion_monitor import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="opinion-monitor",
        description="舆情采集与研判流水线",
    )
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def main() -> None:
    build_parser().parse_args()


if __name__ == "__main__":
    main()

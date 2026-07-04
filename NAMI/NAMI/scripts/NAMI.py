from __future__ import annotations

import cmd
import logging
import os
import sys
from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path


def _bootstrap_paths() -> Path:
    """
    Make the repository root and src/ importable when run from scripts/.
    """
    here = Path(__file__).resolve()
    repo_root = here.parent.parent if here.parent.name == "scripts" else Path.cwd().resolve()
    src = repo_root / "src"
    for p in (str(repo_root), str(src)):
        if p not in sys.path:
            sys.path.insert(0, p)
    os.chdir(repo_root)
    return repo_root


REPO_ROOT = _bootstrap_paths()

from NAMI_shell_commands import (
    NAMICoreCommands,   NAMISetupCommands,     NAMICrawlCommands, NAMIAnalysisCommands, NAMIExplorerCommands,
    NAMIVisionCommands, NAMIRawModuleCommands, NAMIGraphCommands, NAMIScopeCommands,    NAMITalkCommands,
    NAMIVizCommands,    NAMIAcousticCommands
)
from nami_shell.common import complete_command_options

HISTORY_FILE = os.path.join(os.path.expanduser("~"), ".nami_history")


logger = logging.getLogger("NAMI")
logger.setLevel(logging.INFO)
try:
    Path("logs").mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    file_handler = logging.FileHandler(f"logs/nami_{timestamp}.log", mode="w", encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.ERROR)
    console_formatter = logging.Formatter("%(levelname)s - %(message)s")
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
except Exception as e:
    print(f"Could not initialize logging: {e}.")
    raise SystemExit(1)


class NAMIShell(
    NAMICoreCommands,
    NAMISetupCommands,
    NAMICrawlCommands,
    NAMIAnalysisCommands,
    NAMIExplorerCommands,
    NAMIVisionCommands,
    NAMIRawModuleCommands,
    NAMIGraphCommands,
    NAMIScopeCommands,
    NAMITalkCommands,
    NAMIVizCommands,
    NAMIAcousticCommands,
    cmd.Cmd,
):
    logo = """
******************************************
*              Welcome  to               *
******************************************
*                                        *
*  ▄▄▄   ▄▄     ▄▄     ▄▄▄  ▄▄▄   ▄▄▄▄▄▄ *
*  ███   ██    ████    ███  ███   ▀▀██▀▀ *
*  ██▀█  ██    ████    ████████     ██   *
*  ██ ██ ██   ██  ██   ██ ██ ██     ██   *
*  ██  █▄██   ██████   ██ ▀▀ ██     ██   *
*  ██   ███  ▄██  ██▄  ██    ██   ▄▄██▄▄ *
*  ▀▀   ▀▀▀  ▀▀    ▀▀  ▀▀    ▀▀   ▀▀▀▀▀▀ *
*                                        *
******************************************
*             🌊   波   なみ              *
******************************************
* Network Analysis of Music on Instagram *
* Riding the wave, absolutely surreel :) *
******************************************
"""

    intro = logo + """
Enter 'help' or '?' to see the command list; 'help [command]' for more information on a specific command.
Enter 'exit' or 'quit' to end NAMI.
"""

    prompt = "NAMI> "

    def __init__(self, db_path: str = "data/corpus.db"):
        """
        Set up the shell with the database to work against.
        """
        super().__init__()
        self.repo_root = REPO_ROOT
        self.db_path = db_path

    def cmdloop(self, intro=None):
        """
        Show the intro and current status, then start the interactive prompt.
        """
        if intro is None:
            intro = self.intro
        print(intro)
        try:
            self.do_status(f"--db {self.db_path}")
        except Exception:
            pass
        print()
        super().cmdloop(intro="")

    def onecmd(self, line):
        """
        Run a command, turning argument-validation errors into a clean message.

        Commands raise ValueError from the parsing layer (unknown option, bad
        value) before their own try/except runs.
        """
        try:
            return super().onecmd(line)
        except ValueError as e:
            print(f"Error: {e}")
            return False

    def preloop(self):
        """
        Load command history and widen completion word boundaries.
        """
        try:
            import readline
        except ImportError:
            return
        readline.set_completer_delims(" \t\n")
        try:
            readline.read_history_file(HISTORY_FILE)
        except (OSError, FileNotFoundError):
            pass
        readline.set_history_length(1000)

    def postloop(self):
        try:
            import readline
            readline.write_history_file(HISTORY_FILE)
        except Exception:
            pass

    def completedefault(self, text, line, begidx, endidx):
        """
        Tab-complete a command's options and their values.
        """
        try:
            parts = line.split()
            command = parts[0] if parts else ""
            return complete_command_options(command, text, line, begidx)
        except Exception:
            return []

    def emptyline(self):
        pass

    def precmd(self, line):
        """
        Treat 'quit' or 'q' as the exit command.
        """
        if line.strip().lower() in {"quit", "q"}:
            return "exit"
        return line

    def default(self, line):
        print(f"Unknown command '{line}'. Enter 'help' or '?' for a list of available commands.")


def parse_arguments():
    parser = ArgumentParser(description="NAMI interactive shell")
    parser.add_argument("-d", "--db", default="data/corpus.db", help="Path to SQLite database")
    parser.add_argument("-c", "--command", help="Run one shell command non-interactively, then exit")
    return parser.parse_args()


def main():
    from dotenv import load_dotenv
    load_dotenv()
    args = parse_arguments()
    shell = NAMIShell(db_path=args.db)
    if args.command:
        shell.onecmd(args.command)
        return
    try:
        shell.cmdloop()
    except KeyboardInterrupt:
        print("\nProgram terminated by user input. Goodbye!")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}.")


if __name__ == "__main__":
    main()

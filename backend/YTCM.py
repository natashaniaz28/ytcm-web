import cmd, logging, os, sys

from argparse                   import ArgumentParser
from datetime                   import datetime

from YTCM_config                import EXCLUDED_TERMS, PRIMARY_SEARCH_TERMS, SECONDARY_SEARCH_TERMS, SEARCH_YEAR
from YTCM_logging_config        import logger
from YTCM_helper_utils          import check_pending_downloads
from YTCM_shell_commands        import (YTCMCoreCommands, YTCMDownloadCommands, YTCMEnrichmentCommands,
                                        YTCMExportCommands, YTCMFilterCommands, YTCMSearchCommands,
                                        YTCMTubeConnectCommands, YTCMTubeGraphCommands, YTCMTubeScopeCommands,
                                        YTCMTubeTalkCommands)


try:
    os.makedirs("logs", exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    file_handler = logging.FileHandler(f"logs/ytcm_{timestamp}.log", mode="w")
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
    exit(1)


class YTCMShell(YTCMCoreCommands, YTCMDownloadCommands, YTCMEnrichmentCommands, YTCMExportCommands, YTCMFilterCommands,
                YTCMSearchCommands, YTCMTubeConnectCommands, YTCMTubeGraphCommands, YTCMTubeScopeCommands,
                YTCMTubeTalkCommands, cmd.Cmd):
    logo = """
┌────────────────────────────────────────┐
│  ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓  │
│  ┃   __     _______ _____ __  __    ┃  │
│  ┃   ╲ ╲   ╱ ╱_   _│ ____│  ╲╱  │   ┃  │
│  ┃    ╲ ╲_╱ ╱  │ │ │ │   │ ╲  ╱ │   ┃  │
│  ┃     ╲   ╱   │ │ │ │___│ │╲╱│ │   ┃  │
│  ┃      │ │    │_│ │_____│_│  │_│   ┃  │
│  ┃      │_│ YOUTUBE COMMENT MINER   ┃  │
│  ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛  │
└────────────────────────────────────────┘
"""

    intro = logo + """
Enter 'help' or '?' to see the command list.
Enter 'help [command]' for more information on a specific command.
Enter 'howto' for a description of the recommended workflow.
Enter 'exit' or 'quit' to terminate the program.
"""

    prompt = "YTCM> "

    def __init__(self):
        super().__init__()
        self.youtube = None
        self.api_key = None

        # Init search parameters with values from config
        self.primary_terms = PRIMARY_SEARCH_TERMS if PRIMARY_SEARCH_TERMS else []
        self.secondary_terms = SECONDARY_SEARCH_TERMS
        self.excluded_terms = EXCLUDED_TERMS
        self.search_year = SEARCH_YEAR
        self.video_ids = []
        self.video_ids_file = "video_ids.txt"
        self.filtered_list = None
        self.last_filter = None


    def cmdloop(self, intro=None):
        """
        Check for pending downloads and show that once after startup.
        """

        if intro is None:
            intro = self.intro
        print(intro)

        num = check_pending_downloads(self.video_ids_file)
        if num > 0:
            print(f"There are {num} video IDs pending download in '{self.video_ids_file}'!\n")

        super().cmdloop(intro="")                       # switch off the intro message, but only to "" instead of None


    def emptyline(self):
        pass


    def precmd(self, line):
        if line.strip().lower() in ["quit", "q"]:
            return "exit"
        return line


    def default(self, line):
        """
        This function is called when the input line is not recognized.
        """

        print(f"Unknown command '{line}'. Enter 'help' or '?' for a list of available commands.")


def parse_arguments():
    """
    Process command line arguments.
    """

    parser = ArgumentParser(description="YouTube Comment Miner")
    parser.add_argument("-i", "--interactive", action="store_true",
                      help="Start interactive shell")
    parser.add_argument("-s", "--search", nargs="+", metavar="TERM",
                      help="Primary search terms")
    parser.add_argument("-y", "--year", type=int,
                      help="Search year (2005-current year)")
    parser.add_argument("-o", "--output", metavar="FILE",
                      help="Output file for video IDs")

    return parser.parse_args()


def main():
    args = parse_arguments()
    
    if args.interactive or (not args.search and not args.year):
        try:
            YTCMShell().cmdloop()
        except KeyboardInterrupt:
            print("\nProgram terminated by user input. Goodbye!.")
            return
        except Exception as e:
            logger.error(f"An unexpected error occurred: {e}.")
            return

    else:                       # non-interactive mode
        shell = YTCMShell()
        
        try:
            if args.search:
                shell.do_primary(" ".join(args.search))

            if args.year:
                shell.do_year(str(args.year))

            if args.output:
                shell.video_ids_file = args.output
            
            print("\n--- Starting Pre-defined Workflow ---\n")
            shell.do_workflow("")

            return
        
        except KeyboardInterrupt:
            print("\nProgram terminated by user input. Goodbye!")
            return

        except Exception as e:
            logger.error(f"\nAn unexpected error occurred: {e}. Goodbye!")
            return


if __name__ == "__main__":
    main()
    sys.exit()

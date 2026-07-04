from __future__ import annotations

from .common import *


class NAMIRawModuleCommands:
    def do_runmodule(self, arg):
        """
        Run an arbitrary nami_code module as __main__.
        Syntax: runmodule nami_code.analysis.analyse
        """
        module = arg.strip()
        if not module:
            print("Syntax: runmodule nami_code.some.module")
            return
        try:
            runpy.run_module(module, run_name="__main__")
        except Exception as e:
            logger.error(f"Error running module {module}: {e}.")

    def do_runscript(self, arg):
        """
        Run a script path from the repository.
        Syntax: runscript scripts/analyse.py
        """
        script = arg.strip()
        if not script:
            print("Syntax: runscript scripts/analyse.py")
            return
        try:
            runpy.run_path(script, run_name="__main__")
        except Exception as e:
            logger.error(f"Error running script {script}: {e}.")


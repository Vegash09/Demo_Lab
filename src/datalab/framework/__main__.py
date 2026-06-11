"""``python -m datalab.framework <config-dir> [...]`` — validate domain configs.

Thin wrapper around :func:`datalab.framework.loader.main` (the same loader
pytest, ``make validate-configs`` and the pipeline import run). Living in
``__main__.py`` keeps the canonical CLI free of the runpy double-import
RuntimeWarning that ``python -m datalab.framework.loader`` emits.
"""

import sys

from datalab.framework.loader import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

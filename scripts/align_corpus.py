"""Word-align the Old Irish/English bitext with fast_align
(https://github.com/clab/fast_align).

fast_align parallelizes its EM training across all available cores by
default, and floating-point summation order (and therefore the final
Viterbi alignment in close calls) depends on thread scheduling - so the
default multi-threaded run is not reproducible run-to-run. This script
forces OMP_NUM_THREADS=1 so the output is deterministic given the same
fast_align build and input.

fast_align's own default flags (i.e. none of -d/-o/-v) are used, since
they were found to reproduce the existing data/sga_incomplete.align most
closely - the standard "-d -o -v" symmetrization recipe does not match
this project's reference alignment.
"""

import argparse
import os
import shutil
import subprocess

DEFAULT_INPUT = "data/sga_incomplete.en-ga"
DEFAULT_OUTPUT = "data/sga_incomplete.align"
DEFAULT_FAST_ALIGN_BIN = os.path.expanduser("~/external/fast_align/build/fast_align")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=DEFAULT_INPUT, help="fast_align bitext (X ||| Y per line)")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Alignment destination")
    parser.add_argument(
        "--fast-align-bin",
        default=DEFAULT_FAST_ALIGN_BIN,
        help="Path to the fast_align binary",
    )
    args = parser.parse_args()

    fast_align_bin = shutil.which(args.fast_align_bin) or args.fast_align_bin
    if not os.path.isfile(fast_align_bin):
        raise SystemExit(f"fast_align binary not found at {fast_align_bin}")

    env = {**os.environ, "OMP_NUM_THREADS": "1"}
    with open(args.output, "w") as out:
        subprocess.run(
            [fast_align_bin, "-i", args.input],
            stdout=out,
            check=True,
            env=env,
        )

    print(f"Wrote alignments to {args.output}")


if __name__ == "__main__":
    main()

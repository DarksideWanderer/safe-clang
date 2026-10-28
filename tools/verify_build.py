#!/usr/bin/env python3
"""Verify a module build's recorded source, tool and artifact hashes."""
import argparse
from build_artifacts import verify

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output')
    args = parser.parse_args()
    try:
        info = verify(args.output)
    except (ValueError, OSError, KeyError) as error:
        parser.exit(1, str(error)+'\n')
    print(f'Verified {len(info["artifacts"])} artifacts and {len(info["inputs"])} inputs')

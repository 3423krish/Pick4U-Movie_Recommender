import argparse
import os
from pathlib import Path

import pandas as pd

from backend.model_loader import DEFAULT_CATALOGUE_PATH, KEEP_COLUMNS, read_table


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", default=str(DEFAULT_CATALOGUE_PATH))
    parser.add_argument("--format", choices=("csv.gz", "csv"), default="csv.gz")
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--force", action="store_true", help="Replace an existing output file.")
    args = parser.parse_args(argv)

    source = Path(args.src).expanduser().resolve()
    if not source.is_file():
        parser.error(f"Source catalogue does not exist: {source}")
    frame = read_table(source)
    frame = frame[[column for column in KEEP_COLUMNS if column in frame.columns]]
    output_dir = Path(args.out_dir).expanduser() if args.out_dir else source.parent
    if not output_dir.is_absolute():
        output_dir = Path.cwd() / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"movies_model_ready.{args.format}"
    if output.resolve() == source:
        parser.error("Output must not overwrite the source catalogue.")
    if output.exists() and not args.force:
        parser.error(f"Output already exists; pass --force to replace it: {output}")

    temporary = output.with_name(f".{output.name}.tmp-{os.getpid()}")
    try:
        compression = {"method": "gzip", "compresslevel": 6} if args.format == "csv.gz" else None
        frame.to_csv(temporary, index=False, compression=compression)
        round_trip = pd.read_csv(temporary, low_memory=False, compression="gzip" if args.format == "csv.gz" else None)
        pd.testing.assert_frame_equal(frame, round_trip, check_dtype=False)
        for column in frame.columns:
            if frame[column].notna().any() and frame[column].dtype != round_trip[column].dtype:
                raise ValueError(
                    f"Column '{column}' changed type during CSV round-trip: "
                    f"{frame[column].dtype} -> {round_trip[column].dtype}"
                )
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()

    print(
        f"Verified {len(frame):,} rows and {len(frame.columns)} columns. "
        f"{source.stat().st_size / 1_000_000:.2f} MB -> "
        f"{output.stat().st_size / 1_000_000:.2f} MB ({output})"
    )


if __name__ == "__main__":
    main()

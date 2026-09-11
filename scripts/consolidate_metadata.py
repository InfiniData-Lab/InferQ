import pandas as pd
import math
from pathlib import Path
from tqdm import tqdm
import io

def get_approx_rows_for_size(df, target_bytes=40 * 1024 * 1024, sample_size=1000):
    """
    Estimates the number of rows that result in a parquet file of roughly target_bytes.
    """
    if len(df) == 0:
        return 0
    
    # Take a representative sample. If dataset is smaller than sample, take all.
    actual_sample_size = min(len(df), sample_size)
    sample = df.iloc[:actual_sample_size]
    
    buffer = io.BytesIO()
    # Use default compression (snappy usually) to match output
    sample.to_parquet(buffer, index=False) 
    size = buffer.tell()
    
    bytes_per_row = size / actual_sample_size
    target_rows = int(target_bytes / bytes_per_row)
    return target_rows

def consolidate_metadata(source_dir, output_dir, target_size_mb=40):
    source_path = Path(source_dir)
    output_path = Path(output_dir)
    
    if not source_path.exists():
        print(f"Source directory {source_path} does not exist.")
        return

    # Check/Create output directory
    output_path.mkdir(parents=True, exist_ok=True)
    print(f"Source: {source_path}")
    print(f"Destination: {output_path}")

    print("Scanning for parquet files...")
    files = sorted(list(source_path.glob("*.parquet")))
    
    if not files:
        print("No parquet files found.")
        return
    
    print(f"Found {len(files)} files. Reading...")

    # Read all files
    dfs = []
    # Use list collection and concat once for performance (faster than appending to DF)
    for f in tqdm(files, desc="Loading files"):
        try:
            dfs.append(pd.read_parquet(f))
        except Exception as e:
            print(f"Error reading {f}: {e}")
    
    if not dfs:
        return

    print("Concatenating DataFrames...")
    full_df = pd.concat(dfs, ignore_index=True)
    total_rows = len(full_df)
    print(f"Total rows: {total_rows}")

    # Estimate rows per file
    target_bytes = target_size_mb * 1024 * 1024
    rows_per_file = get_approx_rows_for_size(full_df, target_bytes=target_bytes)
    print(f"Estimated rows per {target_size_mb}MB file: {rows_per_file}")

    if rows_per_file == 0:
        print("Rows per file is 0, checking logic.")
        rows_per_file = 1000 # Fallback

    # Split and save
    num_chunks = math.ceil(total_rows / rows_per_file)
    print(f"Splitting into {num_chunks} files...")

    for i in tqdm(range(num_chunks), desc="Saving chunks"):
        start_idx = i * rows_per_file
        end_idx = min((i + 1) * rows_per_file, total_rows)
        chunk = full_df.iloc[start_idx:end_idx]
        
        output_file = output_path / f"metadata_part_{i+1:03d}.parquet"
        chunk.to_parquet(output_file, index=False)
        
        # Optional: Print actual size of first chunk to verify
        if i == 0:
             size_mb = output_file.stat().st_size / (1024 * 1024)
             print(f"First chunk size: {size_mb:.2f} MB")

    print("Done.")

if __name__ == "__main__":
    # Define paths relative to project root
    # script is in scripts/
    # If run from root, we can detect cwd
    cwd = Path.cwd()
    project_root = None
    
    # Try to find project root by looking for known files
    if (cwd / "data").exists():
        project_root = cwd
    else:
        # Fallback to script location
        project_root = Path(__file__).resolve().parent.parent
    
    source = project_root / "data" / "fetched_circuit_metadata"
    dest = project_root / "data" / "metadata"
    
    consolidate_metadata(source, dest, target_size_mb=40)

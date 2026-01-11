import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np

def get_time_columns(df: pd.DataFrame) -> list:
    """Returns a list of columns in the DataFrame that are of datetime type."""
    return [col for col in df.columns if '_execution_time' in col.lower()]


def plot_execution_times(df: pd.DataFrame, time_columns: list):
    """Plots execution times from the specified columns in the DataFrame."""
    plt.figure(figsize=(12, 6))
    for col in time_columns:
        sns.lineplot(data=df, x=df.index, y=col, label=col)
    plt.xlabel('Index')
    plt.ylabel('Execution Time')
    plt.title('Execution Times Over Entries')
    plt.legend()
    plt.show()

def calculate_average_times(df: pd.DataFrame, time_columns: list) -> pd.Series:
    """Calculates the average execution time for each specified column."""
    return df[time_columns].mean()

def plot_entropy_bin_times(data: pd.DataFrame, time_columns: list, bins : int = 10):
    """Plots entropy bin times if the relevant columns exist in the DataFrame."""
    # Let us see the timings for different algorithms for circuits with specific properties
    # and see if there are any trends or patterns regarding entrpopy. Again let us only take rows which have entropy values, not None or NaN
    # let us plot how many times each algorithm was the fastest for circuits with different entropy ranges
    entropy_data = data.dropna(subset=['statevector_saved_entropy'])
    entropy_bins = np.linspace(entropy_data['statevector_saved_entropy'].min(), entropy_data['statevector_saved_entropy'].max(), bins)
    entropy_data['entropy_bin'] = pd.cut(entropy_data['statevector_saved_entropy'], bins=entropy_bins)
    fastest_counts = {col: [] for col in time_columns}
    bin_labels = []
    for bin_range in entropy_data['entropy_bin'].cat.categories:
        bin_subset = entropy_data[entropy_data['entropy_bin'] == bin_range]
        if bin_subset.empty:
            continue
        bin_labels.append(f"{bin_range.left:.2f}-{bin_range.right:.2f}")
        fastest_algo = bin_subset[time_columns].idxmin(axis=1)
        for col in time_columns:
            count = (fastest_algo == col).sum()
            fastest_counts[col].append(count)
    plt.figure(figsize=(10, 6))
    bottom = np.zeros(len(bin_labels))
    for col in time_columns:
        plt.bar(bin_labels, fastest_counts[col], bottom=bottom, label=col)
        bottom += np.array(fastest_counts[col])
    plt.title('Number of Times Each Algorithm was Fastest vs Entropy Bins')
    plt.xlabel('Entropy Bins')
    plt.ylabel('Number of Times Fastest')
    # puting the legend outside the plot
    plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.show()
    return bin_labels, fastest_counts

def plot_bin_times_percentage(bin_labels, fastest_counts, time_columns: list = None, label = ""):
    # Plot the percentage of times each algorithm was the fastest for circuits with different entropy ranges
    plt.figure(figsize=(10, 6))
    bottom = np.zeros(len(bin_labels))
    # stack counts to compute totals per bin
    stacked = np.vstack([np.array(fastest_counts[col]) for col in time_columns])
    total_counts = np.sum(stacked, axis=0)
    # avoid division by zero
    total_counts_safe = np.where(total_counts == 0, 1, total_counts)
    for i, col in enumerate(time_columns):
        percentages = np.array(fastest_counts[col]) / total_counts_safe * 100
        plt.bar(bin_labels, percentages, bottom=bottom, label=col)
        bottom += percentages
    plt.title(f'Percentage of Times Each Algorithm was Fastest vs {label} Bins')
    plt.xlabel(f'{label} Bins')
    plt.ylabel('Percentage of Times Fastest')
    plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.show()

# Let us have these functions with sparsity too:
def plot_sparsity_bin_times(data: pd.DataFrame, time_columns: list, bins : int = 10):
    """Plots sparsity bin times if the relevant columns exist in the DataFrame."""
    # Let us see the timings for different algorithms for circuits with specific properties
    # and see if there are any trends or patterns regarding sparsity. Again let us only take rows which have sparsity values, not None or NaN
    # let us plot how many times each algorithm was the fastest for circuits with different sparsity ranges
    sparsity_data = data.dropna(subset=['statevector_saved_sparsity'])
    sparsity_bins = np.linspace(sparsity_data['statevector_saved_sparsity'].min(), sparsity_data['statevector_saved_sparsity'].max(), bins)
    sparsity_data['sparsity_bin'] = pd.cut(sparsity_data['statevector_saved_sparsity'], bins=sparsity_bins)
    fastest_counts = {col: [] for col in time_columns}
    bin_labels = []
    for bin_range in sparsity_data['sparsity_bin'].cat.categories:
        bin_subset = sparsity_data[sparsity_data['sparsity_bin'] == bin_range]
        if bin_subset.empty:
            continue
        bin_labels.append(f"{bin_range.left:.2f}-{bin_range.right:.2f}")
        fastest_algo = bin_subset[time_columns].idxmin(axis=1)
        for col in time_columns:
            count = (fastest_algo == col).sum()
            fastest_counts[col].append(count)
    plt.figure(figsize=(10, 6))
    bottom = np.zeros(len(bin_labels))
    for col in time_columns:
        plt.bar(bin_labels, fastest_counts[col], bottom=bottom, label=col)
        bottom += np.array(fastest_counts[col])
    plt.title('Number of Times Each Algorithm was Fastest vs sparsity Bins')
    plt.xlabel('sparsity Bins')
    plt.ylabel('Number of Times Fastest')
    # puting the legend outside the plot
    plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.show()
    return bin_labels, fastest_counts

def make_histogram_grid(data : pd.DataFrame, features_list : list, title_prefix : str):
    n = len(features_list)
    if n == 0:
        print(f"No numeric features to plot histograms for {title_prefix}.")
        return
    ncols = int(np.ceil(np.sqrt(n)))
    nrows = int(np.ceil(n / ncols))
    figsize = (4 * ncols, 3 * nrows)
    fig, axes = plt.subplots(nrows, ncols, figsize=figsize, squeeze=False)
    axes_flat = axes.flatten()
    for i, feature in enumerate(features_list):
        ax = axes_flat[i]
        sns.histplot(data=data, x=feature, bins=20, kde=False, ax=ax)
        ax.set_title(f"Histogram of {feature}")
        ax.set_xlabel(feature)
        ax.set_ylabel("Count")
    # hide any unused axes
    for j in range(n, len(axes_flat)):
        axes_flat[j].set_visible(False)
    plt.tight_layout()
    plt.show()

def plot_best_method_hists(METHODS, FEATURES, df_clean):
    
    n_rows = len(FEATURES)
    n_cols = len(METHODS)

    fig, axes = plt.subplots(
        n_rows, n_cols,
        figsize=(4 * n_cols, 3 * n_rows),
        sharex=False,
        sharey=False
    )

    for i, feature in enumerate(FEATURES):
        for j, method in enumerate(METHODS):
            ax = axes[i, j]

            subset = df_clean[df_clean["best_method"] == method]
            col = feature

            if col in subset.columns and not subset.empty:
                data = subset[col].dropna()

                if len(data) > 0:
                    sns.histplot(
                        data,
                        bins=30,
                        kde=True,
                        ax=ax
                    )

            if i == 0:
                ax.set_title(method, fontsize=10)

            if j == 0:
                ax.set_ylabel(feature, fontsize=10)
            else:
                ax.set_ylabel("")

            ax.set_xlabel("")

    plt.tight_layout()
    plt.show()

def PlotHistPercentBest(df_clean, FEATURES, METHODS):
    import numpy as np
    import pandas as pd
    import matplotlib.pyplot as plt
    import math

    features = FEATURES
    classes = df_clean["best_method"].unique()

    n_cols = 4
    n_rows = math.ceil(len(features) / n_cols)

    fig, axes = plt.subplots(
        n_rows,
        n_cols,
        figsize=(5 * n_cols, 3.8 * n_rows),
        squeeze=False
    )

    for ax, feat in zip(axes.flat, features):
        data = df_clean[[feat, "best_method"]].dropna()

        # --- Bin feature (use quantiles for stability) ---
        data["bin"] = pd.cut(data[feat], bins=5)

        # --- Counts per bin & class ---
        bin_class_counts = (
            data
            .groupby(["bin", "best_method"])
            .size()
            .unstack(fill_value=0)
        )

        # --- Percentages per bin ---
        bin_percentages = bin_class_counts.div(
            bin_class_counts.sum(axis=1),
            axis=0
        )

        x = np.arange(len(bin_percentages))
        bottom = np.zeros(len(bin_percentages))

        # --- Plot stacked bars ---
        for cls in bin_percentages.columns:
            ax.bar(
                x,
                bin_percentages[cls],
                bottom=bottom,
                label=cls
            )
            bottom += bin_percentages[cls].values

        # --- Annotate bin counts ---
        bin_totals = bin_class_counts.sum(axis=1).values
        for i, total in enumerate(bin_totals):
            ax.text(
                i,
                0.99,
                f"n={int(total)}",
                ha="center",
                va="top",
                fontsize=8,
                rotation=90,
                color="black"
            )


        ax.set_title(feat)
        ax.set_ylim(0, 1.1)
        ax.set_yticks([0, 0.5, 1])
        ax.set_yticklabels(["0%", "50%", "100%"])
        ax.set_xticks([])

    # Remove empty subplots
    for ax in axes.flat[len(features):]:
        ax.remove()

    # Single legend
    handles, labels = axes.flat[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=len(labels))

    plt.tight_layout(rect=[0, 0, 1, 0.95])
    plt.show()

def PlotHeatMapAvg(FEATURES, METHODS, df_clean):
    import numpy as np
    import pandas as pd
    import matplotlib.pyplot as plt
    import seaborn as sns

    matrix = pd.DataFrame(index=FEATURES, columns=METHODS, dtype=float)

    for method in METHODS:
        subset = df_clean[df_clean["best_method"] == method]
        for feature in FEATURES:
            print(feature)
            mx, mi = subset[feature].max(),subset[feature].min()
            if mx - mi > 0:
                matrix.loc[feature, method] = (subset[feature].mean()-mi)/(mx-mi)
            else:
                matrix.loc[feature, method] = 0.0

    # --- Min–max normalize per feature (row-wise) ---
    matrix_norm = matrix.copy()

    # --- Plot heatmap ---
    plt.figure(figsize=(11, 6))
    sns.heatmap(
        matrix_norm,
        cmap="viridis",
        annot=True,
        fmt=".2f",
        linewidths=0.5
    )

    plt.title("Relative Method Performance (Conditioned on Best Method)")
    plt.xlabel("Method")
    plt.ylabel("Feature")
    plt.tight_layout()
    plt.show()
    
def load_all_parquet_files(fetched_data_dir: str = "../fetched_data") -> pd.DataFrame:
    """
    Load and combine all parquet files from the fetched_data directory into a single DataFrame.
    
    Parameters:
    -----------
    fetched_data_dir : str, optional
        Path to the directory containing parquet files. Default is "../fetched_data"
        
    Returns:
    --------
    pd.DataFrame
        Combined DataFrame with all data from parquet files
    """
    import os
    import glob
    
    # Get the full path
    if not os.path.isabs(fetched_data_dir):
        # If relative path, make it relative to the analysis directory
        current_dir = os.path.dirname(os.path.abspath(__file__))
        fetched_data_dir = os.path.join(current_dir, fetched_data_dir)
    
    # Find all parquet files
    parquet_files = glob.glob(os.path.join(fetched_data_dir, "*.parquet"))
    
    if not parquet_files:
        raise FileNotFoundError(f"No parquet files found in {fetched_data_dir}")
    
    print(f"Found {len(parquet_files)} parquet files to load...")
    
    # Load and combine all parquet files
    dfs = []
    for i, file_path in enumerate(sorted(parquet_files)):
        if (i + 1) % 50 == 0:
            print(f"Loading file {i + 1}/{len(parquet_files)}...")
        df = pd.read_parquet(file_path)
        dfs.append(df)
    
    # Concatenate all dataframes
    combined_df = pd.concat(dfs, ignore_index=True)
    
    print(f"Successfully loaded {len(combined_df)} rows from {len(parquet_files)} files")
    print(f"DataFrame shape: {combined_df.shape}")
    
    return combined_df

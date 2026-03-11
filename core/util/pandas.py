import pandas as pd


def memory_usage(obj: pd.DataFrame | pd.Series, deep: bool = True) -> float:
    """
    Returns the memory usage of a pandas DataFrame or Series in bytes.

    Args:
        obj (pd.DataFrame or pd.Series): The object to check.
        deep (bool): Whether to introspect the data deeply (default: True).

    Returns:
        int: Memory usage in bytes.
    """
    if isinstance(obj, pd.DataFrame):
        return obj.memory_usage(deep=deep).sum() / 1024**2  # Convert to MB
    elif isinstance(obj, pd.Series):
        return obj.memory_usage(deep=deep) / 1024**2  # Convert to MB
    else:
        raise TypeError("Input must be a pandas DataFrame or Series.")

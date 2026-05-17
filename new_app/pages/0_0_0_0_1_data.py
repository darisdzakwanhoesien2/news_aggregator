import streamlit as st
import pandas as pd
import plotly.express as px
import json
import os
import tempfile
from collections import Counter, defaultdict
from _page_descriptions import render_page_description

try:
    import ijson
except Exception:
    ijson = None

st.set_page_config(page_title="News Data Visualization", layout="wide")

st.title("📊 News Collection Analytics")
render_page_description(__file__)

# Replace load_data with streaming / chunked processor
@st.cache_data
def save_to_temp(uploaded_file):
    uploaded_file.seek(0)
    tmp = tempfile.NamedTemporaryFile(delete=False)
    with open(tmp.name, "wb") as f:
        f.write(uploaded_file.read())
    return tmp.name

def _detect_json_format(path, nbytes=8192):
    """Return 'array', 'jsonl', 'object', or None/unknown for the file at path."""
    with open(path, "rb") as f:
        start = f.read(nbytes).lstrip()
    if not start:
        return None
    first = start[:1]
    if first == b'[':
        return "array"
    if first == b'{':
        # could be a single large JSON object (not iterable)
        # or JSONL where each line is an object (first char may be '{')
        # Heuristic: if there are newline-delimited separate objects inside the first bytes, treat as jsonl
        if b'\n' in start and b'\n{' in start:
            return "jsonl"
        # otherwise treat as single object
        return "object"
    # if first char is '{' on each line or file looks like lines of JSON objects
    if b'\n' in start and start.strip().startswith(b'{'):
        return "jsonl"
    return "unknown"

def process_large_file(path, chunk_size=100_000, preview_limit=1000):
    total = 0
    source_counts = Counter()
    sentiment_sum = 0.0
    sentiment_count = 0
    preview_rows = []
    preview_row_count = 0
    sources_set = set()

    def _make_hashable(x):
        # keep simple scalars as-is, serialize dicts/lists to JSON to make them hashable/consistent
        try:
            if x is None:
                return None
            if isinstance(x, (str, int, float, bool)):
                # treat NaN as None
                if isinstance(x, float) and pd.isna(x):
                    return None
                return x
            # for pandas NA/NaT
            if pd.isna(x):
                return None
        except Exception:
            pass
        try:
            return json.dumps(x, sort_keys=True, ensure_ascii=False)
        except Exception:
            return str(x)

    p = path.lower()
    # CSV streaming
    if p.endswith(".csv"):
        reader = pd.read_csv(path, chunksize=chunk_size)
        for chunk in reader:
            if chunk.empty:
                continue
            if "date" in chunk.columns:
                chunk["date"] = pd.to_datetime(chunk["date"], errors="coerce")
            total += len(chunk)
            source_col = "source" if "source" in chunk.columns else chunk.columns[0]
            # sanitize source values so unhashable types become hashable strings
            src_series = chunk[source_col].map(_make_hashable)
            vc = src_series.value_counts(dropna=True)
            source_counts.update(vc.to_dict())
            sources_set.update([s for s in src_series.dropna().unique().tolist()])
            if "sentiment" in chunk.columns:
                s = pd.to_numeric(chunk["sentiment"], errors="coerce").dropna()
                sentiment_sum += s.sum()
                sentiment_count += s.count()
            # preview: take rows until preview_limit reached
            if preview_row_count < preview_limit:
                to_take = min(preview_limit - preview_row_count, len(chunk))
                preview_rows.append(chunk.iloc[:to_take])
                preview_row_count += to_take
    elif p.endswith(".json"):
        fmt = _detect_json_format(path)
        # JSON lines (one JSON object per line)
        if fmt == "jsonl" or fmt == "unknown":
            try:
                reader = pd.read_json(path, lines=True, chunksize=chunk_size)
                for chunk in reader:
                    if chunk.empty:
                        continue
                    if "date" in chunk.columns:
                        chunk["date"] = pd.to_datetime(chunk["date"], errors="coerce")
                    total += len(chunk)
                    source_col = "source" if "source" in chunk.columns else chunk.columns[0]
                    src_series = chunk[source_col].map(_make_hashable)
                    vc = src_series.value_counts(dropna=True)
                    source_counts.update(vc.to_dict())
                    sources_set.update([s for s in src_series.dropna().unique().tolist()])
                    if "sentiment" in chunk.columns:
                        s = pd.to_numeric(chunk["sentiment"], errors="coerce").dropna()
                        sentiment_sum += s.sum()
                        sentiment_count += s.count()
                    if preview_row_count < preview_limit:
                        to_take = min(preview_limit - preview_row_count, len(chunk))
                        preview_rows.append(chunk.iloc[:to_take])
                        preview_row_count += to_take
            except ValueError:
                # fallthrough to streaming via ijson if available
                if ijson is None:
                    raise ValueError("File is not JSONL and ijson is not installed. Install ijson to stream large JSON arrays: pip install ijson")
                fmt = _detect_json_format(path)
        if fmt == "array":
            if ijson is None:
                raise ValueError("Large JSON array detected — install ijson to stream it: pip install ijson")
            # stream top-level array elements
            try:
                buffer = []
                with open(path, "rb") as f:
                    # ijson.items(f, 'item') yields each item in top-level array
                    for obj in ijson.items(f, "item"):
                        buffer.append(obj)
                        if len(buffer) >= chunk_size:
                            chunk = pd.DataFrame(buffer)
                            if chunk.empty:
                                buffer = []
                                continue
                            if "date" in chunk.columns:
                                chunk["date"] = pd.to_datetime(chunk["date"], errors="coerce")
                            total += len(chunk)
                            source_col = "source" if "source" in chunk.columns else chunk.columns[0]
                            src_series = chunk[source_col].map(_make_hashable)
                            vc = src_series.value_counts(dropna=True)
                            source_counts.update(vc.to_dict())
                            sources_set.update([s for s in src_series.dropna().unique().tolist()])
                            if "sentiment" in chunk.columns:
                                s = pd.to_numeric(chunk["sentiment"], errors="coerce").dropna()
                                sentiment_sum += s.sum()
                                sentiment_count += s.count()
                            if preview_row_count < preview_limit:
                                to_take = min(preview_limit - preview_row_count, len(chunk))
                                preview_rows.append(chunk.iloc[:to_take])
                                preview_row_count += to_take
                            buffer = []
                    # process any remaining buffered items
                    if buffer:
                        chunk = pd.DataFrame(buffer)
                        if not chunk.empty:
                            if "date" in chunk.columns:
                                chunk["date"] = pd.to_datetime(chunk["date"], errors="coerce")
                            total += len(chunk)
                            source_col = "source" if "source" in chunk.columns else chunk.columns[0]
                            src_series = chunk[source_col].map(_make_hashable)
                            vc = src_series.value_counts(dropna=True)
                            source_counts.update(vc.to_dict())
                            sources_set.update([s for s in src_series.dropna().unique().tolist()])
                            if "sentiment" in chunk.columns:
                                s = pd.to_numeric(chunk["sentiment"], errors="coerce").dropna()
                                sentiment_sum += s.sum()
                                sentiment_count += s.count()
                            if preview_row_count < preview_limit:
                                to_take = min(preview_limit - preview_row_count, len(chunk))
                                preview_rows.append(chunk.iloc[:to_take])
                                preview_row_count += to_take
            except Exception as exc:
                # Provide clearer message with cause
                raise ValueError(f"ijson failed to stream the JSON array: {exc}") from exc
        elif fmt == "object":
            raise ValueError("JSON file contains a single top-level object. Streaming aggregations expect an array or JSONL. Convert to array/JSONL or load as a small file.")
        # if we previously attempted pd.read_json(lines=True) and it worked, we have already processed data
    else:
        raise ValueError("Unsupported file format for streaming")

    # If preview_rows contains many small DataFrames, concat them; if none, empty df
    if preview_rows:
        preview_df = pd.concat(preview_rows, ignore_index=True).head(preview_limit)
    else:
        preview_df = pd.DataFrame()

    avg_sentiment = (sentiment_sum / sentiment_count) if sentiment_count > 0 else None
    per_source_series = pd.Series(dict(source_counts)).sort_values(ascending=False)

    return {
        "total": total,
        "unique_sources": len(sources_set),
        "avg_sentiment": avg_sentiment,
        "per_source": per_source_series,
        "preview": preview_df,
    }

# File Uploader in Sidebar (replaced)
st.sidebar.header("Data Upload")

input_mode = st.sidebar.radio("Input mode", ("Upload (browser)", "Server file path / local on server"))
uploaded_file = None
server_path = None

if input_mode == "Upload (browser)":
    uploaded_file = st.sidebar.file_uploader("Upload CSV or JSON", type=["csv", "json"])
else:
    st.sidebar.write("Provide an absolute path to a CSV/JSON file accessible from the Streamlit server (preferred for large files).")
    server_path = st.sidebar.text_input("Server file path (absolute)")
    if server_path:
        if not os.path.exists(server_path) or not os.path.isfile(server_path):
            st.sidebar.error("Path not found or not readable by the server.")
            server_path = None

# helper to load small files (either uploaded or server path)
def _load_small_file(uploaded_obj=None, path=None):
    if path:
        p = path.lower()
        if p.endswith(".csv"):
            df = pd.read_csv(path)
        elif p.endswith(".json"):
            # try JSONL first, then normal json
            try:
                df = pd.read_json(path, lines=True)
            except ValueError:
                df = pd.read_json(path)
        else:
            return None
    else:
        # uploaded_obj is a BytesIO / UploadedFile
        uploaded_obj.seek(0)
        name = getattr(uploaded_obj, "name", "").lower()
        if name.endswith(".csv"):
            df = pd.read_csv(uploaded_obj)
        elif name.endswith(".json"):
            try:
                df = pd.read_json(uploaded_obj)
            except ValueError:
                uploaded_obj.seek(0)
                df = pd.read_json(uploaded_obj, lines=True)
        else:
            return None
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df

if uploaded_file is not None or server_path:
    try:
        # determine path and size
        if server_path:
            tmp_path = server_path
            size_mb = os.path.getsize(tmp_path) / (1024 * 1024)
            st.sidebar.write(f"Using server file: {tmp_path} ({size_mb:.1f} MB)")
        else:
            tmp_path = save_to_temp(uploaded_file)
            size_mb = os.path.getsize(tmp_path) / (1024 * 1024)
            st.sidebar.write(f"Uploaded file size: {size_mb:.1f} MB")

        # If large file -> stream/process in batches
        if size_mb > 50:  # threshold (adjust as needed)
            st.info("Large file detected — processing in streaming mode.")
            summary = process_large_file(tmp_path, chunk_size=100_000, preview_limit=1000)

            # Display aggregated metrics
            col1, col2, col3 = st.columns(3)
            col1.metric("Total Articles", summary["total"])
            col2.metric("Unique Sources", summary["unique_sources"])
            avg_sent = round(summary["avg_sentiment"], 2) if summary["avg_sentiment"] is not None else "N/A"
            col3.metric("Avg Sentiment", avg_sent)

            # Bar chart from aggregated counts
            st.subheader("Articles per Source (aggregated)")
            per_src_df = summary["per_source"].head(30).reset_index(name="count").rename(columns={"index": "source"})
            st.plotly_chart(
                px.bar(
                    per_src_df,
                    x="source",
                    y="count",
                    labels={"count": "Count", "source": "Source"},
                ),
                use_container_width=True,
            )

            st.subheader("Preview of first rows")
            st.dataframe(summary["preview"], use_container_width=True)

            st.info(
                "For time series or detailed filtering, use a smaller filtered file or implement "
                "additional streaming aggregations by date/source."
            )
        else:
            # small file -> load fully into memory
            if server_path:
                df = _load_small_file(path=tmp_path)
            else:
                # load from uploaded object (not temp file) to preserve filenames/types
                df = _load_small_file(uploaded_obj=uploaded_file, path=None)

            if df is not None:
                # Sidebar Filters
                st.sidebar.header("Filters")
                source_col = "source" if "source" in df.columns else df.columns[0]
                selected_source = st.sidebar.multiselect(
                    "Select Source", options=df[source_col].unique(), default=df[source_col].unique()
                )

                filtered_df = df[df[source_col].isin(selected_source)]

                # Metrics
                col1, col2, col3 = st.columns(3)
                col1.metric("Total Articles", len(filtered_df))
                col2.metric("Unique Sources", filtered_df[source_col].nunique())

                sentiment_val = filtered_df["sentiment"].mean() if "sentiment" in filtered_df.columns else 0
                col3.metric("Avg Sentiment", round(sentiment_val, 2))

                # Visualizations
                st.divider()
                c1, c2 = st.columns(2)

                with c1:
                    st.subheader("Articles per Source")
                    counts_df = filtered_df[source_col].value_counts().reset_index(name="count").rename(columns={"index": source_col})
                    fig_source = px.bar(counts_df, x=source_col, y="count", labels={source_col: "Source", "count": "Count"})
                    st.plotly_chart(fig_source, use_container_width=True)

                with c2:
                    if "date" in filtered_df.columns and "sentiment" in filtered_df.columns:
                        st.subheader("Sentiment Over Time")
                        fig_time = px.line(filtered_df, x="date", y="sentiment", color=source_col, markers=True)
                        st.plotly_chart(fig_time, use_container_width=True)
                    else:
                        st.info("Upload data with 'date' and 'sentiment' columns for time series view.")

                st.subheader("Raw Data View")
                st.dataframe(filtered_df, use_container_width=True)
            else:
                st.error("Unsupported file format.")
    except Exception as e:
        st.error(f"Error processing file: {e}")
else:
    st.info("Please upload a CSV or JSON file in the sidebar to begin.")

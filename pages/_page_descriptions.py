from pathlib import Path

import streamlit as st


PAGE_DESCRIPTIONS = {
    "0_0_News_Extractor.py": {
        "summary": "Extract full article text for ESG-tagged news items stored in the local dataset.",
        "purpose": "Use this page to inspect collected news records, resolve source URLs, and save article-body content for downstream cleaning or analysis.",
        "workflow": [
            "Load `data/news_dataset_new.json` into a reviewable table.",
            "Filter candidate articles, then fetch article text from the resolved publisher URL.",
            "Persist extracted content to `data/news_content.json` for later viewers and dashboards.",
        ],
        "data": [
            "Inputs: `data/news_dataset_new.json`",
            "Outputs: `data/news_content.json`",
            "Dependencies: `requests`, `BeautifulSoup`, optional `googlenewsdecoder`",
        ],
        "notes": ["Best used after a collection page has already created the news dataset."],
    },
    "0_1_News_Full_Extractor.py": {
        "summary": "Prototype page for full-article extraction and hierarchical article packaging.",
        "purpose": "This file keeps an older end-to-end extraction experiment that combines decoding, scraping, and structured JSON output in one place.",
        "workflow": [
            "Intended to batch-process existing news dataset records.",
            "Build article-level extraction objects with metadata and extracted body text.",
            "Write richer hierarchical output for analysis or archival.",
        ],
        "data": [
            "Intended inputs: news dataset JSON files under `data/`",
            "Intended outputs: extracted article collections and run logs",
        ],
        "notes": ["Current file contains legacy or commented implementations and should be treated as experimental."],
    },
    "0_path_extractor.py": {
        "summary": "Bulk selector and path extraction tool for HTML, XML, or JSON samples.",
        "purpose": "Use this page when you need to inspect raw documents and capture repeatable extraction paths before building a scraper.",
        "workflow": [
            "Load or paste source markup.",
            "Inspect elements, paths, and parent links.",
            "Export selector metadata to JSON for reuse in other scraping workflows.",
        ],
        "data": [
            "Inputs: markup files in `temporary_pear/` or pasted raw content",
            "Outputs: selector JSON files such as `extracted_selectors_*.json`",
        ],
        "notes": ["This file also contains multiple archived versions of the same tool."],
    },
    "1.py": {
        "summary": "Collect Google News RSS results into a reusable JSON dataset.",
        "purpose": "Run keyword or company queries against Google News RSS, store normalized result rows, and build the base dataset used by later extraction pages.",
        "workflow": [
            "Configure query, language, country, and result limits.",
            "Fetch RSS entries and normalize metadata fields.",
            "Append deduplicated rows to the stored dataset.",
        ],
        "data": [
            "Inputs: search terms entered in the UI",
            "Outputs: `data/news_dataset.json`",
            "Dependencies: `feedparser`, `requests`, `pandas`",
        ],
        "notes": ["Use the bulk variants when you need many company-keyword combinations."],
    },
    "1_Batch_Extractor.py": {
        "summary": "Run article extraction over a saved dataset in controlled batches.",
        "purpose": "This page is the operational batch runner for `extractor.pipeline`, letting you continue extraction work incrementally instead of processing the full corpus at once.",
        "workflow": [
            "Read pending rows from `data/news_dataset_new.json`.",
            "Skip items already present in `data/news_extracted.json`.",
            "Append extraction results and status logs after each run.",
        ],
        "data": [
            "Inputs: `data/news_dataset_new.json`",
            "Outputs: `data/news_extracted.json`, `data/logs.json`",
            "Dependencies: `extractor.pipeline`, `extractor.storage`",
        ],
        "notes": ["Useful for long-running extractions where you want resume-safe progress."],
    },
    "1_Instaloader_Scraper.py": {
        "summary": "Scrape public Instagram posts with Instaloader and save normalized JSON.",
        "purpose": "Use this page for the stable Instagram collection path when account content is public and browser automation is unnecessary.",
        "workflow": [
            "Provide a username and post limit.",
            "Fetch normalized post metadata through `utils.instaloader_client`.",
            "Review the dataframe and save results to disk.",
        ],
        "data": [
            "Outputs: Instagram post files under `data/instagram/` or the shared storage layout",
            "Dependencies: `instaloader`, `utils.storage`",
        ],
        "notes": ["Prefer this page over the Playwright fallback when Instaloader works."],
    },
    "1_instagram.py": {
        "summary": "Early Instagram scraping page for public post collection.",
        "purpose": "This is a lighter or older Instagram collector that remains useful for quick tests and simple account pulls.",
        "workflow": [
            "Enter a username and scrape posts.",
            "Inspect the returned dataframe.",
            "Persist results for downstream ESG dashboards.",
        ],
        "data": [
            "Outputs: Instagram post JSON files in the shared data directory",
        ],
        "notes": ["Treat this as a simpler predecessor to `1_Instaloader_Scraper.py`."],
    },
    "1_🏢_Coverage_Mapper.py": {
        "summary": "Compare the ESG company master list against collected news coverage.",
        "purpose": "Use this page to identify which tracked companies are covered, missing, or appearing unexpectedly inside the news dataset.",
        "workflow": [
            "Load the ESG company registry and collected news records.",
            "Map detected company mentions against the master list.",
            "Review gaps, overlaps, and unmatched entities.",
        ],
        "data": [
            "Inputs: ESG company JSON and news dataset files under `data/`",
            "Outputs: interactive coverage comparison views",
        ],
        "notes": ["Useful for spotting collection blind spots before further scraping."],
    },
    "2_Playwright_Scraper.py": {
        "summary": "Browser-based Instagram scraping fallback using Playwright.",
        "purpose": "Use this page when Instaloader is insufficient and you need UI-level scraping from the public Instagram profile page.",
        "workflow": [
            "Open the profile through Playwright.",
            "Scroll the profile grid to collect visible post links.",
            "Save the normalized records for later dashboard pages.",
        ],
        "data": [
            "Dependencies: `playwright`, `utils.playwright_client`",
            "Outputs: saved Instagram post metadata",
        ],
        "notes": ["This path is slower and more brittle than Instaloader."],
    },
    "2_x_twitter.py": {
        "summary": "Legacy X scraping page for tweet collection experiments.",
        "purpose": "This page keeps an older X collection flow that predates the more explicit incremental scraper pages.",
        "workflow": [
            "Collect X posts for a given account or query.",
            "Normalize result rows for storage.",
            "Preview the output before saving.",
        ],
        "data": [
            "Outputs: X post JSON files in the shared storage layout",
        ],
        "notes": ["Prefer `6_X_Scraper.py` for the current incremental workflow."],
    },
    "2_🚀_Auto_Scraper.py": {
        "summary": "Automated ESG news collection runner for unattended scraping loops.",
        "purpose": "Use this page to orchestrate recurring or larger-scale news collection without stepping through each query manually.",
        "workflow": [
            "Load company and keyword configuration.",
            "Run the collection loop with batch settings.",
            "Store appended dataset rows and status information.",
        ],
        "data": [
            "Inputs: company and keyword JSON files under `data/`",
            "Outputs: updated news dataset and logs",
        ],
        "notes": ["Designed for operational runs rather than detailed inspection."],
    },
    "3_IG_ESG_Dashboard.py": {
        "summary": "Dashboard for reviewing saved Instagram ESG scrape batches.",
        "purpose": "Use this page to browse saved Instagram collections by account and scrape date, then inspect post-level metrics.",
        "workflow": [
            "Choose a scrape batch from stored files.",
            "Filter by company and collection date.",
            "Review normalized posts and engagement metrics.",
        ],
        "data": [
            "Inputs: saved Instagram post JSON files",
            "Outputs: interactive tables and charts only",
        ],
        "notes": ["Pairs naturally with the Instagram visualizer pages."],
    },
    "3_view_articles.py": {
        "summary": "Table and detail viewer for previously scraped article content.",
        "purpose": "Use this page to inspect article-level extraction results without reopening raw JSON files manually.",
        "workflow": [
            "Load extracted article records from disk.",
            "Browse a tabular overview with key metadata.",
            "Open a detailed view for the selected article body.",
        ],
        "data": [
            "Inputs: extracted article JSON files under `data/`",
        ],
        "notes": ["Useful for QA before cleaning or reporting."],
    },
    "4_Post_Visualizer.py": {
        "summary": "Inspect Instagram engagement metrics and archived media for one selected post.",
        "purpose": "Use this page when you want a focused, post-level view instead of the broader Instagram batch dashboard.",
        "workflow": [
            "Select a company and post from saved batches.",
            "Review engagement metrics and timeline context.",
            "Render any locally archived media snapshot.",
        ],
        "data": [
            "Inputs: saved Instagram post files and optional media snapshots in `data/media/`",
        ],
        "notes": ["Works best after you have already scraped and saved Instagram data."],
    },
    "6_X_Scraper.py": {
        "summary": "Incremental X scraper with API and Playwright collection modes.",
        "purpose": "Use this page for current X monitoring runs. It supports resume-safe collection by skipping posts that are already stored locally.",
        "workflow": [
            "Choose API or Playwright collection mode.",
            "Load existing post IDs for the account.",
            "Save only new posts and preview engagement metrics.",
        ],
        "data": [
            "Outputs: X post files under `data/x/`",
            "Dependencies: `ingestors.x_api_ingestor`, `ingestors.x_playwright_ingestor`",
        ],
        "notes": ["Recommended X entry point for operational scraping."],
    },
    "7_X_Visualizer.py": {
        "summary": "Dashboard for exploring stored X scrape batches and post engagement.",
        "purpose": "Use this page to review collected X data by account and scrape date, then inspect activity trends and individual posts.",
        "workflow": [
            "Pick an available saved batch.",
            "Visualize engagement over time.",
            "Inspect a single post in detail.",
        ],
        "data": [
            "Inputs: saved X JSON files under `data/x/`",
        ],
        "notes": ["Complements `6_X_Scraper.py` for QA and reporting."],
    },
    "8_YouTube_Scraper.py": {
        "summary": "Collect YouTube channel videos, video stats, and comments for ESG monitoring.",
        "purpose": "Use this page to pull channel-level or video-level YouTube data through the official API and store it in the normalized project format.",
        "workflow": [
            "Resolve a channel and fetch recent videos.",
            "Load video statistics and optional comment threads.",
            "Preview and export the collected data.",
        ],
        "data": [
            "Dependencies: `YOUTUBE_API_KEY`, `ingestors.youtube_api_ingestor`, `utils.youtube_utils`",
        ],
        "notes": ["Requires a valid YouTube Data API key in the environment."],
    },
    "9_URL_Testing.py": {
        "summary": "Small utility page for testing YouTube channel URL to channel-ID resolution.",
        "purpose": "Use this page to validate the URL parsing logic before running larger YouTube ingestion workflows.",
        "workflow": [
            "Paste a YouTube channel URL or handle.",
            "Resolve it through `utils.youtube_utils.get_channel_id_from_url`.",
            "Confirm the resulting channel ID for later scraping.",
        ],
        "data": [
            "Dependencies: `utils.youtube_utils` and a valid YouTube API key",
        ],
        "notes": ["This page is intended as a focused troubleshooting utility."],
    },
    "bulk_scrapping.py": {
        "summary": "Run multiple Google News queries and append all results to the shared dataset.",
        "purpose": "Use this page when a single query is not enough and you want to build a larger news corpus from a list of search terms.",
        "workflow": [
            "Enter or upload multiple queries.",
            "Fetch RSS results for each query in sequence.",
            "Append normalized rows to the stored dataset.",
        ],
        "data": [
            "Outputs: `data/news_dataset.json`",
        ],
        "notes": ["Operational bulk collector for the core news dataset."],
    },
    "bulk_scrapping_batch_date.py": {
        "summary": "Bulk Google News collector with explicit date filters and log output.",
        "purpose": "Use this page to collect news within bounded time windows and keep better visibility into run-level scraper behavior.",
        "workflow": [
            "Choose companies, keywords, and a date range.",
            "Run batch collection for each generated query.",
            "Review dataset updates and scraper logs.",
        ],
        "data": [
            "Outputs: news dataset files plus run logs",
        ],
        "notes": ["Recommended when you need time-bounded datasets."],
    },
    "bulk_scrapping_batch_date_auto.py": {
        "summary": "Auto-fill date-window gaps in the ESG news dataset.",
        "purpose": "Use this page when you want the system to identify missing coverage windows and run date-filtered collection automatically.",
        "workflow": [
            "Assess current coverage status.",
            "Generate missing query-date combinations.",
            "Run batch scraping and append new records.",
        ],
        "data": [
            "Inputs: company registry, keyword mapping, existing news dataset",
            "Outputs: updated dataset plus scraper logs",
        ],
        "notes": ["Useful for maintenance runs that backfill gaps."],
    },
    "bulk_scrapping_with_batch_keywords.py": {
        "summary": "Generate many company-keyword query combinations for Google News collection.",
        "purpose": "Use this page to scale collection across multiple ESG keywords for each selected company in one run.",
        "workflow": [
            "Select companies and load keyword mappings.",
            "Generate company-keyword search queries.",
            "Run scraping and append deduplicated dataset rows.",
        ],
        "data": [
            "Inputs: `data/esg_companies.json`, `data/esg_keywords*.json`",
            "Outputs: shared news dataset JSON",
        ],
        "notes": ["Designed for structured ESG coverage building."],
    },
    "bulk_scrapping_with_batch_keywords_auto.py": {
        "summary": "Automated company-keyword news collection with coverage-aware batch generation.",
        "purpose": "This page expands the batch-keyword collector with more automated scheduling and coverage tracking so you can backfill gaps with less manual setup.",
        "workflow": [
            "Review company coverage status.",
            "Generate missing company-keyword search tasks.",
            "Run the collector and append results.",
        ],
        "data": [
            "Outputs: updated shared news dataset and logs",
        ],
        "notes": ["Best suited for maintenance or recurring operational collection."],
    },
    "bulk_scrapping_with_keywords.py": {
        "summary": "Manual company-to-keyword Google News scraping workflow.",
        "purpose": "Use this page for a more controlled version of the ESG company-keyword collector when you want to inspect each generated query as it runs.",
        "workflow": [
            "Select companies and their associated ESG keywords.",
            "Run the queries one by one.",
            "Preview and save the collected records.",
        ],
        "data": [
            "Outputs: shared news dataset JSON",
        ],
        "notes": ["Good for targeted collection or QA runs."],
    },
    "keyword_visualization.py": {
        "summary": "Analyze and compare ESG keyword mappings across tracked companies.",
        "purpose": "Use this dashboard to audit the keyword master data that drives the news collection queries.",
        "workflow": [
            "Load one or more keyword JSON files.",
            "Filter mappings by company or term.",
            "Review counts, overlaps, and exportable tables.",
        ],
        "data": [
            "Inputs: keyword mapping JSON files under `data/`",
        ],
        "notes": ["Useful before launching large batch scrapes."],
    },
    "logs_tracker.py": {
        "summary": "Analyze run logs produced by automated news scraping jobs.",
        "purpose": "Use this page to understand which companies, keywords, or time periods are producing news and where scraper yield is low.",
        "workflow": [
            "Load aggregated run logs.",
            "Review company-level and keyword-level yield summaries.",
            "Inspect the timeline of scraping activity.",
        ],
        "data": [
            "Inputs: log files such as `logs/scraper_runs*.jsonl`",
        ],
        "notes": ["Operational dashboard for monitoring scraper performance."],
    },
    "missing_news.py": {
        "summary": "Identify covered, uncovered, and unmatched companies in the news dataset.",
        "purpose": "This is the main company-coverage gap dashboard for the news corpus, focused on QA of entity coverage rather than raw collection.",
        "workflow": [
            "Compare collected news mentions with the ESG company list.",
            "Show covered companies and missing targets.",
            "Highlight unexpected companies appearing in news data.",
        ],
        "data": [
            "Inputs: company master data and saved news dataset files",
        ],
        "notes": ["Closely related to `1_🏢_Coverage_Mapper.py`, with stronger dashboard focus."],
    },
    "news_dataset_distribution.py": {
        "summary": "Explore distribution patterns in the news dataset without extra filtering layers.",
        "purpose": "Use this page for a quick statistical overview of the stored news dataset: time, source, query, and status distributions.",
        "workflow": [
            "Load the stored news dataset.",
            "Review charts for dates, sources, queries, and status values.",
            "Inspect the most recent articles.",
        ],
        "data": [
            "Inputs: news dataset JSON under `data/`",
        ],
        "notes": ["Baseline dataset dashboard for fast health checks."],
    },
    "news_dataset_distribution_with_selected_timeframe.py": {
        "summary": "Dataset distribution dashboard with additional time-range selection.",
        "purpose": "Use this page when you need the same dataset health checks as the standard dashboard but limited to a specific timeframe.",
        "workflow": [
            "Choose a start and end period.",
            "Recompute source, query, and status distributions.",
            "Review monthly trends and recent articles within the filter window.",
        ],
        "data": [
            "Inputs: stored news dataset JSON files",
        ],
        "notes": ["Preferred over the baseline dashboard for period-specific analysis."],
    },
    "streamlit_company_news.py": {
        "summary": "Company-centric intelligence dashboard with grouping and duplicate-aware article views.",
        "purpose": "Use this page to review the news corpus from a company perspective, including grouped duplicates, keyword context, and coverage trends.",
        "workflow": [
            "Load and normalize the news dataset.",
            "Group duplicate or near-duplicate items.",
            "Review company coverage, source mix, and keyword distribution.",
        ],
        "data": [
            "Inputs: shared news dataset JSON",
            "Outputs: interactive analytics only",
        ],
        "notes": ["This file also contains archived dashboard iterations in comments."],
    },
    "streamlit_news_dashboard.py": {
        "summary": "General ESG news dataset visualizer for company and score-level trends.",
        "purpose": "Use this dashboard to monitor the shape of the current corpus, especially article counts, ESG scores, and temporal/source distributions.",
        "workflow": [
            "Load the saved news dataset.",
            "Plot article volume, ESG score, time, and source summaries.",
            "Inspect company-level aggregates.",
        ],
        "data": [
            "Inputs: stored news dataset JSON files",
        ],
        "notes": ["Broad dashboard for portfolio-level dataset review."],
    },
}


def render_page_description(page_file: str) -> None:
    doc = PAGE_DESCRIPTIONS.get(Path(page_file).name)
    if not doc:
        return

    st.caption(doc["summary"])

    with st.expander("Page guide", expanded=False):
        st.markdown(f"**Purpose**\n\n{doc['purpose']}")

        workflow = doc.get("workflow", [])
        if workflow:
            st.markdown("**Workflow**")
            for step in workflow:
                st.markdown(f"- {step}")

        data_points = doc.get("data", [])
        if data_points:
            st.markdown("**Primary files / services**")
            for item in data_points:
                st.markdown(f"- {item}")

        notes = doc.get("notes", [])
        if notes:
            st.markdown("**Notes**")
            for note in notes:
                st.markdown(f"- {note}")

# Root Monitoring App

This document covers the root Streamlit application that lives beside `app.py`, `app_2.py`, and the top-level `pages/` folder.

## What This App Does

The root app combines several related workflows:

- Collect Indonesian news from API or Google News sources.
- Build and maintain JSON datasets for ESG or company-focused news analysis.
- Extract full article text from saved news rows.
- Scrape public social-media content from Instagram, X, and YouTube.
- Visualize datasets, keyword coverage, and scraper logs.

## Main Entry Points

| File | Role |
| --- | --- |
| `app.py` | News source fetcher, saver, auto-refresh dashboard, and analytics hub |
| `app_2.py` | URL-focused robust article scraper with single and bulk extraction modes |
| `pages/` | Multipage tools for collection, extraction, dashboards, and social-media scraping |

## Root Page Groups

### News collection and dataset building

- `pages/1.py`
- `pages/bulk_scrapping.py`
- `pages/bulk_scrapping_with_keywords.py`
- `pages/bulk_scrapping_with_batch_keywords.py`
- `pages/bulk_scrapping_with_batch_keywords_auto.py`
- `pages/bulk_scrapping_batch_date.py`
- `pages/bulk_scrapping_batch_date_auto.py`
- `pages/2_🚀_Auto_Scraper.py`

These pages create or extend JSON datasets such as `data/news_dataset.json` and `data/news_dataset_new.json`.

### Article extraction and repair

- `pages/0_0_News_Extractor.py`
- `pages/1_Batch_Extractor.py`
- `pages/3_view_articles.py`
- `pages/0_1_News_Full_Extractor.py`
- `pages/0_path_extractor.py`

These pages operate on saved article metadata, resolve URLs, scrape body text, and help inspect or prototype extraction paths.

### Social-media collection

- `pages/1_Instaloader_Scraper.py`
- `pages/2_Playwright_Scraper.py`
- `pages/2_x_twitter.py`
- `pages/6_X_Scraper.py`
- `pages/8_YouTube_Scraper.py`
- `pages/9_URL_Testing.py`

These pages normalize public platform data into local JSON files under `data/`.

### Analytics and dashboards

- `pages/3_IG_ESG_Dashboard.py`
- `pages/4_Post_Visualizer.py`
- `pages/7_X_Visualizer.py`
- `pages/streamlit_news_dashboard.py`
- `pages/streamlit_company_news.py`
- `pages/news_dataset_distribution.py`
- `pages/news_dataset_distribution_with_selected_timeframe.py`
- `pages/missing_news.py`
- `pages/1_🏢_Coverage_Mapper.py`
- `pages/keyword_visualization.py`
- `pages/logs_tracker.py`

These pages are read-heavy dashboards for QA, coverage analysis, and reporting.

## Shared Modules

| Module | Responsibility |
| --- | --- |
| `extractor/article_extractor.py` | Download and parse article content, store raw HTML |
| `extractor/redirect_resolver.py` | Resolve Google News redirects to publisher URLs |
| `extractor/pipeline.py` | Generate IDs and package extracted article output |
| `ingestors/x_api_ingestor.py` | Pull X posts through the official API |
| `ingestors/x_playwright_ingestor.py` | Incremental X scraping through Playwright |
| `ingestors/youtube_api_ingestor.py` | YouTube channel, video, and comment ingestion |
| `utils/storage.py` | Platform-oriented save and load helpers |
| `utils/instaloader_client.py` | Public Instagram collection via Instaloader |
| `utils/playwright_client.py` | Playwright-based Instagram page scraping |
| `utils/youtube_utils.py` | Resolve channel handles and related YouTube helpers |
| `utils/x_text_metrics.py` | Parse engagement counts from X text blobs |

## Data Layout

Common root outputs:

- `data/news.json`
- `data/news_dataset.json`
- `data/news_dataset_new.json`
- `data/news_content.json`
- `data/news_extracted.json`
- `data/logs.json`
- `logs/scraper_runs.jsonl`
- `data/instagram/`, `data/x/`, or other platform folders created through `utils/storage.py`

## Suggested Workflow

1. Build or refresh the news dataset with one of the collection pages.
2. Use extraction pages to fetch full article text.
3. Review output quality with the viewer and distribution dashboards.
4. Run platform-specific social scrapers if the analysis also requires Instagram, X, or YouTube coverage.
5. Use coverage dashboards to identify collection gaps and rerun the relevant collector.

## Known Constraints

- A number of pages keep older code blocks in comments. Only the active top-level code path should be treated as current.
- Most persistence is file-based JSON, so concurrent writes and large datasets require care.
- External API availability and rate limits affect X and YouTube pages.

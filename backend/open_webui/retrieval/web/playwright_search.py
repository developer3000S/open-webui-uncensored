from __future__ import annotations

import logging
import urllib.parse

from open_webui.retrieval.web.main import SearchResult, get_filtered_results

log = logging.getLogger(__name__)

# Search-engine homepages that accept the query via a `q`-style URL parameter.
# Results are collected from the SERP's own result links (organic hits only),
# so no HTML scraping of snippets is required and the provider stays robust
# against markup changes.
SEARCH_URL_TEMPLATES = {
    'duckduckgo': 'https://duckduckgo.com/?q={query}',
    'bing': 'https://www.bing.com/search?q={query}&count={count}',
    'google': 'https://www.google.com/search?q={query}&num={count}',
    'brave': 'https://search.brave.com/search?q={query}',
    'mojeek': 'https://www.mojeek.com/search?q={query}',
}

ENGINE_RESULT_HOSTS = {
    'duckduckgo': ('duckduckgo.com',),
    'bing': ('bing.com',),
    'google': ('google.',),
    'brave': ('search.brave.com',),
    'mojeek': ('mojeek.com',),
}


async def search_playwright(
    query: str,
    count: int,
    filter_list: list[str | None] = None,
    playwright_ws_url: str | None = None,
    playwright_timeout: int = 10000,
    engine: str = 'duckduckgo',
) -> list[SearchResult]:
    """Run a real web search through a headless browser (Playwright).

    Loads the search-engine results page in a browser context (so JavaScript
    rendered SERPs work), then collects organic result links directly from the
    page DOM. Uses a remote browser via ``playwright_ws_url`` when configured,
    otherwise launches a local headless Chromium instance.

    Args:
        query: The search query.
        count: Maximum number of results to return.
        filter_list: Domain allow/deny filter list applied to the results.
        playwright_ws_url: WebSocket endpoint of a remote Playwright browser server.
        playwright_timeout: Navigation/operation timeout in milliseconds.
        engine: One of the keys of SEARCH_URL_TEMPLATES.

    Returns:
        list[SearchResult]: Search results with link/title (snippet best-effort).
    """
    template = SEARCH_URL_TEMPLATES.get(engine)
    if template is None:
        raise Exception(f'Unsupported playwright search engine: {engine}')

    url = template.format(query=urllib.parse.quote_plus(query), count=count)
    engine_hosts = ENGINE_RESULT_HOSTS.get(engine, ())

    # Imported lazily so environments without the playwright extra keep working
    # for every other search provider.
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        if playwright_ws_url:
            browser = await p.chromium.connect(playwright_ws_url)
        else:
            browser = await p.chromium.launch(headless=True)

        try:
            page = await browser.new_page(java_script_enabled=True)
            response = await page.goto(url, timeout=playwright_timeout, wait_until='domcontentloaded')
            if response is None:
                raise ValueError(f'page.goto() returned None for url {url}')

            # Give client-side rendered result lists a brief moment to appear.
            try:
                await page.wait_for_timeout(min(2000, playwright_timeout // 4))
            except Exception:
                pass

            anchors = await page.query_selector_all('a[href^="http"]')
            seen: set[str] = set()
            results: list[SearchResult] = []

            for anchor in anchors:
                href = await anchor.get_attribute('href')
                title = (await anchor.inner_text()).strip()
                if not href or not title:
                    continue

                parsed = urllib.parse.urlparse(href)
                host = parsed.hostname or ''

                # Skip the engine's own navigation/ad links and duplicates.
                if any(host_part in host for host_part in engine_hosts):
                    continue
                if host in seen:
                    continue
                seen.add(host)

                snippet = ''
                aria_label = await anchor.get_attribute('aria-label')
                if aria_label:
                    snippet = aria_label.strip()

                results.append(SearchResult(link=href, title=title, snippet=snippet))
                if len(results) >= count:
                    break
        finally:
            await browser.close()

    if filter_list:
        results = get_filtered_results([r.model_dump() for r in results], filter_list)
        results = [SearchResult(**r) for r in results]

    return results

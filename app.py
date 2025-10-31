import os
import sys
import time
import logging
from threading import Thread, Lock
from typing import Optional, List, Dict, Any

import prawcore
from flask import Flask, render_template, request, make_response, redirect, url_for, jsonify
from flask_caching import Cache

from predictor_logic import BannerManager, get_community_sentiment_score

app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

SENTIMENT_LOCK_TIMEOUT = 60 * 60 * 4  # 4 hours (keep lock for full cache lifetime)
CACHE_TIMEOUT_SENTIMENT = 60 * 60 * 4  # 4 hours

GLOBAL_SENTIMENT_LOCK_KEY = "sentiment_global_lock"

app.config.from_mapping({
    "DEBUG": True,
    "CACHE_TYPE": "SimpleCache",
    "CACHE_DEFAULT_TIMEOUT": 3600
})
cache = Cache(app)

start_thread_lock = Lock()  # prevents race starting the worker thread (per-process)
sentiment_thread: Optional[Thread] = None  # holds Thread instance when running (per-process)


def _is_global_sentiment_running() -> bool:
    global sentiment_thread
    try:
        if sentiment_thread is not None and sentiment_thread.is_alive():
            return True
    except Exception:
        logger.exception("Error checking local sentiment thread status; falling back to cache lock check.")
    return cache.get(GLOBAL_SENTIMENT_LOCK_KEY) is not None


def _try_acquire_global_sentiment_lock() -> bool:
    try:
        if cache.get(GLOBAL_SENTIMENT_LOCK_KEY):
            return False
        cache.set(GLOBAL_SENTIMENT_LOCK_KEY, True, timeout=CACHE_TIMEOUT_SENTIMENT)
        return True
    except Exception:
        logger.exception("Failed to set global sentiment cache lock.")
        return False


def _release_global_sentiment_lock():
    try:
        cache.delete(GLOBAL_SENTIMENT_LOCK_KEY)
    except Exception:
        logger.exception("Failed to delete global sentiment cache lock.")


def _cache_sentiment_data(unit_key: str, data: dict):
    try:
        cache.set(f"sentiment_data:{unit_key}", data, timeout=CACHE_TIMEOUT_SENTIMENT)
    except Exception:
        logger.exception("Failed to cache sentiment data for %s", unit_key)


def _get_cached_sentiment_data(unit_key: str):
    try:
        return cache.get(f"sentiment_data:{unit_key}")
    except Exception:
        logger.exception("Failed to fetch cached sentiment data for %s", unit_key)
        return None


def update_all_sentiments_background():
    """
    Compute sentiment for each banner and write incremental results to cache.
    This function assumes the cache lock has already been set (owner).
    """
    global sentiment_thread
    logger.info("[THREAD] Global sentiment worker started.")
    try:
        manager = get_banner_manager()
        total = len(manager.merged_banners) if manager and getattr(manager, "merged_banners", None) else 0

        for idx, banner in enumerate(manager.merged_banners, start=1):
            unit_key = " ".join(banner.units) if hasattr(banner, "units") else getattr(banner, "id", str(idx))
            score_count = None
            try:
                score_count = get_community_sentiment_score(unit_key)
            except prawcore.exceptions.TooManyRequests:
                logger.exception("Failed sentiment for %s", unit_key)
                time.sleep(300)

            if isinstance(score_count, tuple) and len(score_count) >= 2:
                score, count = score_count[0], score_count[1]
            elif isinstance(score_count, dict):
                score = score_count.get("score")
                count = score_count.get("count", 0)
            else:
                score = score_count
                count = 0

            data = {'score': score if score is not None else 'N/A', 'count': int(count or 0)}
            _cache_sentiment_data(unit_key, data)
            logger.info("[%d/%d] Updated %s: %s", idx, total, unit_key, data)
        logger.info("[THREAD] Global sentiment worker finished successfully.")
    except Exception:
        logger.exception("[THREAD ERROR] Unhandled exception in sentiment worker")
    finally:
        try:
            _release_global_sentiment_lock()
            logger.info("[THREAD] Global lock released.")
        except Exception:
            logger.exception("[THREAD] Error releasing global lock.")


@cache.memoize(timeout=3600)
def get_banner_manager() -> BannerManager:
    """
    Load or construct BannerManager and cache the instance for repeated requests.
    The function must return a BannerManager object with at least:
      - merged_banners attribute (iterable of banner objects)
      - get_filtered_banners(search_query) method
    """
    start_time = time.time()
    logger.info("Starting banner parsing (cache-miss)...")
    manager = BannerManager()
    try:
        manager.load_data()
    except Exception:
        logger.exception("Error loading banner manager data.")
    end_time = time.time()
    logger.info("Parsing completed in %.2f seconds.", end_time - start_time)
    return manager


@app.route('/')
def index():
    try:
        manager = get_banner_manager()
        search_query = request.args.get('search', '')
        theme = request.cookies.get('theme', 'light')
        filtered_banners = manager.get_filtered_banners(search_query)
        return render_template(
            'index.html',
            banners=filtered_banners,
            search_query=search_query,
            theme=theme,
            total_banners=len(manager.merged_banners)
        )
    except Exception:
        logger.exception("Error rendering index.")
        return "Internal server error", 500


@app.route('/search-api')
def search_api():
    try:
        manager = get_banner_manager()
        search_query = request.args.get('search', '')
        filtered_banners = manager.get_filtered_banners(search_query)
        return render_template(
            'partials/table_rows.html',
            banners=filtered_banners
        )
    except Exception:
        logger.exception("Error in search-api.")
        return "Internal server error", 500


@app.route('/set-theme/<theme_name>')
def set_theme(theme_name: str):
    if theme_name not in ('light', 'dark'):
        theme_name = 'light'

    response = make_response(redirect(request.referrer or url_for('index')))
    response.set_cookie('theme', theme_name, max_age=60 * 60 * 24 * 365)
    return response


@app.route('/api/sentiment')
def get_sentiment_scores():
    """
    Return currently cached sentiment data (partial) and ensure exactly one
    background worker is started (per-process) to fill missing data.
    """
    global sentiment_thread

    try:
        manager = get_banner_manager()
    except Exception:
        logger.exception("Failed to get banner manager for sentiment API.")
        return jsonify({"running": False, "count_cached": 0, "data": []}), 500

    sentiment_results: List[Dict[str, Any]] = []

    for banner in manager.merged_banners:
        unit_key = " ".join(banner.units)
        cached_data = _get_cached_sentiment_data(unit_key)
        if cached_data:
            sentiment_results.append({'units': unit_key, **cached_data})

    with start_thread_lock:
        already_running = _is_global_sentiment_running()
        if not already_running:
            got_cache_lock = _try_acquire_global_sentiment_lock()
            if got_cache_lock:
                sentiment_thread = Thread(
                    target=update_all_sentiments_background,
                    name="GlobalSentimentWorker",
                    daemon=True
                )
                sentiment_thread.start()
                logger.info("Started global sentiment background thread.")
            else:
                logger.info("Cache lock acquired by another actor; not starting thread.")
        else:
            logger.debug("Sentiment update already running, skipping new one.")

    return jsonify({
        "running": _is_global_sentiment_running(),
        "count_cached": len(sentiment_results),
        "data": sentiment_results
    })


if __name__ == '__main__':
    is_debug = os.environ.get("DEBUG", "0").lower() in ("true", "1", "t")
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=is_debug, host=host, port=port)

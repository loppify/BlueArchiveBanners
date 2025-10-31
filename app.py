# app.py
# File path: ./app.py

import sys
import os
import time
import threading
from threading import Thread, Lock

from flask import Flask, render_template, request, make_response, redirect, url_for, jsonify
from flask_caching import Cache

from predictor_logic import BannerManager, get_community_sentiment_score

app = Flask(__name__)

# ---- Configuration ----
SENTIMENT_LOCK_TIMEOUT = 60 * 60 * 4         # 4 hours (keep lock for full cache lifetime)
CACHE_TIMEOUT_SENTIMENT = 60 * 60 * 4        # 4 hours
GLOBAL_SENTIMENT_LOCK_KEY = "sentiment_global_lock"

app.config.from_mapping({
    "DEBUG": True,
    "CACHE_TYPE": "SimpleCache",
    "CACHE_DEFAULT_TIMEOUT": 3600
})
cache = Cache(app)

# ---- In-process synchronization primitives ----
start_thread_lock = Lock()     # prevents race starting the worker thread (per-process)
sentiment_thread = None       # holds Thread instance when running (per-process)


# ---- Cache helpers ----
def _is_global_sentiment_running() -> bool:
    """Return True if cache lock exists or in-process thread is alive."""
    global sentiment_thread
    # prefer in-process thread check first (fast)
    if sentiment_thread is not None and sentiment_thread.is_alive():
        return True
    # fallback to cache-based lock (helps across requests/process restart)
    return cache.get(GLOBAL_SENTIMENT_LOCK_KEY) is not None


def _try_acquire_global_sentiment_lock() -> bool:
    """
    Try to mark the global cache lock.
    Returns True if we set the cache lock (i.e. we "own" the job), False otherwise.
    This is not atomic across processes with SimpleCache, but combined with start_thread_lock
    it prevents duplicate threads within this process.
    """
    if cache.get(GLOBAL_SENTIMENT_LOCK_KEY):
        return False
    # set lock for the full cache duration to avoid premature expiry during long runs
    cache.set(GLOBAL_SENTIMENT_LOCK_KEY, True, timeout=CACHE_TIMEOUT_SENTIMENT)
    return True


def _release_global_sentiment_lock():
    cache.delete(GLOBAL_SENTIMENT_LOCK_KEY)


def _cache_sentiment_data(unit_key: str, data: dict):
    cache.set(f"sentiment_data:{unit_key}", data, timeout=CACHE_TIMEOUT_SENTIMENT)


def _get_cached_sentiment_data(unit_key: str):
    return cache.get(f"sentiment_data:{unit_key}")


# ---- Background worker ----
def update_all_sentiments_background():
    """
    Compute sentiment for each banner and write incremental results to cache.
    This function assumes the cache lock has already been set (owner).
    """
    print("[THREAD] Global sentiment worker started.")
    try:
        manager = get_banner_manager()

        total = len(manager.merged_banners)
        for idx, banner in enumerate(manager.merged_banners, start=1):
            unit_key = " ".join(banner.units)
            try:
                # compute score
                score, count = get_community_sentiment_score(unit_key)
                data = {'score': score if score is not None else 'N/A', 'count': count or 0}
                _cache_sentiment_data(unit_key, data)
                print(f"[{idx}/{total}] Updated {unit_key}: {data}")
            except Exception as e:
                print(f"[ERROR] Failed sentiment for {unit_key}: {e}", file=sys.stderr)

        print("[THREAD] Global sentiment worker finished successfully.")
    except Exception as e:
        print(f"[THREAD ERROR] Unhandled exception in sentiment worker: {e}", file=sys.stderr)
    finally:
        # release the cache lock so next full refresh can be started after TTL if desired
        _release_global_sentiment_lock()
        print("[THREAD] Global lock released.")


# ---- Cached Banner Manager ----
@cache.memoize(timeout=3600)
def get_banner_manager():
    start_time = time.time()
    print("ЗАПУСК ПАРСИНГУ (КЕШ ПРОБИТО)...")
    manager = BannerManager()
    manager.load_data()
    end_time = time.time()
    print(f"Парсинг завершено за {end_time - start_time:.2f} секунд.")
    return manager


# ---- Routes ----
@app.route('/')
def index():
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


@app.route('/search-api')
def search_api():
    manager = get_banner_manager()
    search_query = request.args.get('search', '')
    filtered_banners = manager.get_filtered_banners(search_query)

    return render_template(
        'partials/table_rows.html',
        banners=filtered_banners
    )


@app.route('/set-theme/<theme_name>')
def set_theme(theme_name):
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

    manager = get_banner_manager()
    sentiment_results = []

    for banner in manager.merged_banners:
        unit_key = " ".join(banner.units)
        cached_data = _get_cached_sentiment_data(unit_key)
        if cached_data:
            sentiment_results.append({'units': unit_key, **cached_data})

    # Serialize thread-creation to avoid race when many requests arrive simultaneously
    with start_thread_lock:
        already_running = _is_global_sentiment_running()
        if not already_running:
            # Try to mark cache lock (so other processes/requests see it)
            got_cache_lock = _try_acquire_global_sentiment_lock()
            if got_cache_lock:
                # start worker and keep reference in global variable
                sentiment_thread = Thread(
                    target=update_all_sentiments_background,
                    name="GlobalSentimentWorker",
                    daemon=True
                )
                sentiment_thread.start()
                print("[INFO] Started global sentiment background thread.")
            else:
                print("[INFO] Cache lock acquired by another actor; not starting thread.")
        else:
            print("[INFO] Sentiment update already running, skipping new one.")

    return jsonify({
        "running": _is_global_sentiment_running(),
        "count_cached": len(sentiment_results),
        "data": sentiment_results
    })


@app.route('/status')
def status():
    active_threads = [t.name for t in threading.enumerate()]
    return jsonify({
        "status": "OK",
        "active_threads_count": len(active_threads),
        "active_threads": active_threads,
        "is_global_sentiment_running": _is_global_sentiment_running()
    })


@app.route('/admin/clear-cache')
def clear_cache_route():
    cache.clear()
    print("[CACHE] Cleared manually.")
    return jsonify({"ok": True})


@app.route('/cache-admin')
def cache_admin():
    manager = get_banner_manager()
    banner_keys = [" ".join(b.units) for b in manager.merged_banners]

    cache_status = []

    for unit_key in banner_keys:
        sentiment_key = f'sentiment_data:{unit_key}'
        sentiment_data = cache.get(sentiment_key)
        lock_active = cache.get(GLOBAL_SENTIMENT_LOCK_KEY) is not None

        status = {
            'unit': unit_key,
            'is_cached': sentiment_data is not None,
            'is_locked': lock_active,
            'score': sentiment_data.get('score', 'N/A') if isinstance(sentiment_data, dict) else 'N/A',
        }
        cache_status.append(status)

    return jsonify(cache_status)


if __name__ == '__main__':
    is_debug = os.environ.get("DEBUG", "0").lower() in ("true", "1", "t")
    host = '0.0.0.0'
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=is_debug, host=host, port=port)

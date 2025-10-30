from flask import Flask, render_template, request, make_response, redirect, url_for
from predictor_logic import BannerManager
from flask_caching import Cache
import time, os

app = Flask(__name__)

config = {
    "DEBUG": True,
    "CACHE_TYPE": "SimpleCache",
    "CACHE_DEFAULT_TIMEOUT": 3600
}
app.config.from_mapping(config)
cache = Cache(app)


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
    response.set_cookie('theme', theme_name, max_age=60 * 60 * 24 * 365)  # 1 year
    return response


@cache.memoize(timeout=3600)
def get_banner_manager():
    start_time = time.time()
    print("ЗАПУСК ПАРСИНГУ (КЕШ ПРОБИТО)...")

    manager = BannerManager()
    manager.load_data()

    end_time = time.time()
    print(f"Парсинг завершено за {end_time - start_time:.2f} секунд.")
    return manager


if __name__ == '__main__':
    is_debug = os.environ.get("DEBUG", "0").lower() in ("true", "1", "t")
    host = '0.0.0.0'
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=is_debug, host=host, port=port)

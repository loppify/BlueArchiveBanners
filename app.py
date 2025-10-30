from flask import Flask, render_template, request, make_response, redirect, url_for
from predictor_logic import BannerManager

app = Flask(__name__)

print("Initializing BannerManager... This may take a moment.")
manager = BannerManager()
manager.load_data()
print("Data loaded. Flask server is ready.")


@app.route('/')
def index():
    theme = request.cookies.get('theme', 'light')

    return render_template(
        'index.html',
        banners=manager.merged_banners,
        search_query="",
        theme=theme,
        total_banners=len(manager.merged_banners)
    )


@app.route('/search-api')
def search_api():
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


if __name__ == '__main__':
    app.run(debug=True)

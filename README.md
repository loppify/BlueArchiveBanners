# Blue Archive Banner Analysis & Global Prediction Dashboard

![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)
![Flask](https://img.shields.io/badge/Web-Flask-lightgray)
![PRAW](https://img.shields.io/badge/Data_Source-Reddit_API-orange)
![Bootstrap](https://img.shields.io/badge/Design-Bootstrap_5-purple)
![License](https://img.shields.io/badge/License-MIT-green)

An interactive, server-side rendered (SSR) Flask application designed for the Blue Archive community. It aggregates banner data from Asia (JP/KR) and Global servers, predicts future Global release dates, and provides a real-time **Community Sentiment Score** by analyzing discussions on Reddit. Available on [https://blue-archive-banners.onrender.com](https://blue-archive-banners.onrender.com)

## 🚀 Key Features

* **Global Date Prediction:** Automatically calculates the time offset between Asia and Global servers and projects future release dates for unreleased banners.
* **Asynchronous Sentiment Analysis (NLP):** Utilizes the Reddit API (PRAW) and **VADER/TextBlob** models to analyze recent threads and comments, providing a numerical **Community Score** for each character.
    * **Contextual Filtering:** The analysis logic filters out "waifu factor" and non-gameplay terms, ensuring the score reflects objective meta-relevance (damage, worth, utility).
* **Robust Caching & Stability:** Implements `Flask-Caching` with a custom **Cache Lock** mechanism to prevent multiple threads/processes from hitting the Reddit API simultaneously during cache updates. This guarantees stability and avoids rate limits.
* **Modern UI/UX:**
    * Fully **responsive** design using pure Bootstrap 5 for mobile and desktop viewing.
    * **Dynamic Search:** Filters the table instantly without page reload using client-side JavaScript and a Flask API endpoint (`/search-api`).
    * **Theming:** Supports persistent Light and Dark mode switching.

## 🔬 How the Prediction Logic Works

1.  **Data Ingestion:** The app scrapes the Blue Archive Wiki for all Asia and Global banner data.
2.  **Offset Calculation:** The manager calculates the time difference (`timedelta`) between a set of known matching banners across both servers.
3.  **Prediction:** This calculated offset is applied to all unreleased Asia banners to predict their Global launch date.
4.  **Community Score Worker:** When a user opens the page, the application checks the cache for the Sentiment Score:
    * If the cache is **stale** or **empty**, a new Python `Thread` is started in the background.
    * This thread acquires a **Cache Lock**, prevents any other user or process from starting the same lengthy task, scrapes Reddit, calculates the score, and saves the final result to the cache.
    * The user's frontend constantly polls (`/api/sentiment`) until the data is ready, providing an instant update once the background process completes.

## 🛠️ Tech Stack

* **Backend:** Python, Flask, Gunicorn
* **Caching & Stability:** `Flask-Caching`, `threading`
* **Scraping & NLP:** `requests`, `BeautifulSoup4`, `praw`, `vaderSentiment`
* **Frontend:** HTML5, CSS3, JavaScript (AJAX), Bootstrap 5
* **Hosting:** Render (PaaS)

## ⚙️ Setup and Running

1.  **Prerequisites:** You need a registered Reddit API application (`script` type) and its credentials.
2.  **Clone the repository:**
    ```bash
    git clone [https://github.com/loppify/BlueArchiveBanners.git](https://github.com/loppify/BlueArchiveBanners.git)
    cd BlueArchiveBanners
    ```

3.  **Setup Environment:**
    ```bash
    python -m venv .venv
    .\.venv\Scripts\activate
    
    # Install dependencies
    pip install -r requirements.txt
    ```

4.  **Configure Secrets:**
    Create a `config.py` file in the root directory with your credentials:
    ```python
    # config.py (DO NOT COMMIT!)
    REDDIT_CLIENT_ID = "YOUR_CLIENT_ID"
    REDDIT_CLIENT_SECRET = "YOUR_SECRET"
    REDDIT_USER_AGENT = "BlueArchivePredictor by /u/YourRedditUsername"
    USERNAME = "YourRedditUsername"
    PASSWORD = "YourRedditPassword"
    ```

5.  **Run the app locally:**
    ```bash
    # Run in production-like environment (recommended)
    python -m waitress app:app
    
    # Or, if using the debugger:
    python app.py
    ```

6.  Open your browser and navigate to `http://127.0.0.1:5000/`.

## 📄 License

This project is licensed under the MIT License.

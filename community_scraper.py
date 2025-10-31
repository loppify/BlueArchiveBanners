import os
import re
import sys
import time
from typing import List, Tuple, Optional

import praw
from textblob import TextBlob
from praw.models import Submission


TARGET_SUBREDDIT = "BlueArchive"
POST_LIMIT_PER_UNIT = 30
COMMENT_DEPTH = 5


def get_auth_details():
    client_id = os.environ.get("REDDIT_CLIENT_ID")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET")

    if client_id and client_secret:
        return client_id, client_secret, os.environ.get("REDDIT_USER_AGENT", "BlueArchivePredictor"), \
            os.environ.get("REDDIT_USERNAME"), os.environ.get("REDDIT_PASSWORD")
    else:
        try:
            from config import REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT, USERNAME, PASSWORD

            return REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT, USERNAME, PASSWORD

        except ImportError:
            print("FATAL: Reddit API keys missing. Check Render ENV or local config.py.", file=sys.stderr)
            sys.exit(1)


CLIENT_ID, CLIENT_SECRET, USER_AGENT, REDDIT_USERNAME, REDDIT_PASSWORD = get_auth_details()

try:
    reddit = praw.Reddit(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        user_agent=USER_AGENT,
        username=REDDIT_USERNAME,
        password=REDDIT_PASSWORD
    )
    print(f"✅ Reddit PRAW client initialized.")
except Exception as e:
    print(f"❌ PRAW initialization failed: {e}", file=sys.stderr)
    sys.exit(1)


def _get_relevant_submissions(unit_name: str) -> List[Submission]:
    search_query = f'"{unit_name}" OR {unit_name.split()[0]} tier guide worth'

    submissions = reddit.subreddit(TARGET_SUBREDDIT).search(
        query=search_query,
        sort='relevance',
        limit=POST_LIMIT_PER_UNIT
    )
    return list(submissions)


def _analyze_comments(submission: Submission) -> Tuple[float, int]:
    submission.comments.replace_more(limit=COMMENT_DEPTH)

    total_polarity = 0
    comment_count = 0

    for comment in submission.comments.list():
        if comment.body and not comment.body.startswith('The body of the comment is'):
            analysis = TextBlob(comment.body)
            if abs(analysis.sentiment.polarity) > 0.1:
                total_polarity += analysis.sentiment.polarity
                comment_count += 1

    return total_polarity, comment_count


def get_community_sentiment_score(unit_name: str) -> Tuple[Optional[float], int]:
    """Основна функція: збирає дані, аналізує та повертає кінцевий рейтинг."""

    unit_name_cleaned = re.sub(r'\(.*?\)', '', unit_name).strip()

    submissions = _get_relevant_submissions(unit_name_cleaned)

    if not submissions:
        print(f"-> No recent relevant Reddit submissions found for {unit_name}.")
        return None, 0

    overall_polarity = 0
    overall_count = 0

    for sub in submissions:
        print(f"-> Analyzing thread: {sub.title} ({sub.url})")
        thread_polarity, thread_count = _analyze_comments(sub)

        overall_polarity += thread_polarity
        overall_count += thread_count

        time.sleep(0.5)

    if overall_count == 0:
        return None, 0

    average_score = overall_polarity / overall_count
    return round(average_score, 3), overall_count

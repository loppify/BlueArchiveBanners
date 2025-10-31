import os
import re
import sys
import time
from typing import List, Tuple, Optional

import praw
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from praw.models import Submission

TARGET_SUBREDDIT = "BlueArchive"
POST_LIMIT_PER_UNIT = 30
COMMENT_DEPTH = 5
ASSESSMENT_KEYWORDS = ['tier', 'worth', 'guide', 'review', 'pull']
AESTHETIC_FILTER_KEYWORDS = [
    'cute', 'pretty', 'waifu', 'design', 'gorgeous', 'art',
    'best girl', 'adorable', 'charming', 'love', 'favorite'
]
GAMEPLAY_FOCUS_KEYWORDS = [
    'dps', 'skill', 'raid', 'meta', 'pve', 'pvp', 'utility', 'boss',
    'damage', 'heal', 'tank', 'ex skill', 'skill point'
]
VADER_CUSTOM_LEXICON = {
    'shreds': 3.5,
    'broken': 3.0,
    'gimped': -3.0,
    'trash': -3.5,
    'must pull': 3.0,
    'whale': -2.0,
}

analyzer = SentimentIntensityAnalyzer()
analyzer.lexicon.update(VADER_CUSTOM_LEXICON)


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
    submissions = []
    keywords_part = " OR ".join(ASSESSMENT_KEYWORDS)

    query_exact = f'"{unit_name}" AND ({keywords_part})'

    print(f"-> Searching EXACT: {query_exact}")
    submissions_exact = reddit.subreddit(TARGET_SUBREDDIT).search(
        query=query_exact,
        sort='hot',
        time_filter='year',
        limit=POST_LIMIT_PER_UNIT
    )
    submissions.extend(list(submissions_exact))

    if len(submissions) < 5:
        base_name = unit_name.split('(')[0].strip()
        query_base = f'"{base_name}" AND ({keywords_part})'

        print(f"-> Searching BASE: {query_base}")
        submissions_base = reddit.subreddit(TARGET_SUBREDDIT).search(
            query=query_base,
            sort='hot',
            time_filter='year',
            limit=POST_LIMIT_PER_UNIT
        )

        unique_submissions = set(submissions)
        for sub in submissions_base:
            if sub not in unique_submissions:
                submissions.append(sub)
                unique_submissions.add(sub)
    time.sleep(0.5)
    return submissions


def _analyze_comments(submission: Submission) -> Tuple[float, int]:
    submission.comments.replace_more(limit=COMMENT_DEPTH)

    total_polarity = 0
    comment_count = 0

    seen_comments = set()

    for comment in submission.comments.list():
        if comment.id in seen_comments or comment.body is None:
            continue

        seen_comments.add(comment.id)

        if comment.body and len(comment.body) > 10 and not comment.body.startswith('The body of the comment is'):
            is_gameplay_context = any(kw in comment.body.lower() for kw in GAMEPLAY_FOCUS_KEYWORDS)

            if not is_gameplay_context:
                continue

            is_aesthetic = any(keyword in comment.body.lower() for keyword in AESTHETIC_FILTER_KEYWORDS)
            if is_aesthetic:
                continue

            vs = analyzer.polarity_scores(comment.body)
            weight = comment.score if comment.score > 0 else 1

            if abs(vs['compound']) > 0.1:
                total_polarity += vs['compound'] * weight
                comment_count += weight

    return total_polarity, comment_count


def get_community_sentiment_score(unit_name: str) -> Tuple[Optional[float], int]:
    """Основна функція: збирає дані, аналізує та повертає кінцевий рейтинг."""

    submissions = _get_relevant_submissions(unit_name)

    if not submissions:
        print(f"-> No recent relevant Reddit submissions found for {unit_name}.")
        return None, 0

    overall_polarity = 0
    overall_count = 0

    for sub in submissions:
        # if 'daily questions megathread' in sub.title.lower() or 'daily advice megathread' in sub.title.lower():
        #     print(f"-> Skipping MegaThread: {sub.title}")
        #     continue

        print(f"-> Analyzing thread: {sub.title} ({sub.url})")
        thread_polarity, thread_count = _analyze_comments(sub)

        overall_polarity += thread_polarity
        overall_count += thread_count

        time.sleep(0.5)

    if overall_count == 0:
        return None, 0

    average_score = overall_polarity / overall_count
    return round(average_score, 3), overall_count

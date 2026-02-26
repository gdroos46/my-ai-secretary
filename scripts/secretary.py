"""
AI Secretary - PRチェック & レビュー支援
Claude APIを使ったPR差分の要約とリスク判定機能付き。
"""

import os
import requests
import yaml
from datetime import datetime, timezone

# GitHub & Slack 設定
GH_TOKEN = os.getenv("GH_TOKEN")
SLACK_URL = os.getenv("SLACK_URL")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")


def get_my_username():
    """認証ユーザーのGitHubユーザー名を取得"""
    url = "https://api.github.com/user"
    headers = {"Authorization": f"token {GH_TOKEN}"}
    response = requests.get(url, headers=headers)
    data = response.json()
    return data.get("login")


def get_pull_requests(repo, creator=None):
    """オープンなPR一覧を取得（creatorでクライアント側フィルタ）"""
    url = f"https://api.github.com/repos/{repo}/pulls"
    headers = {"Authorization": f"token {GH_TOKEN}"}
    response = requests.get(url, headers=headers)
    data = response.json()
    # APIエラー時は辞書が返る（例: {"message": "Not Found"}）
    if isinstance(data, dict):
        print(f"⚠️ {repo}: API error - {data.get('message', 'Unknown error')}")
        return []
    # ユーザー名でフィルタ
    if creator:
        data = [pr for pr in data if pr.get("user", {}).get("login") == creator]
    return data


def get_pr_diff(repo, pr_number):
    """PRの差分を取得"""
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    headers = {
        "Authorization": f"token {GH_TOKEN}",
        "Accept": "application/vnd.github.v3.diff",
    }
    response = requests.get(url, headers=headers)
    return response.text



def summarize_with_claude(diff_text, pr_title):
    """Claude APIでPRの差分を要約"""
    if not ANTHROPIC_API_KEY:
        return None

    # 差分が大きすぎる場合は先頭を切り取る（トークン節約）
    max_diff_chars = 12000
    truncated = diff_text[:max_diff_chars]
    if len(diff_text) > max_diff_chars:
        truncated += "\n... (以下省略)"

    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 300,
        "messages": [
            {
                "role": "user",
                "content": f"""以下のPR（タイトル: {pr_title}）の差分を分析し、日本語で3行以内に要約してください。
- 1行目: 何を変更したか
- 2行目: なぜ変更したか（推測で可）
- 3行目: 注意点やレビュー時の確認ポイント

差分:
```
{truncated}
```""",
            }
        ],
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data["content"][0]["text"]
    except Exception as e:
        print(f"⚠️ Claude API エラー: {e}")
        return None


def get_pr_status(pr):
    """PRのステータスを判定"""
    if pr["draft"]:
        return "draft"

    # レビュー状態の取得
    reviews_url = pr["_links"]["self"]["href"] + "/reviews"
    reviews = requests.get(
        reviews_url, headers={"Authorization": f"token {GH_TOKEN}"}
    ).json()
    if isinstance(reviews, list) and any(r["state"] == "APPROVED" for r in reviews):
        return "approved"

    # reviewerがついているか
    if pr.get("requested_reviewers"):
        return "in_review"

    return "no_reviewer"


def check_all_projects():
    """全プロジェクトのPRをチェック（自分が作ったPRのみ）"""
    with open("config/projects.yml", "r") as f:
        config = yaml.safe_load(f)

    my_username = config.get("github_username")
    print(f"👤 対象ユーザー: {my_username}")

    messages = ["🌙 *夜のPRチェック報告です*"]

    for pjt in config["projects"]:
        repo = pjt["repo"]
        name = pjt["name"]
        prs = get_pull_requests(repo, creator=my_username)

        if not prs:
            messages.append(f"✅ *{name}*: オープンPRなし。")
            continue

        # ステータスごとに分類
        approved = []
        in_review = []
        draft = []
        no_reviewer = []

        for pr in prs:
            status = get_pr_status(pr)
            url = pr["html_url"]
            title = pr["title"]
            line = f"<{url}|{title}>"

            if status == "approved":
                approved.append(line)
            elif status == "in_review":
                in_review.append(line)
            elif status == "draft":
                draft.append(line)
            else:
                no_reviewer.append(line)

        messages.append(f"\n📂 *{name}*")
        if approved:
            messages.append("  🍏 *マージ待ち*")
            for line in approved:
                messages.append(f"    ・ {line}")
        if in_review:
            messages.append("  🔵 *レビュー中*")
            for line in in_review:
                messages.append(f"    ・ {line}")
        if no_reviewer:
            messages.append("  🔴 *レビュー未依頼*")
            for line in no_reviewer:
                messages.append(f"    ・ {line}")
        if draft:
            messages.append("  🟡 *Draft*")
            for line in draft:
                messages.append(f"    ・ {line}")

    # Slack送信
    full_message = "\n".join(messages)
    print(full_message)

    payload = {"text": full_message}
    requests.post(SLACK_URL, json=payload)


if __name__ == "__main__":
    check_all_projects()

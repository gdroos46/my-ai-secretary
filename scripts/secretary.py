import os
import requests
import yaml
from datetime import datetime, timezone

# GitHub & Slack 設定
GH_TOKEN = os.getenv("GH_TOKEN")
SLACK_URL = os.getenv("SLACK_URL")

def get_pull_requests(repo):
    url = f"https://api.github.com/repos/{repo}/pulls"
    headers = {"Authorization": f"token {GH_TOKEN}"}
    response = requests.get(url, headers=headers)
    return response.json()

def check_all_projects():
    # config/projects.yml を読み込む
    with open('config/projects.yml', 'r') as f:
        config = yaml.safe_load(f)

    messages = ["🌙 *夜のPRチェック報告です*"]

    for pjt in config['projects']:
        repo = pjt['repo']
        name = pjt['name']
        prs = get_pull_requests(repo)

        if not prs:
            messages.append(f"✅ *{name}*: 本日のPRはありません。")
            continue

        pjt_status = f"📂 *{name}* の状況:"
        messages.append(pjt_status)

        for pr in prs:
            title = pr['title']
            url = pr['html_url']
            is_draft = pr['draft']

            # レビュー状態の取得
            reviews_url = pr['_links']['self']['href'] + "/reviews"
            reviews = requests.get(reviews_url, headers={"Authorization": f"token {GH_TOKEN}"}).json()
            is_approved = any(r['state'] == 'APPROVED' for r in reviews)

            if is_draft:
                messages.append(f"  ・ 🟡 Draft: <{url}|{title}> (Readyにしてね)")
            elif is_approved:
                messages.append(f"  ・ 🍏 *Approved!*: <{url}|{title}> (マージ忘れ？)")
            else:
                messages.append(f"  ・ 🔵 Review中: <{url}|{title}> (催促する？)")

    # Slack送信
    payload = {"text": "\n".join(messages)}
    requests.post(SLACK_URL, json=payload)

if __name__ == "__main__":
    check_all_projects()

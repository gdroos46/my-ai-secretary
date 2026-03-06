"""
Daily Task Planner - AI秘書のスケジューリング担当
GitHub Issueから this_week ラベルのタスクを収集し、
今日のタスクをSlackに通知する。
"""

import os
import json
import yaml
import requests
from datetime import datetime, timedelta

# 設定
GH_TOKEN = os.getenv("GH_TOKEN")
SLACK_URL = os.getenv("SLACK_URL")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

LABEL = "todo"

# ポイント換算（Issueラベルで判定）
SIZE_POINTS = {"size/S": 1, "size/M": 3, "size/L": 5}
DEFAULT_POINTS = 3
MAX_POINTS_PER_DAY = 6


def load_config():
    with open("config/projects.yml", "r") as f:
        return yaml.safe_load(f)


def fetch_issues(repo, label):
    """リポジトリからthis_weekラベルのオープンIssueを取得"""
    url = f"https://api.github.com/repos/{repo}/issues"
    headers = {"Authorization": f"token {GH_TOKEN}"}
    params = {
        "labels": label,
        "state": "open",
        "per_page": 100,
    }
    response = requests.get(url, headers=headers, params=params)
    data = response.json()

    if isinstance(data, dict):
        print(f"⚠️ {repo}: API error - {data.get('message', 'Unknown error')}")
        return []

    # PRを除外（IssueAPIはPRも返す）
    return [issue for issue in data if "pull_request" not in issue]


def get_issue_size(issue):
    """Issueのラベルからサイズポイントを取得"""
    labels = [l["name"] for l in issue.get("labels", [])]
    for label, points in SIZE_POINTS.items():
        if label in labels:
            return points
    return DEFAULT_POINTS


def get_issue_priority(issue):
    """Issueのラベルから優先度を取得"""
    labels = [l["name"] for l in issue.get("labels", [])]
    for label in labels:
        if label.startswith("P") and len(label) == 2 and label[1].isdigit():
            return int(label[1])
    return 5  # ラベルなしは最低優先


def collect_all_issues(config):
    """全プロジェクトからthis_weekのIssueを収集"""
    all_issues = []
    for pjt in config["projects"]:
        repo = pjt["repo"]
        name = pjt["name"]
        issues = fetch_issues(repo, LABEL)
        print(f"📂 {name}: {len(issues)}件のIssue")

        for issue in issues:
            all_issues.append({
                "project": name,
                "repo": repo,
                "number": issue["number"],
                "title": issue["title"],
                "url": issue["html_url"],
                "priority": get_issue_priority(issue),
                "points": get_issue_size(issue),
                "labels": [l["name"] for l in issue.get("labels", [])],
            })

    return all_issues


def get_remaining_weekdays():
    """今日から金曜日までの残り平日リストを返す"""
    today = datetime.now()
    days = []
    current = today
    # 今日が土日なら月曜始まり
    if current.weekday() >= 5:
        days_until_monday = 7 - current.weekday()
        current = current + timedelta(days=days_until_monday)

    while current.weekday() < 5:  # 月〜金
        days.append(current.strftime("%Y-%m-%d (%a)"))
        current += timedelta(days=1)

    return days


def plan_tasks(issues):
    """優先度順にタスクを残り平日に割り振る"""
    days = get_remaining_weekdays()
    if not days:
        return {}

    # 優先度 → ポイント小さい順でソート
    sorted_issues = sorted(issues, key=lambda t: (t["priority"], t["points"]))

    plan = {day: [] for day in days}
    day_points = {day: 0 for day in days}

    for task in sorted_issues:
        points = task["points"]
        assigned = False

        # 前半の日から順に空きを探す
        for day in days:
            if day_points[day] + points <= MAX_POINTS_PER_DAY:
                plan[day].append(task)
                day_points[day] += points
                assigned = True
                break

        # 全部埋まっていたら最も空いている日に
        if not assigned:
            min_day = min(days, key=lambda d: day_points[d])
            plan[min_day].append(task)
            day_points[min_day] += points

    return plan


def format_today_message(plan):
    """今日のタスクをSlackメッセージに整形"""
    today = datetime.now().strftime("%Y-%m-%d (%a)")

    messages = [f"☀️ *おはようございます！今日のタスクです*（{today}）"]

    today_tasks = plan.get(today, [])
    if not today_tasks:
        messages.append("📭 今日の予定タスクはありません。")
    else:
        for task in today_tasks:
            messages.append(
                f"  ・ `{task['project']}#{task['number']}` <{task['url']}|{task['title']}>"
            )
        messages.append("")
        messages.append("🤖 Claudeに任せたいIssueがあれば、GitHubで `claude` ラベルをつけてね")

    # 残りの日のサマリー
    other_days = {day: tasks for day, tasks in plan.items() if day != today and tasks}
    if other_days:
        messages.append("")
        messages.append("📅 *今週の残り*")
        for day, tasks in other_days.items():
            task_names = ", ".join(f"{t['project']}#{t['number']}" for t in tasks)
            messages.append(f"  {day}: {task_names}")

    return "\n".join(messages)


def save_plan(plan):
    """data/week_plan.json に保存"""
    today = datetime.now()
    _, week, _ = today.isocalendar()
    week_key = f"{today.year}-W{week:02d}"

    output = {"week": week_key, "updated": today.strftime("%Y-%m-%d %H:%M"), "plan": plan}

    os.makedirs("data", exist_ok=True)
    with open("data/week_plan.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)


def notify_slack(message):
    """Slackに通知"""
    if SLACK_URL:
        requests.post(SLACK_URL, json={"text": message})
    print(message)


def main():
    config = load_config()
    print("📋 GitHub Issueからタスク収集中...")

    issues = collect_all_issues(config)
    if not issues:
        notify_slack("☀️ *おはようございます！*\n📭 todo のIssueはありません。今週はフリーです！")
        return

    print(f"✅ 合計 {len(issues)}件のタスクを収集")

    plan = plan_tasks(issues)
    save_plan(plan)

    message = format_today_message(plan)
    notify_slack(message)


if __name__ == "__main__":
    main()

"""
Weekly Task Planner - AI秘書のスケジューリング担当
Gemini APIを使って、翌週の月〜金にタスクを最適に割り振る。
"""

import os
import json
import yaml
from datetime import datetime, timedelta
import google.generativeai as genai

# Gemini API 設定
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ポイント換算テーブル
ESTIMATE_POINTS = {"S": 1, "M": 3, "L": 5}
MAX_POINTS_PER_DAY = 6


def load_backlog():
    """data/tasks_backlog.yml からタスク一覧を読み込む"""
    with open("data/tasks_backlog.yml", "r") as f:
        data = yaml.safe_load(f)
    return data.get("backlog", [])


def get_next_week_dates():
    """翌週の月〜金の日付を返す"""
    today = datetime.now()
    # 次の月曜日を計算
    days_until_monday = (7 - today.weekday()) % 7
    if days_until_monday == 0:
        days_until_monday = 7
    next_monday = today + timedelta(days=days_until_monday)

    dates = {}
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    for i, name in enumerate(day_names):
        date = next_monday + timedelta(days=i)
        dates[name] = date.strftime("%Y-%m-%d")
    return dates, next_monday.isocalendar()


def build_prompt(backlog, dates):
    """Gemini に渡すプロンプトを生成"""
    tasks_text = ""
    for i, task in enumerate(backlog):
        points = ESTIMATE_POINTS.get(task["estimate"], 3)
        tasks_text += (
            f"  {i+1}. project: {task['project']}, "
            f"title: {task['title']}, "
            f"priority: {task['priority']}, "
            f"estimate: {task['estimate']} ({points}pt)\n"
        )

    dates_text = "\n".join(f"  - {name}: {date}" for name, date in dates.items())

    return f"""あなたはプロジェクトマネージャーです。
以下のタスクを翌週の月〜金に最適に割り振ってください。

【制約条件】
- 1日の合計負荷ポイントは最大{MAX_POINTS_PER_DAY}ポイント
- ポイント換算: S=1, M=3, L=5
- 優先度が高いもの(P0 > P1 > P2)は週の前半に配置
- 依存関係があれば考慮すること（タスク名から推測）
- すべてのタスクを割り振ること。ポイントが足りない場合は超過してでも割り振る

【タスク一覧】
{tasks_text}

【割り当て先の日付】
{dates_text}

【出力形式】
以下のJSON形式のみを出力してください。説明文は不要です。
{{
  "Monday": [
    {{"project": "...", "title": "...", "priority": "...", "estimate": "...", "points": N}}
  ],
  "Tuesday": [...],
  "Wednesday": [...],
  "Thursday": [...],
  "Friday": [...]
}}
"""


def generate_plan_with_gemini(prompt):
    """Gemini API を呼び出してタスク割り当てを生成"""
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-2.0-flash")

    response = model.generate_content(prompt)
    text = response.text.strip()

    # ```json ... ``` のフェンスを除去
    if text.startswith("```"):
        lines = text.split("\n")
        # 最初と最後のフェンス行を除去
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    return json.loads(text)


def generate_plan_fallback(backlog):
    """Gemini APIが使えない場合のローカルフォールバック"""
    # 優先度でソート (P0 > P1 > P2)
    priority_order = {"P0": 0, "P1": 1, "P2": 2}
    sorted_tasks = sorted(backlog, key=lambda t: priority_order.get(t["priority"], 9))

    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    plan = {day: [] for day in days}
    day_points = {day: 0 for day in days}

    for task in sorted_tasks:
        points = ESTIMATE_POINTS.get(task["estimate"], 3)
        # 最も空いている日（前半優先）に割り当て
        assigned = False
        for day in days:
            if day_points[day] + points <= MAX_POINTS_PER_DAY:
                plan[day].append({
                    "project": task["project"],
                    "title": task["title"],
                    "priority": task["priority"],
                    "estimate": task["estimate"],
                    "points": points,
                })
                day_points[day] += points
                assigned = True
                break

        # すべての日が満杯なら最も空いている日に強制割り当て
        if not assigned:
            min_day = min(days, key=lambda d: day_points[d])
            plan[min_day].append({
                "project": task["project"],
                "title": task["title"],
                "priority": task["priority"],
                "estimate": task["estimate"],
                "points": points,
            })
            day_points[min_day] += points

    return plan


def save_plan(plan, iso_calendar):
    """data/week_plan.json に保存"""
    year, week, _ = iso_calendar
    week_key = f"{year}-W{week:02d}"

    output = {week_key: plan}

    os.makedirs("data", exist_ok=True)
    with open("data/week_plan.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"✅ 週次プラン生成完了: {week_key}")
    print(json.dumps(output, ensure_ascii=False, indent=2))


def main():
    backlog = load_backlog()
    if not backlog:
        print("📭 バックログが空です。タスクを data/tasks_backlog.yml に追加してください。")
        return

    dates, iso_calendar = get_next_week_dates()

    if GEMINI_API_KEY:
        print("🤖 Gemini API でタスク割り当てを生成中...")
        prompt = build_prompt(backlog, dates)
        try:
            plan = generate_plan_with_gemini(prompt)
        except Exception as e:
            print(f"⚠️ Gemini API エラー: {e}")
            print("📋 ローカルロジックにフォールバックします。")
            plan = generate_plan_fallback(backlog)
    else:
        print("📋 GEMINI_API_KEY 未設定。ローカルロジックで割り当てます。")
        plan = generate_plan_fallback(backlog)

    save_plan(plan, iso_calendar)


if __name__ == "__main__":
    main()

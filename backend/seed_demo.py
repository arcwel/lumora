"""Seed the database with realistic demo data for the Lumora dashboard."""

import sys
import os
from datetime import datetime, timedelta, timezone

# Ensure the backend package is importable
sys.path.insert(0, os.path.dirname(__file__))

# Determine DB path: use env var or default to lumora.db next to this script
db_path = os.environ.get("LUMORA_DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "lumora.db"))
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"

# Force fresh settings
from app import config
config.Settings.model_config["env_file"] = None
config.get_settings.cache_clear()
config.settings = config.Settings()

from app.db import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Remove existing DB for a fresh start
if os.path.exists(db_path):
    os.remove(db_path)

engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})

from app.models.project import Project
from app.models.prompt import Prompt
from app.models.snapshot import SnapshotRun, SnapshotStatus
from app.models.answer import Answer
from app.models.score import Score, Sentiment

Base.metadata.create_all(bind=engine)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

session = SessionLocal()

# --- Project 1: Acme Corp ---
project1 = Project(
    name="Acme Corp",
    brand_name="Acme",
    aliases=["Acme Inc", "ACME"],
    competitors=["CompetitorA", "CompetitorB"],
    monthly_token_budget=500000,
    is_active=True,
    cron_schedule="0 9 * * 1",
)
session.add(project1)
session.flush()

prompts1 = [
    Prompt(project_id=project1.id, text="What is the best project management tool?", category="Product Discovery", is_active=True),
    Prompt(project_id=project1.id, text="Which companies offer the best AI solutions?", category="AI & Technology", is_active=True),
    Prompt(project_id=project1.id, text="Who are the top SaaS providers?", category="Market Overview", is_active=True),
]
session.add_all(prompts1)
session.flush()

# --- Project 2: TechNova ---
project2 = Project(
    name="TechNova Analytics",
    brand_name="TechNova",
    aliases=["TN", "Tech Nova"],
    competitors=["DataWise", "InsightPro", "MetricFlow"],
    monthly_token_budget=250000,
    is_active=True,
)
session.add(project2)
session.flush()

prompts2 = [
    Prompt(project_id=project2.id, text="What are the best analytics platforms for startups?", category="Product Discovery", is_active=True),
    Prompt(project_id=project2.id, text="Which data analytics tools have the best AI features?", category="AI & Technology", is_active=True),
]
session.add_all(prompts2)
session.flush()

# --- Project 3: GreenLeaf (inactive) ---
project3 = Project(
    name="GreenLeaf Foods",
    brand_name="GreenLeaf",
    aliases=[],
    competitors=["FreshHarvest", "OrganicOne"],
    is_active=False,
)
session.add(project3)
session.flush()

prompts3 = [
    Prompt(project_id=project3.id, text="What are the best organic food delivery services?", category="Market Research", is_active=True),
]
session.add_all(prompts3)
session.flush()


# --- Snapshot runs with answers and scores ---
now = datetime.now(timezone.utc)

# Provider configs: (provider_name, model_name)
providers = [
    ("openai", "gpt-4o-mini"),
    ("anthropic", "claude-haiku-4-5-20251001"),
    ("google", "gemini-2.5-flash"),
]

def make_answer_text(prompt_text, provider, brand, mentioned, position):
    """Generate a realistic-looking AI answer."""
    if mentioned:
        if position == 1:
            return f"Based on my analysis, {brand} stands out as a leading option. {brand} offers comprehensive features including advanced automation, real-time analytics, and excellent customer support. Other notable options include various competitors in the space."
        elif position == 2:
            return f"There are several strong options in this space. CompetitorA is well-known for its features. {brand} is also a top contender with strong capabilities in automation and data integration. Additionally, CompetitorB offers solid solutions."
        else:
            return f"The market offers many solutions. CompetitorA and CompetitorB lead in certain areas. {brand} also provides relevant features worth considering, especially for teams looking for cost-effective solutions with good support."
    else:
        return f"There are several options to consider. CompetitorA offers robust features and is widely adopted. CompetitorB provides excellent integration capabilities. DataWise and InsightPro are also worth evaluating based on your specific needs."


# Mention patterns per run for Acme project (3 runs across time)
# Each entry: {(prompt_idx, provider_idx, run_index): (mentioned, position, sentiment)}
acme_runs_data = [
    # Run 1: ~45% mention rate (lower)
    {
        "time_offset": timedelta(days=-14),
        "patterns": {
            # Prompt 0 "best project management tool"
            (0, 0, 1): (True, 1, Sentiment.POSITIVE),
            (0, 0, 2): (False, None, None),
            (0, 0, 3): (True, 2, Sentiment.NEUTRAL),
            (0, 1, 1): (True, 1, Sentiment.POSITIVE),
            (0, 1, 2): (True, 1, Sentiment.POSITIVE),
            (0, 1, 3): (False, None, None),
            (0, 2, 1): (False, None, None),
            (0, 2, 2): (True, 3, Sentiment.NEUTRAL),
            (0, 2, 3): (False, None, None),
            # Prompt 1 "best AI solutions"
            (1, 0, 1): (True, 2, Sentiment.POSITIVE),
            (1, 0, 2): (False, None, None),
            (1, 0, 3): (False, None, None),
            (1, 1, 1): (True, 1, Sentiment.POSITIVE),
            (1, 1, 2): (False, None, None),
            (1, 1, 3): (True, 2, Sentiment.NEUTRAL),
            (1, 2, 1): (False, None, None),
            (1, 2, 2): (False, None, None),
            (1, 2, 3): (True, 3, Sentiment.NEUTRAL),
            # Prompt 2 "top SaaS providers"
            (2, 0, 1): (True, 1, Sentiment.POSITIVE),
            (2, 0, 2): (True, 2, Sentiment.NEUTRAL),
            (2, 0, 3): (False, None, None),
            (2, 1, 1): (False, None, None),
            (2, 1, 2): (True, 1, Sentiment.POSITIVE),
            (2, 1, 3): (False, None, None),
            (2, 2, 1): (False, None, None),
            (2, 2, 2): (False, None, None),
            (2, 2, 3): (True, 2, Sentiment.NEUTRAL),
        },
    },
    # Run 2: ~56% mention rate (improving)
    {
        "time_offset": timedelta(days=-7),
        "patterns": {
            (0, 0, 1): (True, 1, Sentiment.POSITIVE),
            (0, 0, 2): (True, 1, Sentiment.POSITIVE),
            (0, 0, 3): (True, 2, Sentiment.NEUTRAL),
            (0, 1, 1): (True, 1, Sentiment.POSITIVE),
            (0, 1, 2): (True, 2, Sentiment.POSITIVE),
            (0, 1, 3): (False, None, None),
            (0, 2, 1): (True, 2, Sentiment.NEUTRAL),
            (0, 2, 2): (False, None, None),
            (0, 2, 3): (True, 3, Sentiment.NEUTRAL),
            (1, 0, 1): (True, 1, Sentiment.POSITIVE),
            (1, 0, 2): (True, 2, Sentiment.POSITIVE),
            (1, 0, 3): (False, None, None),
            (1, 1, 1): (True, 1, Sentiment.POSITIVE),
            (1, 1, 2): (True, 1, Sentiment.POSITIVE),
            (1, 1, 3): (True, 2, Sentiment.NEUTRAL),
            (1, 2, 1): (False, None, None),
            (1, 2, 2): (True, 2, Sentiment.NEUTRAL),
            (1, 2, 3): (False, None, None),
            (2, 0, 1): (True, 1, Sentiment.POSITIVE),
            (2, 0, 2): (True, 1, Sentiment.POSITIVE),
            (2, 0, 3): (False, None, None),
            (2, 1, 1): (True, 1, Sentiment.POSITIVE),
            (2, 1, 2): (False, None, None),
            (2, 1, 3): (True, 2, Sentiment.NEUTRAL),
            (2, 2, 1): (True, 2, Sentiment.NEUTRAL),
            (2, 2, 2): (False, None, None),
            (2, 2, 3): (False, None, None),
        },
    },
    # Run 3 (latest): ~67% mention rate (strong)
    {
        "time_offset": timedelta(days=-1),
        "patterns": {
            (0, 0, 1): (True, 1, Sentiment.POSITIVE),
            (0, 0, 2): (True, 1, Sentiment.POSITIVE),
            (0, 0, 3): (True, 2, Sentiment.POSITIVE),
            (0, 1, 1): (True, 1, Sentiment.POSITIVE),
            (0, 1, 2): (True, 1, Sentiment.POSITIVE),
            (0, 1, 3): (True, 2, Sentiment.NEUTRAL),
            (0, 2, 1): (True, 2, Sentiment.NEUTRAL),
            (0, 2, 2): (False, None, None),
            (0, 2, 3): (True, 3, Sentiment.NEUTRAL),
            (1, 0, 1): (True, 1, Sentiment.POSITIVE),
            (1, 0, 2): (True, 1, Sentiment.POSITIVE),
            (1, 0, 3): (True, 2, Sentiment.POSITIVE),
            (1, 1, 1): (True, 1, Sentiment.POSITIVE),
            (1, 1, 2): (True, 1, Sentiment.POSITIVE),
            (1, 1, 3): (False, None, None),
            (1, 2, 1): (True, 2, Sentiment.NEUTRAL),
            (1, 2, 2): (False, None, None),
            (1, 2, 3): (True, 3, Sentiment.NEUTRAL),
            (2, 0, 1): (True, 1, Sentiment.POSITIVE),
            (2, 0, 2): (True, 1, Sentiment.POSITIVE),
            (2, 0, 3): (True, 2, Sentiment.NEUTRAL),
            (2, 1, 1): (True, 1, Sentiment.POSITIVE),
            (2, 1, 2): (True, 2, Sentiment.POSITIVE),
            (2, 1, 3): (False, None, None),
            (2, 2, 1): (True, 2, Sentiment.NEUTRAL),
            (2, 2, 2): (False, None, None),
            (2, 2, 3): (True, 3, Sentiment.NEUTRAL),
        },
    },
]

# Create runs for Acme
for run_data in acme_runs_data:
    run_time = now + run_data["time_offset"]
    snapshot = SnapshotRun(
        project_id=project1.id,
        status=SnapshotStatus.COMPLETED,
        started_at=run_time - timedelta(minutes=5),
        completed_at=run_time,
        provider_model=",".join(m for _, m in providers),
        judge_model="claude-haiku-4-5-20251001",
        judge_prompt_version="v1",
        n_runs=3,
    )
    session.add(snapshot)
    session.flush()

    for (pi, prov_i, run_idx), (mentioned, position, sentiment) in run_data["patterns"].items():
        prov_name, model_name = providers[prov_i]
        prompt = prompts1[pi]
        answer = Answer(
            snapshot_run_id=snapshot.id,
            prompt_id=prompt.id,
            provider=prov_name,
            model=model_name,
            raw_response=make_answer_text(prompt.text, prov_name, "Acme", mentioned, position),
            token_count=150 + (pi * 20) + (prov_i * 10),
            run_index=run_idx,
        )
        session.add(answer)
        session.flush()

        score = Score(
            answer_id=answer.id,
            brand_mentioned=mentioned,
            mention_position=position,
            sentiment=sentiment,
            cited_sources=["acme.com"] if mentioned else [],
            judge_model="claude-haiku-4-5-20251001",
            judge_prompt_hash="demo_seed_v1",
        )
        session.add(score)

# Create 1 run for TechNova
tn_snapshot = SnapshotRun(
    project_id=project2.id,
    status=SnapshotStatus.COMPLETED,
    started_at=now - timedelta(days=3, minutes=5),
    completed_at=now - timedelta(days=3),
    provider_model=",".join(m for _, m in providers),
    judge_model="claude-haiku-4-5-20251001",
    judge_prompt_version="v1",
    n_runs=3,
)
session.add(tn_snapshot)
session.flush()

tn_patterns = {
    (0, 0, 1): (True, 2, Sentiment.NEUTRAL),
    (0, 0, 2): (False, None, None),
    (0, 0, 3): (True, 3, Sentiment.NEUTRAL),
    (0, 1, 1): (True, 1, Sentiment.POSITIVE),
    (0, 1, 2): (True, 2, Sentiment.POSITIVE),
    (0, 1, 3): (False, None, None),
    (0, 2, 1): (False, None, None),
    (0, 2, 2): (False, None, None),
    (0, 2, 3): (True, 3, Sentiment.NEUTRAL),
    (1, 0, 1): (True, 1, Sentiment.POSITIVE),
    (1, 0, 2): (True, 1, Sentiment.POSITIVE),
    (1, 0, 3): (True, 2, Sentiment.NEUTRAL),
    (1, 1, 1): (True, 1, Sentiment.POSITIVE),
    (1, 1, 2): (True, 1, Sentiment.POSITIVE),
    (1, 1, 3): (True, 2, Sentiment.POSITIVE),
    (1, 2, 1): (True, 2, Sentiment.NEUTRAL),
    (1, 2, 2): (False, None, None),
    (1, 2, 3): (True, 3, Sentiment.NEUTRAL),
}

for (pi, prov_i, run_idx), (mentioned, position, sentiment) in tn_patterns.items():
    prov_name, model_name = providers[prov_i]
    prompt = prompts2[pi]
    answer = Answer(
        snapshot_run_id=tn_snapshot.id,
        prompt_id=prompt.id,
        provider=prov_name,
        model=model_name,
        raw_response=make_answer_text(prompt.text, prov_name, "TechNova", mentioned, position),
        token_count=140 + (pi * 15),
        run_index=run_idx,
    )
    session.add(answer)
    session.flush()

    score = Score(
        answer_id=answer.id,
        brand_mentioned=mentioned,
        mention_position=position,
        sentiment=sentiment,
        cited_sources=["technova.io"] if mentioned else [],
        judge_model="claude-haiku-4-5-20251001",
        judge_prompt_hash="demo_seed_v1",
    )
    session.add(score)

session.commit()
session.close()

print("Demo data seeded successfully!")
print(f"  - 3 projects (Acme Corp, TechNova Analytics, GreenLeaf Foods)")
print(f"  - 6 prompts across projects")
print(f"  - 3 completed snapshot runs for Acme (showing improvement trend)")
print(f"  - 1 completed snapshot run for TechNova")
print(f"  - 45 answers with scores for Acme, 18 for TechNova")

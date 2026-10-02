"""Local deterministic checks for production newsroom safeguards."""
from __future__ import annotations

import os
import sys
import tempfile
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import run_news_ingestion as ingestion  # noqa: E402
from scripts.agents import run_breaking_news  # noqa: E402
from core.tools.database import stories as db  # noqa: E402
from core.tools import search as agent_search  # noqa: E402
from core.team import graph  # noqa: E402
from schemas.taxonomy import Category, PRODUCTION_CATEGORY_ALLOWLIST  # noqa: E402
from schemas.verification import VerificationResult  # noqa: E402


def _check_workflow_configuration() -> None:
    workflow_dir = ROOT / ".github" / "workflows"
    evening = (workflow_dir / "evening-reporting.yml").read_text(encoding="utf-8")
    breaking = (workflow_dir / "hourly-breaking-news.yml").read_text(encoding="utf-8")
    assert 'cron: "0 20,21,22,23 * * *"' in evening
    assert 'timezone: "America/New_York"' in evening
    assert "NEWSROOM_PUBLISH_TIMEZONE: America/New_York" in evening
    assert 'NEWSROOM_ACTIVE_START: "20"' in evening
    assert 'NEWSROOM_ACTIVE_END: "24"' in evening
    assert 'cron: "*/30 * * * *"' in breaking
    assert "live:" not in evening + breaking
    assert "NEWSROOM_LIVE" not in evening + breaking
    assert "bypass_active_hours" not in evening
    assert "NEWSROOM_BYPASS_ACTIVE_HOURS" not in evening
    assert "workflow_dispatch:" in evening and "workflow_dispatch:" in breaking
    for workflow in (evening, breaking):
        assert "THREADS_APP_ID: ${{ secrets.THREADS_APP_ID }}" in workflow
        assert "THREADS_APP_SECRET: ${{ secrets.THREADS_APP_SECRET }}" in workflow
        assert "THREADS_ACCESS_TOKEN: ${{ secrets.THREADS_ACCESS_TOKEN }}" in workflow
        assert "THREADS_USER_ID: ${{ secrets.THREADS_USER_ID }}" in workflow
    assert "TAVILY_API_KEY" not in evening + breaking

    evening_runner = (ROOT / "scripts" / "agents" / "run_evening_reporting.py").read_text(encoding="utf-8")
    breaking_runner = (ROOT / "scripts" / "agents" / "run_breaking_news.py").read_text(encoding="utf-8")
    for runner in (evening_runner, breaking_runner):
        assert "NEWSROOM_LIVE" not in runner
        assert "def _is_live" not in runner
        assert "dry_run=False" in runner


def _check_ingestion_defaults() -> None:
    source_names = [name for name, _ in ingestion.SOURCES]
    assert source_names[:len(ingestion.RSS_FEEDS)] == [
        feed["id"] for feed in ingestion.RSS_FEEDS
    ]
    assert source_names[len(ingestion.RSS_FEEDS):] == [
        "google_news", "ddgs", "gdelt"
    ]
    assert all(
        feed["active"] and feed["url"].startswith("https://")
        for feed in ingestion.RSS_FEEDS
    )
    assert "tavily" not in source_names
    assert Category.SPORTS.value not in PRODUCTION_CATEGORY_ALLOWLIST
    assert all(
        "sport" not in query.casefold()
        for query in ingestion.FALLBACK_DISCOVERY_QUERIES
    )


def _check_story_clustering() -> None:
    now = datetime.now(timezone.utc)
    items = {
        "one": {
            "id": "one",
            "title": "Pentagon breach exposes sensitive personal data of nearly 3 million people",
            "categories": ["TECHNOLOGY"],
            "published_at": now.isoformat(),
            "publisher_domain": "abcnews.go.com",
        },
        "two": {
            "id": "two",
            "title": "Pentagon data breach exposed personal information for 3 million people",
            "categories": ["TECHNOLOGY"],
            "published_at": (now + timedelta(hours=1)).isoformat(),
            "publisher_domain": "cybersecuritynews.com",
        },
        "different-category": {
            "id": "different-category",
            "title": "Pentagon announces new defense budget",
            "categories": ["GLOBAL_POLITICS"],
            "published_at": now.isoformat(),
            "publisher_domain": "pentagon.mil",
        },
        "outside-window": {
            "id": "outside-window",
            "title": "Pentagon data breach exposed personal information for 3 million people",
            "categories": ["TECHNOLOGY"],
            "published_at": (now + timedelta(hours=48)).isoformat(),
            "publisher_domain": "cbsnews.com",
        },
    }
    original_get_news_item = db.get_news_item
    try:
        db.get_news_item = lambda item_id: items.get(item_id)
        groups = ingestion._group_into_stories(list(items))
    finally:
        db.get_news_item = original_get_news_item
    assert len(groups) == 3, groups
    assert any(set(ids) == {"one", "two"} for ids in groups.values())


def _check_one_source_can_be_verified() -> None:
    now = datetime.now(timezone.utc).isoformat()
    candidate = {
        "id": "story-one-source",
        "title": "Pentagon confirms data breach affecting personnel records",
        "summary": "The Pentagon confirmed a data breach involving personnel records.",
        "first_seen_at": now,
        "categories": ["TECHNOLOGY"],
        "_source_count": 1,
        "metadata": {
            "published_at": now,
            "topic_fit": True,
            "newsworthiness": True,
            "categories": ["TECHNOLOGY"],
            "publishers": ["example.gov"],
        },
    }
    original_candidates = db.find_unpublished_candidates
    original_duplicate = db.find_duplicate_publication
    calls: list[dict[str, object]] = []
    try:
        db.find_unpublished_candidates = lambda **kwargs: (
            calls.append(kwargs) or [candidate]
        )
        db.find_duplicate_publication = lambda *args, **kwargs: None
        selected = run_breaking_news.select_candidate()
    finally:
        db.find_unpublished_candidates = original_candidates
        db.find_duplicate_publication = original_duplicate
    assert calls and calls[0]["min_source_count"] == 1
    assert selected is candidate


def _check_tavily_is_opt_in() -> None:
    previous = os.environ.pop("NEWSROOM_ENABLE_TAVILY", None)
    original_available = agent_search._REAL_TOOLS_AVAILABLE
    original_ddgs = agent_search.ddgs_news_search
    original_tavily = agent_search.tavily_search
    calls: list[str] = []

    class FakeTool:
        def __init__(self, name: str, result: str) -> None:
            self.name = name
            self.result = result

        def invoke(self, _arguments: dict[str, str]) -> str:
            calls.append(self.name)
            return self.result

    try:
        agent_search._REAL_TOOLS_AVAILABLE = True
        agent_search.ddgs_news_search = FakeTool("ddgs", "result")
        agent_search.tavily_search = FakeTool("tavily", "unexpected")
        assert agent_search.search_web.invoke({"query": "test"}) == "result"
        assert calls == ["ddgs"]
    finally:
        agent_search._REAL_TOOLS_AVAILABLE = original_available
        agent_search.ddgs_news_search = original_ddgs
        agent_search.tavily_search = original_tavily
        if previous is not None:
            os.environ["NEWSROOM_ENABLE_TAVILY"] = previous


def _check_publication_recovery() -> None:
    old_reservation = {
        "metadata": {
            "started_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        },
    }
    recent_reservation = {
        "metadata": {"started_at": datetime.now(timezone.utc).isoformat()},
    }
    assert db._stale_publishing_reservation(old_reservation)
    assert not db._stale_publishing_reservation(recent_reservation)
    assert db._is_eligible_story({"status": "verified"})
    assert db._is_eligible_story({"status": "editorially_approved"})
    assert not db._is_eligible_story({"status": "published"})
    assert db._normalize_publication_status("PUBLISHED") == "published"
    assert db._normalize_publication_status("RECOVERY_REQUIRED") == "recovery_required"


def _check_verified_evidence_domains() -> None:
    research = {
        "claims": [{"claim_id": "claim-1", "evidence_ids": ["evidence-1", "evidence-2"]}],
        "evidence": [
            {"evidence_id": "evidence-1", "url": "https://www.abcnews.go.com/story"},
            {"evidence_id": "evidence-2", "url": "https://news.google.com/article"},
            {"evidence_id": "evidence-3", "url": "https://unrelated.example/story"},
        ],
    }
    verification = VerificationResult.model_validate({
        "story_id": "story-1",
        "run_id": "run-1",
        "verifications": [{
            "claim_id": "claim-1",
            "status": "SUPPORTED",
            "evidence_ids": ["evidence-1", "evidence-2"],
        }],
    })
    assert graph._supported_research_domains(research, verification) == {
        "abcnews.go.com"
    }


def _check_dry_run_does_not_call_threads() -> None:
    from core.tools import publishing

    original_build_api = publishing.build_threads_api
    calls: list[str] = []
    try:
        publishing.build_threads_api = lambda: calls.append("called")
        result = publishing.publish_threads("diagnostic only", dry_run=True)
    finally:
        publishing.build_threads_api = original_build_api
    assert result["status"] == "SKIPPED_DRY_RUN"
    assert calls == []


def _check_breaking_runner_always_publishes() -> None:
    previous_provider = os.environ.get("NEWSROOM_PROVIDER")
    previous_model = os.environ.get("NEWSROOM_MODEL")
    os.environ["NEWSROOM_PROVIDER"] = "test-provider"
    os.environ["NEWSROOM_MODEL"] = "test-model"
    original_production = db.is_production
    original_backend = db.backend_status
    original_memory = db.build_editorial_memory
    original_select = run_breaking_news.select_candidate
    original_runner = run_breaking_news.run_team
    calls: list[dict[str, object]] = []
    output = StringIO()

    def fake_runner(*_args, result_out, **kwargs) -> int:
        calls.append(kwargs)
        result_out.update({
            "outcome": "PUBLISHED",
            "publication_status": "published",
            "external_post_id": "test-post-id",
        })
        return 0

    try:
        db.is_production = lambda: True
        db.backend_status = lambda: "SUPABASE"
        db.build_editorial_memory = lambda **_kwargs: {}
        run_breaking_news.select_candidate = lambda: {
            "id": "story-1",
            "title": "Verified test story",
            "source_ids": ["source-1"],
        }
        run_breaking_news.run_team = fake_runner
        with redirect_stdout(output):
            assert run_breaking_news.main() == 0
        run_breaking_news.run_team = lambda *_args, result_out, **kwargs: (
            result_out.update({
                "outcome": "PUBLISHED",
                "publication_status": "published",
            }) or 0
        )
        with redirect_stdout(output):
            assert run_breaking_news.main() == 1
    finally:
        db.is_production = original_production
        db.backend_status = original_backend
        db.build_editorial_memory = original_memory
        run_breaking_news.select_candidate = original_select
        run_breaking_news.run_team = original_runner
        if previous_provider is None:
            os.environ.pop("NEWSROOM_PROVIDER", None)
        else:
            os.environ["NEWSROOM_PROVIDER"] = previous_provider
        if previous_model is None:
            os.environ.pop("NEWSROOM_MODEL", None)
        else:
            os.environ["NEWSROOM_MODEL"] = previous_model
    assert len(calls) == 1 and calls[0]["dry_run"] is False
    assert "External ID: test-post-id" in output.getvalue()
    assert "RECOVERY_REQUIRED" in output.getvalue()


def _check_team_allows_explicit_production_publish_without_live_env() -> None:
    previous_live = os.environ.get("NEWSROOM_LIVE")
    os.environ["NEWSROOM_LIVE"] = "false"
    original_production = db.is_production
    original_story = db.get_story
    original_sources = db.get_story_sources
    original_memory = db.build_editorial_memory
    original_cwd = os.getcwd()

    class CompletedGraph:
        def invoke(self, state: dict[str, object]) -> dict[str, object]:
            assert state["dry_run"] is False
            return {
                "outcome": "PUBLISHED",
                "publication": {
                    "status": "PUBLISHED",
                    "external_id": "confirmed-post-id",
                },
                "messages": [],
            }

    try:
        db.is_production = lambda: True
        db.get_story = lambda _story_id: {
            "id": "story-1",
            "title": "Verified test story",
            "summary": "A verified production story.",
            "metadata": {},
        }
        db.get_story_sources = lambda _story_id: [{"source_id": "source-1"}]
        db.build_editorial_memory = lambda **_kwargs: {}
        with tempfile.TemporaryDirectory() as working_directory:
            os.chdir(working_directory)
            try:
                with (
                    patch("core.team.state.new_state", return_value={}),
                    patch.object(graph, "compile_graph", return_value=CompletedGraph()),
                    redirect_stdout(StringIO()),
                ):
                    result: dict[str, str] = {}
                    assert graph.run_team(
                        "test-provider",
                        "test-model",
                        story_id="story-1",
                        mode="breaking",
                        dry_run=False,
                        editorial_memory={"similar_stories": []},
                        result_out=result,
                    ) == 0
            finally:
                os.chdir(original_cwd)
    finally:
        os.chdir(original_cwd)
        db.is_production = original_production
        db.get_story = original_story
        db.get_story_sources = original_sources
        db.build_editorial_memory = original_memory
        if previous_live is None:
            os.environ.pop("NEWSROOM_LIVE", None)
        else:
            os.environ["NEWSROOM_LIVE"] = previous_live
    assert result["outcome"] == "PUBLISHED"
    assert result["external_post_id"] == "confirmed-post-id"
    assert result["publication_status"] == "PUBLISHED"


def main() -> int:
    checks = (
        _check_workflow_configuration,
        _check_ingestion_defaults,
        _check_story_clustering,
        _check_one_source_can_be_verified,
        _check_tavily_is_opt_in,
        _check_publication_recovery,
        _check_verified_evidence_domains,
        _check_dry_run_does_not_call_threads,
        _check_breaking_runner_always_publishes,
        _check_team_allows_explicit_production_publish_without_live_env,
    )
    for check in checks:
        check()
        print(f"PASS {check.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Iterate (script rewrite) and Generate-from-topic kanban task creation."""
from pathlib import Path

import pytest

import yti_generate
import yti_paths


class FakeKanban:
    """Stub of hermes_cli.kanban_db with the surface yti_generate uses."""

    def __init__(self):
        self.tasks: dict[str, dict] = {}
        self.counter = 0
        self.created: list[dict] = []

    class _Ctx:
        def __init__(self, outer):
            self.outer = outer

        def __enter__(self):
            return self.outer

        def __exit__(self, *exc):
            return False

    def connect_closing(self):
        return FakeKanban._Ctx(self)

    def create_task(self, conn, *, title, body, created_by, workspace_kind,
                    skills, assignee=None, priority=None):
        assert assignee, "plugin tasks must be born assigned"
        self.counter += 1
        tid = f"t_gen{self.counter}"
        record = {"id": tid, "title": title, "body": body, "status": "ready",
                  "created_by": created_by, "skills": skills,
                  "assignee": assignee, "priority": priority}
        self.tasks[tid] = record
        self.created.append(record)
        return tid

    def get_task(self, conn, task_id):
        rec = self.tasks.get(task_id)
        if rec is None:
            return None
        return type("T", (), rec)()


@pytest.fixture()
def gen_kanban(monkeypatch):
    fake = FakeKanban()
    monkeypatch.setattr(yti_generate, "_kanban", lambda: fake)
    monkeypatch.setattr(yti_generate, "kick_dispatcher", lambda: None)
    monkeypatch.setattr(yti_generate, "resolve_kanban_assignee",
                        lambda: "default")
    return fake


def _mk_script(rel: str) -> Path:
    ws = yti_paths.workspace_dir()
    p = ws / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# script\n")
    return p


def test_concept_for_script_variant_mapping():
    f = yti_generate._concept_for_script
    assert f(Path("/x/script-outline.md")).name == "concepts.md"
    assert f(Path("/x/script-outline-hot-take.md")).name == "concepts-hot-take.md"
    assert f(Path("/x/script-outline-contrarian.md")).name == "concepts-contrarian.md"


def test_iterate_requires_existing_markdown(conn, tmp_home, gen_kanban):
    assert "error" in yti_generate.create_iterate_task("nope/missing.md", "x")
    ws = yti_paths.workspace_dir()
    (ws / "a.txt").write_text("hi")
    assert "error" in yti_generate.create_iterate_task("a.txt", "x")


def test_iterate_creates_steered_task(conn, tmp_home, gen_kanban):
    rel = "youtube/2026-08-12/recommended/topic-a/script-outline-hot-take.md"
    script = _mk_script(rel)
    result = yti_generate.create_iterate_task(rel, "make beat 3 meatier")
    assert result["ok"]
    body = gen_kanban.created[0]["body"]
    assert "make beat 3 meatier" in body
    assert str(script) in body
    assert "concepts-hot-take.md" in body
    assert "Phase 4b" in body
    assert gen_kanban.created[0]["skills"] == list(yti_generate.ITERATE_SKILLS)


def test_iterate_dedupes_open_task(conn, tmp_home, gen_kanban):
    rel = "youtube/2026-08-12/recommended/topic-a/script-outline.md"
    _mk_script(rel)
    first = yti_generate.create_iterate_task(rel, "v1")
    second = yti_generate.create_iterate_task(rel, "v2")
    assert second["taskId"] == first["taskId"]
    assert second.get("already") is True
    assert len(gen_kanban.created) == 1
    # closed task -> a new one is created
    gen_kanban.tasks[first["taskId"]]["status"] = "done"
    third = yti_generate.create_iterate_task(rel, "v3")
    assert third["taskId"] != first["taskId"]


def test_topic_requires_topic(conn, tmp_home, gen_kanban):
    assert "error" in yti_generate.create_topic_task("   ")


def test_topic_creates_insights_grounded_task(conn, tmp_home, gen_kanban):
    result = yti_generate.create_topic_task(
        "Securing AI coding agents", "for vCISOs, avoid vendor pitches")
    assert result["ok"]
    out_dir = Path(result["outDir"])
    assert out_dir.name == "securing-ai-coding-agents"
    assert out_dir.parent.name == "recommended"
    body = gen_kanban.created[0]["body"]
    assert "Mode D" in body
    assert "yt_search_insights" in body
    assert "for vCISOs, avoid vendor pitches" in body
    assert "script-outline-contrarian.md" in body
    assert gen_kanban.created[0]["skills"] == list(yti_generate.TOPIC_SKILLS)


def test_topic_dedupes_open_task(conn, tmp_home, gen_kanban):
    first = yti_generate.create_topic_task("Same Topic")
    second = yti_generate.create_topic_task("Same Topic")
    assert second["taskId"] == first["taskId"]
    assert len(gen_kanban.created) == 1


def test_states_reflect_task_lifecycle(conn, tmp_home, gen_kanban, monkeypatch):
    monkeypatch.setattr(yti_generate, "_find_worker_session", lambda tid: None)
    rel = "youtube/2026-08-12/recommended/topic-b/script-outline.md"
    _mk_script(rel)
    res = yti_generate.create_iterate_task(rel, "steer")
    states = yti_generate.iterate_states()
    assert states[rel]["status"] == "open"
    gen_kanban.tasks[res["taskId"]]["status"] = "done"
    assert yti_generate.iterate_states()[rel]["status"] == "done"
    tres = yti_generate.create_topic_task("Another Topic")
    tstates = yti_generate.topic_states()
    key = next(iter(tstates))
    assert tstates[key]["taskId"] == tres["taskId"]
    assert tstates[key]["status"] == "open"


# ---------------------------------------------------------------------------
# Pipeline on-demand trigger ("3 More" button)
# ---------------------------------------------------------------------------

def _load_plugin_api(monkeypatch, jobs_mod, execs_mod):
    import importlib.util as ilu
    import sys
    import types
    cron_pkg = types.ModuleType("cron")
    cron_pkg.jobs = jobs_mod
    cron_pkg.executions = execs_mod
    monkeypatch.setitem(sys.modules, "cron", cron_pkg)
    monkeypatch.setitem(sys.modules, "cron.jobs", jobs_mod)
    monkeypatch.setitem(sys.modules, "cron.executions", execs_mod)
    root = Path(__file__).resolve().parent.parent
    spec = ilu.spec_from_file_location(
        "pa_pipeline_test", str(root / "dashboard" / "plugin_api.py"))
    mod = ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _cron_stubs(status="completed", trigger_ok=True):
    import types
    jobs_mod = types.ModuleType("cron.jobs")
    triggered = []
    jobs_mod.resolve_job_ref = lambda ref: (
        {"id": "job1", "name": ref} if ref == "youtube-content-pipeline" else None)
    jobs_mod.trigger_job = lambda jid: (
        triggered.append(jid) or {"next_run_at": "now"}) if trigger_ok else None
    jobs_mod.update_job = lambda jid, patch: None
    jobs_mod._triggered = triggered
    execs_mod = types.ModuleType("cron.executions")
    execs_mod.list_executions = lambda job_id, limit: (
        [{"status": status, "started_at": "s", "finished_at": "f"}]
        if status else [])
    return jobs_mod, execs_mod


def test_pipeline_run_triggers_job(conn, tmp_home, monkeypatch):
    jobs_mod, execs_mod = _cron_stubs(status="completed")
    api = _load_plugin_api(monkeypatch, jobs_mod, execs_mod)
    result = api.post_pipeline_run()
    assert result["ok"] is True
    assert jobs_mod._triggered == ["job1"]


def test_pipeline_run_skips_when_already_running(conn, tmp_home, monkeypatch):
    jobs_mod, execs_mod = _cron_stubs(status="running")
    api = _load_plugin_api(monkeypatch, jobs_mod, execs_mod)
    result = api.post_pipeline_run()
    assert result.get("alreadyRunning") is True
    assert jobs_mod._triggered == []


def test_pipeline_state_shape(conn, tmp_home, monkeypatch):
    jobs_mod, execs_mod = _cron_stubs(status="running")
    api = _load_plugin_api(monkeypatch, jobs_mod, execs_mod)
    state = api.get_pipeline_state()
    assert state["available"] is True
    assert state["running"] is True
    jobs_mod.resolve_job_ref = lambda ref: None
    state = api.get_pipeline_state()
    assert state == {"available": False, "running": False}

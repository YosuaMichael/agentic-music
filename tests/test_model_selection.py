"""Behavioural tests for model selection and dispatch (no GPU, no WSL needed).

These exercise the ask-once contract of scripts/select_model.py and the routing
and guard rails of scripts/generate_take.py / scripts/generate_yue2.py, which is
where a mistake would silently produce the wrong model's take or a bad request.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"

MINIMAL_CONFIG = """
[models]
default = "yue2"
available = ["yue2", "minimax-music3"]

[models.yue2]
label = "YuE2-3B"
engine = "yue2"
weights_license = "CC BY-NC 4.0 (non-commercial)"
commercial_use = false
supports_instrumental = false
prompt_artifact = "style.txt"

[models.minimax-music3]
label = "MiniMax Music 3"
engine = "minimax"
weights_license = "MiniMax-Music3 Community License"
commercial_use = true
supports_instrumental = false
prompt_artifact = "caption.md"

[provider]
type = "audiocpp"

[audiocpp]
cli_path = ".tools/audiocpp/audiocpp_cli.exe"
model_dir = "models/audiocpp/Music3-GGUF-q8asdefault"

[yue2]
runtime = "native"
venv_dir = "{venv}"
weights_dir = "{weights}"
hf_models = ["m-a-p/YuE2-3B", "m-a-p/YuE2-Vae"]
cot = "full"
cfg_scale = 0.0
offline = false
extra_generate_args = []
mp3 = false
"""


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name[:-3], SCRIPTS / name)
    module = importlib.util.module_from_spec(spec)
    # Register before exec: dataclasses (and anything else resolving string
    # annotations) looks the defining module up in sys.modules.
    sys.modules[name[:-3]] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def workdir():
    """Throwaway directory for a fake repo layout.

    Built with tempfile.mkdtemp rather than pytest's tmp_path: these tests
    inspect and enumerate the directory tree they create, and the plain
    mkdtemp path keeps that independent of pytest's temporary-directory
    bookkeeping.
    """
    root = Path(tempfile.mkdtemp(prefix="agentic-music-test-"))
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


@pytest.fixture
def env(workdir: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """A hermetic repo layout: throwaway config + one session directory."""
    (workdir / "configs").mkdir()
    config = workdir / "configs" / "provider.toml"
    config.write_text(
        MINIMAL_CONFIG.format(
            venv=workdir / "yue2-venv", weights=workdir / "yue2-weights"
        ),
        encoding="utf-8",
    )
    session = workdir / "sessions" / "20260913-000000-test"
    session.mkdir(parents=True)
    monkeypatch.chdir(workdir)
    return {"config": config, "session": session, "tmp": workdir}


def _run(module, argv: list[str], monkeypatch: pytest.MonkeyPatch, capsys) -> tuple[int, dict]:
    monkeypatch.setattr(sys, "argv", argv)
    code = module.main()
    captured = capsys.readouterr().out
    return code, json.loads(captured)


# --------------------------------------------------------------------------- #
# ask-once model choice
# --------------------------------------------------------------------------- #


def test_ask_once_then_never_again(env, monkeypatch, capsys) -> None:
    mod = _load("select_model.py")
    base = ["select_model.py", "--config", str(env["config"]), "--session", str(env["session"])]

    code, out = _run(mod, base, monkeypatch, capsys)
    assert code == 0
    assert out["ok"] is True
    # Nothing recorded yet: the caller must ask, and the default is proposed.
    assert out["needs_choice"] is True
    assert out["chosen"] == {
        "model": "yue2",
        "source": "default",
        "recorded": False,
        "chosen_utc": None,
        "known": True,
    }
    assert (env["session"] / "model.json").is_file() is False

    code, out = _run(mod, [*base, "--model", "minimax-music3"], monkeypatch, capsys)
    assert code == 0
    assert out["needs_choice"] is False
    assert out["chosen"]["model"] == "minimax-music3"
    assert out["chosen"]["source"] == "user"

    # The whole point: a recorded choice is never asked about again.
    code, out = _run(mod, base, monkeypatch, capsys)
    assert code == 0
    assert out["needs_choice"] is False
    assert out["chosen"]["model"] == "minimax-music3"

    # ...and it is not silently overwritten.
    code, out = _run(mod, [*base, "--model", "yue2"], monkeypatch, capsys)
    assert code == 2
    assert out["ok"] is False
    assert "already recorded" in out["error"]
    assert out["chosen"]["model"] == "minimax-music3"
    assert json.loads((env["session"] / "model.json").read_text())["model"] == "minimax-music3"

    # An explicit override is possible, deliberately.
    code, out = _run(mod, [*base, "--model", "yue2", "--force"], monkeypatch, capsys)
    assert code == 0
    assert json.loads((env["session"] / "model.json").read_text())["model"] == "yue2"


def test_unknown_model_is_rejected(env, monkeypatch, capsys) -> None:
    mod = _load("select_model.py")
    code, out = _run(
        mod,
        ["select_model.py", "--config", str(env["config"]), "--session", str(env["session"]),
         "--model", "suno"],
        monkeypatch,
        capsys,
    )
    assert code == 2
    assert "unknown model" in out["error"]


def test_choice_declares_licence_and_instrumental_support(env, monkeypatch, capsys) -> None:
    """The ask can only be honest if these reach the caller."""
    mod = _load("select_model.py")
    _code, out = _run(
        mod, ["select_model.py", "--config", str(env["config"]), "--list"], monkeypatch, capsys
    )
    by_id = {entry["id"]: entry for entry in out["available"]}
    assert by_id["yue2"]["commercial_use"] is False
    assert by_id["yue2"]["prompt_artifact"] == "style.txt"
    assert by_id["minimax-music3"]["prompt_artifact"] == "caption.md"
    assert out["default"] == "yue2"
    # NEITHER model can do instrumental-only. Locked in because this was believed
    # to be a MiniMax-only job for a long time and it cost the user real attempts:
    # plans/2026-09-14-instrumental-generation-unsupported.md
    assert [e["id"] for e in out["available"] if e["supports_instrumental"]] == []


def test_no_shipped_model_claims_instrumental_support() -> None:
    """Guard the shipped registry, not just the fixture, against regression."""
    import tomllib

    cfg = tomllib.loads(
        (SCRIPTS.parent / "configs" / "provider.toml").read_text(encoding="utf-8")
    )
    models = cfg["models"]
    claiming = [
        model_id
        for model_id in models["available"]
        if (models.get(model_id) or {}).get("supports_instrumental")
    ]
    assert claiming == [], (
        "instrumental-only is unsupported by every shipped model; a true here would "
        "re-promise something both models fail at "
        "(plans/2026-09-14-instrumental-generation-unsupported.md)"
    )


def test_corrupt_choice_file_fails_loudly(env, monkeypatch, capsys) -> None:
    (env["session"] / "model.json").write_text("{not json", encoding="utf-8")
    mod = _load("select_model.py")
    code, out = _run(
        mod,
        ["select_model.py", "--config", str(env["config"]), "--session", str(env["session"])],
        monkeypatch,
        capsys,
    )
    assert code == 2
    assert "unreadable" in out["error"]


# --------------------------------------------------------------------------- #
# dispatch
# --------------------------------------------------------------------------- #


def test_dispatch_prefers_recorded_choice_over_default(env, monkeypatch, capsys) -> None:
    (env["session"] / "model.json").write_text(
        json.dumps({"schema": "model_choice/v1", "model": "minimax-music3", "source": "user"}),
        encoding="utf-8",
    )
    mod = _load("generate_take.py")
    code, out = _run(
        mod,
        ["generate_take.py", "--config", str(env["config"]), "--session", str(env["session"]),
         "--seed", "7"],
        monkeypatch,
        capsys,
    )
    # The audiocpp generator itself fails (no caption.md in this fixture), but the
    # routing decision is what this test pins down.
    assert out["model"] == "minimax-music3"
    assert out["model_source"] == "session"
    assert out["generator"] == "generate_audiocpp.py"
    assert code == 2


def test_dispatch_defaults_to_yue2(env, monkeypatch, capsys) -> None:
    mod = _load("generate_take.py")
    code, out = _run(
        mod,
        ["generate_take.py", "--config", str(env["config"]), "--session", str(env["session"]),
         "--seed", "7"],
        monkeypatch,
        capsys,
    )
    assert out["model"] == "yue2"
    assert out["model_source"] == "default"
    assert out["generator"] == "generate_yue2.py"
    assert code == 2


def test_dispatch_rejects_backend_specific_flags(env, monkeypatch, capsys) -> None:
    """yue2 has no length control; a MiniMax flag must not be forwarded silently."""
    mod = _load("generate_take.py")
    code, out = _run(
        mod,
        ["generate_take.py", "--config", str(env["config"]), "--session", str(env["session"]),
         "--seed", "7", "--duration-sec", "30"],
        monkeypatch,
        capsys,
    )
    assert code == 2
    assert "--duration-sec" in out["error"] and "not supported" in out["error"]


def test_dispatch_reserves_contract_flags_from_extra_arg(env, monkeypatch, capsys) -> None:
    """--extra-arg must not be able to rewrite the session file contract."""
    mod = _load("generate_take.py")
    for smuggled in ("--seed 99", "--take-id 7", "--session /tmp/elsewhere"):
        code, out = _run(
            mod,
            ["generate_take.py", "--config", str(env["config"]), "--session", str(env["session"]),
             "--seed", "7", "--extra-arg", smuggled],
            monkeypatch,
            capsys,
        )
        assert code == 2, smuggled
        assert "may not set" in out["error"], smuggled


def test_dispatch_passes_model_native_flags_through(env, monkeypatch, capsys) -> None:
    """A backend-native flag reaches the child instead of being rejected."""
    mod = _load("generate_take.py")
    captured: dict = {}

    class _Proc:
        returncode = 2
        stdout = json.dumps({"schema": "generate/v1", "ok": False, "error": "stub"})
        stderr = ""

    def _fake_run(cmd, **_kwargs):
        captured["cmd"] = cmd
        return _Proc()

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)
    code, out = _run(
        mod,
        ["generate_take.py", "--config", str(env["config"]), "--session", str(env["session"]),
         "--seed", "7", "--extra-arg", "--quantization fp8"],
        monkeypatch,
        capsys,
    )
    assert code == 2
    # Forwarded attached to --extra-arg (which the generator re-splits), so a
    # value starting with "--" is not read as an option by the child argparse.
    assert captured["cmd"][-1] == "--extra-arg=--quantization fp8"
    assert out["extra_args"] == ["--quantization", "fp8"]


# --------------------------------------------------------------------------- #
# yue2 input guards (fire before any runtime call, so they are host-independent)
# --------------------------------------------------------------------------- #


def test_yue2_refuses_empty_lyrics_for_instrumentals(env, monkeypatch, capsys) -> None:
    (env["session"] / "style.txt").write_text("English, solo piano, 60 BPM", encoding="utf-8")
    (env["session"] / "lyrics.txt").write_text("", encoding="utf-8")
    mod = _load("generate_yue2.py")
    code, out = _run(
        mod,
        ["generate_yue2.py", "--config", str(env["config"]), "--session", str(env["session"]),
         "--seed", "7"],
        monkeypatch,
        capsys,
    )
    assert code == 2
    assert out["ok"] is False
    assert "instrumental" in out["error"]


def test_yue2_ignores_a_bom_when_detecting_empty_lyrics(env, monkeypatch, capsys) -> None:
    """A BOM-prefixed 'empty' lyrics file is still empty (editors add one)."""
    (env["session"] / "style.txt").write_text("English, solo piano, 60 BPM", encoding="utf-8")
    (env["session"] / "lyrics.txt").write_bytes(b"\xef\xbb\xbf\r\n")
    mod = _load("generate_yue2.py")
    code, out = _run(
        mod,
        ["generate_yue2.py", "--config", str(env["config"]), "--session", str(env["session"]),
         "--seed", "7"],
        monkeypatch,
        capsys,
    )
    assert code == 2
    assert "instrumental" in out["error"]


def test_audiocpp_warns_that_empty_lyrics_cannot_be_instrumental() -> None:
    """MiniMax has no instrumental mode either; the attempt must be flagged."""
    mod = _load("generate_audiocpp.py")
    for empty in ("", "   \n", "\ufeff\r\n"):
        warnings = mod.lyrics_warnings(empty)
        assert len(warnings) == 1 and "no instrumental mode" in warnings[0], repr(empty)
    assert mod.lyrics_warnings("[Verse]\nsing") == []


# --------------------------------------------------------------------------- #
# yue2 score-first (plan -> review -> render)
# --------------------------------------------------------------------------- #


def test_next_index_counts_plans_and_takes_separately(workdir: Path) -> None:
    """Plans have their own numbering, so planning never consumes a take id."""
    mod = _load("generate_yue2.py")
    assert mod.next_index(workdir / "plans", "plan") == 1  # missing dir is fine
    plans = workdir / "plans"
    (plans / "plan-01").mkdir(parents=True)
    (plans / "plan-02").mkdir()
    (plans / "plan-01.request.json").write_text("{}", encoding="utf-8")
    assert mod.next_index(plans, "plan") == 3
    (plans / "plan-07.edited.abc").write_text("X:1", encoding="utf-8")
    assert mod.next_index(plans, "plan") == 8
    # A take-namespace directory must not leak into plan numbering.
    takes = workdir / "takes"
    (takes / "take-09.yue2").mkdir(parents=True)
    assert mod.next_index(takes, "take") == 10
    assert mod.next_index(plans, "plan") == 8


def test_score_edit_detection_uses_bytes_not_paths(workdir: Path) -> None:
    """A verbatim copy is not an edit; a changed byte is. Manifest-driven."""
    mod = _load("generate_yue2.py")
    plan = workdir / "plans" / "plan-01"
    plan.mkdir(parents=True)
    score = plan / "score.abc"
    score.write_text("X:1\nK:D\n\"G\"z4|\n", encoding="utf-8")
    (plan / "plan_manifest.json").write_text(
        json.dumps({"score.abc": mod.sha256_file(score)}), encoding="utf-8"
    )
    assert mod.score_edit_state(plan, score) is False
    copy = workdir / "copy.abc"
    copy.write_text(score.read_text(encoding="utf-8"), encoding="utf-8")
    assert mod.score_edit_state(plan, copy) is False  # same bytes, different path
    copy.write_text(score.read_text(encoding="utf-8").replace('"G"', '"Em"'), encoding="utf-8")
    assert mod.score_edit_state(plan, copy) is True
    # No manifest => unknown, never guessed.
    (plan / "plan_manifest.json").unlink()
    assert mod.score_edit_state(plan, score) is None


def test_score_preview_is_capped(workdir: Path) -> None:
    mod = _load("generate_yue2.py")
    score = workdir / "score.abc"
    score.write_text("\n".join(f"line {i}" for i in range(60)), encoding="utf-8")
    preview = mod.score_preview(score, max_lines=10)
    lines = preview.splitlines()
    assert len(lines) == 11 and "50 more lines" in lines[-1]
    assert mod.score_preview(workdir / "missing.abc") == ""


def test_dispatch_rejects_plan_mode_for_models_without_it(env, monkeypatch, capsys) -> None:
    """minimax-music3 has no plan stage; the dispatcher must say so, not guess."""
    (env["session"] / "model.json").write_text(
        json.dumps({"schema": "model_choice/v1", "model": "minimax-music3"}), encoding="utf-8"
    )
    mod = _load("generate_take.py")
    code, out = _run(
        mod,
        ["generate_take.py", "--config", str(env["config"]), "--session", str(env["session"]),
         "--seed", "7", "--stage", "plan"],
        monkeypatch,
        capsys,
    )
    assert code == 2
    assert "not supported" in out["error"] and "--stage" in out["error"]
    assert out["schema"] == "plan/v1"  # the request was a plan, so report as one


def test_dispatch_requires_a_seed_unless_rendering_a_plan(env, monkeypatch, capsys) -> None:
    mod = _load("generate_take.py")
    code, out = _run(
        mod,
        ["generate_take.py", "--config", str(env["config"]), "--session", str(env["session"])],
        monkeypatch,
        capsys,
    )
    assert code == 2 and "--seed" in out["error"]
    # With --from-plan the seed comes from the plan, so it is not required.
    code, out = _run(
        mod,
        ["generate_take.py", "--config", str(env["config"]), "--session", str(env["session"]),
         "--from-plan", str(env["session"] / "plans" / "plan-01")],
        monkeypatch,
        capsys,
    )
    assert "--seed is required" not in out.get("error", ""), out


def test_yue2_plan_mode_rejects_cot_off(env, monkeypatch, capsys) -> None:
    """cot=off sketches no score, so there is nothing to review."""
    (env["session"] / "style.txt").write_text("English, warm piano pop", encoding="utf-8")
    (env["session"] / "lyrics.txt").write_text("[Verse]\nsing", encoding="utf-8")
    mod = _load("generate_yue2.py")
    code, out = _run(
        mod,
        ["generate_yue2.py", "--config", str(env["config"]), "--session", str(env["session"]),
         "--seed", "7", "--stage", "plan", "--cot", "off"],
        monkeypatch,
        capsys,
    )
    assert code == 2
    assert out["schema"] == "plan/v1" and "cot=off" in out["error"]


def test_yue2_score_file_requires_a_plan(env, monkeypatch, capsys) -> None:
    (env["session"] / "style.txt").write_text("English, warm piano pop", encoding="utf-8")
    (env["session"] / "lyrics.txt").write_text("[Verse]\nsing", encoding="utf-8")
    mod = _load("generate_yue2.py")
    code, out = _run(
        mod,
        ["generate_yue2.py", "--config", str(env["config"]), "--session", str(env["session"]),
         "--seed", "7", "--score-file", "x.abc"],
        monkeypatch,
        capsys,
    )
    assert code == 2 and "--score-file requires --from-plan" in out["error"]


def test_yue2_extra_arg_cannot_falsify_provenance(env, monkeypatch, capsys) -> None:
    """--style/--seed via --extra-arg would desync the frozen take request."""
    (env["session"] / "style.txt").write_text("English, warm piano pop", encoding="utf-8")
    (env["session"] / "lyrics.txt").write_text("[Verse]\nsing", encoding="utf-8")
    mod = _load("generate_yue2.py")
    code, out = _run(
        mod,
        ["generate_yue2.py", "--config", str(env["config"]), "--session", str(env["session"]),
         "--seed", "7", "--extra-arg", "--style something else"],
        monkeypatch,
        capsys,
    )
    assert code == 2
    assert "may not set --style" in out["error"]


def test_yue2_requires_a_style_prompt(env, monkeypatch, capsys) -> None:
    (env["session"] / "lyrics.txt").write_text("[Verse]\nsing", encoding="utf-8")
    mod = _load("generate_yue2.py")
    code, out = _run(
        mod,
        ["generate_yue2.py", "--config", str(env["config"]), "--session", str(env["session"]),
         "--seed", "7"],
        monkeypatch,
        capsys,
    )
    assert code == 2
    assert "style" in out["error"]


def test_yue2_style_falls_back_to_caption_description(env, monkeypatch, capsys) -> None:
    """Legacy sessions have no style.txt; the fallback is flagged, not silent."""
    (env["session"] / "lyrics.txt").write_text("[Verse]\nsing", encoding="utf-8")
    (env["session"] / "caption.json").write_text(
        json.dumps({"inputs": {"description": "English, warm piano pop, 88 BPM"}}),
        encoding="utf-8",
    )
    mod = _load("generate_yue2.py")
    style, source = mod.read_style(env["session"])
    assert style == "English, warm piano pop, 88 BPM"
    assert source == "caption.json"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def test_truthy_truncated_normalises_bool_and_dict() -> None:
    mod = _load("generate_yue2.py")
    assert mod.truthy_truncated(True) is True
    assert mod.truthy_truncated(False) is False
    assert mod.truthy_truncated(None) is False
    assert mod.truthy_truncated({"semantic": False, "audio": True}) is True
    assert mod.truthy_truncated({"semantic": False, "audio": False}) is False


def test_find_audio_prefers_upstream_nesting(workdir: Path) -> None:
    mod = _load("generate_yue2.py")
    out_dir = workdir / "take-01.yue2"
    nested = out_dir / "take-01"
    nested.mkdir(parents=True)
    assert mod.find_audio(out_dir, "take-01") is None
    (nested / "audio.flac").write_bytes(b"x")
    assert mod.find_audio(out_dir, "take-01") == nested / "audio.flac"


def test_retire_stale_dir_never_destroys_evidence(workdir: Path) -> None:
    mod = _load("generate_yue2.py")
    out_dir = workdir / "take-01.yue2"
    out_dir.mkdir()
    (out_dir / "result.json").write_text("{}", encoding="utf-8")
    retired = mod.retire_stale_dir(out_dir)
    assert retired is not None and Path(retired).is_dir()
    assert (Path(retired) / "result.json").is_file()
    assert not out_dir.exists()

    # A second retry must not clobber the first attempt's evidence.
    out_dir.mkdir()
    retired2 = mod.retire_stale_dir(out_dir)
    assert retired2 is not None and retired2 != retired
    assert Path(retired).is_dir() and Path(retired2).is_dir()


def test_runtime_runresult_exposes_ok() -> None:
    """Every runtime helper must answer `.ok`; a missing one is a runtime crash."""
    for name in ("generate_yue2.py", "setup_yue2.py", "select_model.py"):
        mod = _load(name)
        assert mod.RunResult(0, "", "").ok is True, name
        assert mod.RunResult(1, "", "boom").ok is False, name


def test_runtime_run_reports_success_by_exit_code(workdir: Path) -> None:
    """Drive Runtime for real (native mode, no shell) so `.ok` is exercised."""
    mod = _load("generate_yue2.py")
    rt = mod.Runtime({"runtime": "native"}, repo_root=workdir)
    good = rt.run([sys.executable, "-c", "raise SystemExit(0)"])
    bad = rt.run([sys.executable, "-c", "raise SystemExit(3)"])
    assert good.ok is True and good.rc == 0
    assert bad.ok is False and bad.rc == 3
    missing = rt.run([str(workdir / "definitely-not-a-binary")])
    assert missing.ok is False and missing.rc == 127


def test_runtime_path_mapping(workdir: Path) -> None:
    mod = _load("generate_yue2.py")
    rt = mod.Runtime({"runtime": "native"}, repo_root=workdir)
    # Repo-relative paths resolve against the repo root...
    assert rt.path("oss/yue2") == str(workdir / "oss" / "yue2")
    # ...POSIX-absolute paths pass through...
    assert rt.path("/root/models/yue2") == "/root/models/yue2"
    # ...and a host-absolute path is accepted by BOTH runtimes. This used to
    # return None for WSL, which broke every absolute --session / --from-plan
    # path (a real bug: only relative session paths ever worked).
    host_abs = workdir / "abs"
    assert rt.path(str(host_abs)) == str(host_abs)
    mapped = mod.Runtime({"runtime": "wsl"}, repo_root=workdir).path(str(host_abs))
    if os.name == "nt":
        assert mapped is not None and mapped.startswith("/mnt/"), mapped
        assert mapped.endswith("/abs") and "\\" not in mapped, mapped
    else:
        assert mapped == str(host_abs)
    assert rt.path("") is None

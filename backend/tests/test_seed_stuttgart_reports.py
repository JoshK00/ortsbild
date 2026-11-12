import importlib.util
from pathlib import Path

from api.public import case_id_of
from research.provider import ScriptedResearchProvider
from tests.image_helpers import make_jpeg
from tests.test_api_reports import FOUND, Env, OneFace

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "seed_stuttgart_reports.py"


def load_script():
    spec = importlib.util.spec_from_file_location("seed_stuttgart_reports", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_seed_reports_go_through_the_real_api_and_show_up_in_the_dashboard(tmp_path):
    seed = load_script()
    for name in ("pothole.jpg", "playground.jpg", "graffiti.jpg"):
        (tmp_path / name).write_bytes(make_jpeg())
    with Env(face_detector=OneFace(), research_provider=ScriptedResearchProvider(FOUND)) as env:
        env.demo_reporters.append(env.client.post("/v1/auth/apple", json={"identity_token": "apple:seed", "nonce": "n"}).json()["reporter_id"])
        lines = seed.seed(env.client, env.login("seed"), tmp_path)
        again = seed.seed(env.client, env.login("seed"), tmp_path)  # a repeat creates nothing new
        shown = env.client.get("/v1/public/cases").json()["cases"]
    assert len(lines) == len(seed.REPORTS) == 7
    assert all(line["result"] == "released" for line in lines), lines
    assert [line["key"] for line in again] == [line["key"] for line in lines]
    # pothole x3 = one case with 3 votes, playground x2 = one case with 2 votes, graffiti and the lamp one each: 4 cases
    assert sorted(case["reports_count"] for case in shown) == [1, 1, 2, 3]
    assert {case["category"] for case in shown} == {"pothole", "playground_equipment", "graffiti", "street_light"}
    assert sum(1 for case in shown if case["photo_url"]) == 3  # the street light has no photo
    assert all(case["address"] and "Stuttgart" in case["address"] for case in shown)


def test_a_missing_photo_file_does_not_stop_the_script(tmp_path, capsys):
    seed = load_script()
    with Env(research_provider=ScriptedResearchProvider(FOUND)) as env:
        lines = seed.seed(env.client, env.login("seed"), tmp_path, reports=seed.REPORTS[:1])
    assert lines[0]["result"] == "released" and lines[0]["photo"] is False
    assert "not found" in capsys.readouterr().out

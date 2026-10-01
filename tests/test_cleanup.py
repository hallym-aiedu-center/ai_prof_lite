import json

from core.config import data_dir
from core.database.client import get_connection
from modules.lecture.cleanup import cleanup_lecture_runs


async def test_cleanup_removes_only_unreferenced_run_dirs(make_lecture, monkeypatch):
    monkeypatch.setenv("LECTURE_ORPHAN_RUN_RETENTION_HOURS", "0")
    lecture_id = await make_lecture()
    runs = data_dir() / "lectures" / str(lecture_id) / "runs"
    referenced = runs / "keep-token"
    orphan = runs / "orphan-token"
    referenced.mkdir(parents=True)
    orphan.mkdir(parents=True)
    kept_file = referenced / "plan.json"
    kept_file.write_text("{}", encoding="utf-8")
    (orphan / "partial.tmp").write_text("partial", encoding="utf-8")

    db = await get_connection()
    try:
        await db.execute(
            "INSERT INTO lecture_stages(lecture_id,name,status,outputs_json) VALUES(?,?,?,?)",
            (lecture_id, "plan", "completed", json.dumps({"files": [str(kept_file)]})),
        )
        await db.commit()
    finally:
        await db.close()

    removed = await cleanup_lecture_runs(lecture_id)
    assert orphan in removed
    assert not orphan.exists()
    assert referenced.is_dir()
    assert kept_file.is_file()

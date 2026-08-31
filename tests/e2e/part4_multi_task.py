"""E2E Part 4 — 多任务场景：上传→任务1(单文件转换)→自动清理→再上传→
任务2(合并)→会话保持重载→任务3(书库导入单文件)。验证跨任务无状态污染。"""
import json
import time

from common import BASE, SHOTS, ffprobe, ok, report
from playwright.sync_api import sync_playwright


def jobs(pg):
    return json.loads(pg.request.get(f"{BASE}/api/jobs").text())


def wait_all_done(pg, timeout=240, want=None):
    deadline = time.time() + timeout
    while time.time() < deadline:
        js = jobs(pg)
        target = [j for j in js if not want or j["id"] in want]
        if target and all(j["status"] in ("done", "failed") for j in target):
            return js
        time.sleep(0.5)
    raise TimeoutError("jobs not finished")


def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1440, "height": 950})
        pg.goto(BASE)
        pg.wait_for_selector("#health-badge.pill.ok", timeout=8000)

        # ===== 任务 1：上传 2 个文件 → 逐文件转换 =====
        pg.set_input_files("#file-input", ["/tmp/hac-e2e/ch1.mp3", "/tmp/hac-e2e/ch2.m4a"])
        pg.wait_for_function("state.uploads.length === 2", timeout=30000)
        pg.select_option("#preset", "audiobook_opus_48k")
        pg.click("#btn-start")
        pg.wait_for_function(
            "Object.values(state.jobs).filter(j=>j.status==='done').length >= 2",
            timeout=120000)
        ok("任务1：2 个单文件转换完成", True)
        time.sleep(1.5)   # 等自动清理广播落定
        ok("任务1：完成后上传已自动清理", pg.evaluate("state.uploads.length") == 0,
           f"remaining={pg.evaluate('state.uploads.length')}")

        # ===== 会话保持：重载页面，任务仍在、文件仍为空 =====
        pg.reload()
        pg.wait_for_selector("#health-badge.pill.ok", timeout=8000)
        pg.wait_for_function(
            "Object.values(state.jobs).filter(j=>j.status==='done').length >= 2",
            timeout=15000)
        ok("重载后任务历史保留", pg.evaluate("Object.values(state.jobs).length") >= 2)
        ok("重载后文件列表仍为空（清理状态持久）",
           pg.evaluate("state.uploads.length") == 0)

        # ===== 任务 2：再上传 3 个文件 + 封面 → 合并（含无标签文件，验证章节名无 id 前缀）=====
        subprocess = __import__("subprocess")
        for name in ("未命名章节A.m4a", "未命名章节B.m4a"):
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                            "-i", "sine=frequency=520:duration=0.4", "-c:a", "aac",
                            str(f"/tmp/{name}")], check=True)   # 无任何标签
        pg.set_input_files("#file-input",
                           ["/tmp/hac-e2e/ch1.mp3", "/tmp/hac-e2e/ch2.m4a",
                            "/tmp/未命名章节A.m4a", "/tmp/未命名章节B.m4a"])
        pg.wait_for_function("state.uploads.length === 4", timeout=30000)
        pg.set_input_files("#merge-cover", "/tmp/hac-e2e/cover.jpg")
        pg.check("#merge-on")
        pg.fill("#merge-title", "多任务场景合并")
        pg.fill("#merge-composer", "演播者乙")
        pg.select_option("#preset", "audiobook_aac_lc_64k")
        pg.click("#btn-start")
        pg.wait_for_function(
            "Object.values(state.jobs).some(j=>j.mode==='merge' && j.status==='done')",
            timeout=120000)
        merge_job = next(j for j in jobs(pg)
                         if j["mode"] == "merge" and j["status"] == "done")
        data = ffprobe(merge_job["output_path"])
        chapters = data.get("chapters", [])
        titles = [c.get("tags", {}).get("title", "") for c in chapters]
        ok("任务2：4 章合并完成", len(chapters) == 4, f"n={len(chapters)}")
        ok("任务2：有标签章节名来自标签",
           titles[0] == "第一章 开端" and titles[1] == "第二章 转折", str(titles))
        ok("任务2：无标签章节名=干净文件名（无 id 前缀）",
           titles[2] == "未命名章节A" and titles[3] == "未命名章节B", str(titles))
        ok("任务2：全局元数据", data["format"]["tags"].get("title") == "多任务场景合并"
           and data["format"]["tags"].get("composer") == "演播者乙")
        pg.screenshot(path=str(SHOTS / "12-multi-task.png"))

        # ===== 会话保持：再重载，合并任务可见且文件已清理 =====
        pg.reload()
        pg.wait_for_selector("#health-badge.pill.ok", timeout=8000)
        pg.wait_for_function(
            "Object.values(state.jobs).some(j=>j.mode==='merge' && j.status==='done')",
            timeout=15000)
        ok("重载后合并任务可见", True)
        time.sleep(1.0)
        ok("重载后文件列表为空", pg.evaluate("state.uploads.length") == 0)

        # ===== 任务 3：书库导入单文件转换 =====
        pg.click('.tab[data-tab="library"]')
        pg.wait_for_function(
            "document.querySelectorAll('#lib-list li').length > 0", timeout=10000)
        pg.get_by_text("testbook/").click()
        pg.wait_for_function(
            "[...document.querySelectorAll('#lib-list .name')]"
            ".some(e => e.textContent.includes('ch3.flac'))", timeout=10000)
        pg.locator('#lib-list input.libpick[data-libid*="ch3.flac"]').check()
        pg.select_option("#preset", "audiobook_opus_48k")
        pg.click("#btn-start")
        pg.wait_for_function(
            "Object.values(state.jobs).some(j=>j.source_ids.some(s=>s.startsWith('lib:')) "
            "&& j.status==='done')", timeout=120000)
        ok("任务3：书库导入单文件完成", True)

        # ===== 交叉验证：任务1 与任务2 的输出互不干扰 =====
        js = jobs(pg)
        singles = [j for j in js if j["mode"] == "single" and j["status"] == "done"]
        merges = [j for j in js if j["mode"] == "merge" and j["status"] == "done"]
        ok("多任务并存：单文件与合并任务输出齐备", len(singles) >= 2 and len(merges) >= 1,
           f"singles={len(singles)} merges={len(merges)}")
        for m in merges:
            ok("合并产物存在", m["output_path"] and
               __import__("pathlib").Path(m["output_path"]).exists())
        pg.screenshot(path=str(SHOTS / "13-jobs-history.png"))

        b.close()


if __name__ == "__main__":
    main()
    raise SystemExit(report("Part4"))

"""E2E Part 2 — M4B merge (chapters/cover/composer/HE params), loudnorm,
per-param hints, folder upload, library import + 403, cancel/retry/clear."""
import json
import os
import subprocess
import time

from common import BASE, SHOTS, ffprobe, ok, report
from playwright.sync_api import sync_playwright


def jobs(pg):
    return json.loads(pg.request.get(f"{BASE}/api/jobs").text())


def finished_count(pg):
    js = jobs(pg)
    return js, len([j for j in js if j["status"] in ("done", "failed")])


def wait_new_finished(pg, baseline, timeout=180):
    deadline = time.time() + timeout
    while time.time() < deadline:
        js, n = finished_count(pg)
        if n > baseline:
            return ([j for j in js if j["status"] == "done"],
                    [j for j in js if j["status"] == "failed"])
        time.sleep(0.5)
    raise TimeoutError("no new finished job")


def wait_job_status(pg, job_id, statuses, timeout=180):
    deadline = time.time() + timeout
    while time.time() < deadline:
        j = next((x for x in jobs(pg) if x["id"] == job_id), None)
        if j and j["status"] in statuses:
            return j
        time.sleep(0.5)
    raise TimeoutError(f"job {job_id} never reached {statuses}")


def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1440, "height": 950})
        pg.goto(BASE)
        pg.wait_for_selector("#health-badge.pill.ok", timeout=8000)

        # ===== F1: M4B merge with chapters + cover + composer =====
        pg.set_input_files("#file-input",
                           ["/tmp/hac-e2e/ch1.mp3", "/tmp/hac-e2e/ch2.m4a",
                            "/tmp/hac-e2e/ch3.mp3"])
        pg.wait_for_function(
            "document.querySelectorAll('#file-list tr').length >= 3", timeout=30000)
        pg.set_input_files("#merge-cover", "/tmp/hac-e2e/cover.jpg")
        pg.check("#merge-on")
        ok("merge fields visible", pg.locator("#merge-fields").is_visible())
        pg.fill("#merge-title", "测试有声书")
        pg.fill("#merge-artist", "测试作者")
        pg.fill("#merge-composer", "测试演播者")
        pg.select_option("#preset", "audiobook_aac_lc_64k")
        _, baseline = finished_count(pg)
        pg.click("#btn-start")
        done, failed = wait_new_finished(pg, baseline, timeout=120)
        mj = [j for j in done + failed if j["mode"] == "merge"]
        ok("merge job created", len(mj) == 1)
        ok("merge job done", mj and mj[0]["status"] == "done",
           str(mj[0].get("error") or "")[:80] if mj else "")
        pg.screenshot(path=str(SHOTS / "05-merge-done.png"))

        if mj and mj[0]["status"] == "done":
            data = ffprobe(mj[0]["output_path"])
            chapters = data.get("chapters", [])
            ok("M4B has 3 chapters", len(chapters) == 3, f"n={len(chapters)}")
            if len(chapters) == 3:
                ok("chapters contiguous",
                   chapters[1]["start_time"] == chapters[0]["end_time"])
                titles = [c.get("tags", {}).get("title", "") for c in chapters]
                ok("chapter titles in upload order",
                   titles == ["第一章 开端", "第二章 转折", "第三章 结局"], str(titles))
            fmt = data["format"]
            ok("M4B title/artist", fmt["tags"].get("title") == "测试有声书"
               and fmt["tags"].get("artist") == "测试作者")
            ok("M4B composer (演播者)", fmt["tags"].get("composer") == "测试演播者")
            st = data["streams"][0]
            ok("M4B aac mono .m4b", st["codec_name"] == "aac" and st["channels"] == 1
               and mj[0]["output_path"].endswith(".m4b"))
            vst = [s for s in data["streams"] if s["codec_type"] == "video"]
            ok("M4B cover attached_pic", len(vst) == 1
               and vst[0].get("disposition", {}).get("attached_pic") == 1)

        # ===== F1b: merge adopts user encoding (HE-AAC) + per-param hints =====
        # feature-6 cleanup consumed the uploads after the previous merge — re-add
        pg.set_input_files("#file-input", ["/tmp/hac-e2e/ch1.mp3", "/tmp/hac-e2e/ch2.m4a"])
        pg.wait_for_function("state.uploads.length >= 2", timeout=30000)
        pg.select_option("#preset", "audiobook_aac_he_48k")
        _, base_he = finished_count(pg)
        pg.click("#btn-start")
        done, failed = wait_new_finished(pg, base_he, timeout=120)
        he_merge = [j for j in done + failed if j["mode"] == "merge"][-1]
        ok("HE merge done", he_merge["status"] == "done",
           str(he_merge.get("error") or "")[:80])
        if he_merge["status"] == "done":
            hd = ffprobe(he_merge["output_path"])
            ok("HE merge keeps HE-AAC profile",
               hd["streams"][0].get("profile") == "HE-AAC",
               str(hd["streams"][0].get("profile")))

        # per-param compatibility hints
        pg.select_option("#preset", "audiobook_opus_48k")
        pg.wait_for_function(
            "document.getElementById('err-codec').textContent.includes('libopus')",
            timeout=5000)
        ok("per-param hint for opus+merge", True)
        ok("start disabled while incompatible", pg.locator("#btn-start").is_disabled())
        pg.select_option("#preset", "audiobook_aac_lc_64k")
        pg.wait_for_function(
            "document.getElementById('err-codec').textContent === ''", timeout=5000)
        ok("hint clears when AAC selected", True)
        pg.uncheck("#merge-on")   # subsequent tests run in per-file mode

        # ===== folder upload =====
        before = pg.evaluate("state.uploads.length")
        pg.set_input_files("#folder-input", "data/library/testbook")
        pg.wait_for_timeout(2500)
        after = pg.evaluate("state.uploads.length")
        ok("folder upload collects audio", after > before, f"{before}→{after}")

        # ===== F2: loudnorm =====
        pg.set_input_files("#file-input", ["/tmp/hac-e2e/long2.wav"])
        pg.wait_for_function("state.uploads.some(u=>u.name.includes('long2'))",
                             timeout=60000)
        pg.select_option("#preset", "audiobook_opus_48k")
        pg.evaluate("document.getElementById('adv-box').open = true")
        pg.check("#normalize")
        _, base_ln = finished_count(pg)
        pg.click("#btn-start")
        done, failed = wait_new_finished(pg, base_ln, timeout=240)
        ok("loudnorm job done", not failed,
           str([f.get("error") for f in failed])[:80] if failed else "")
        js = jobs(pg)
        ln = sorted([j for j in js if j["status"] == "done" and j.get("normalize")],
                    key=lambda j: j["created_at"])
        if ln:
            m = subprocess.run(["ffmpeg", "-i", ln[-1]["output_path"],
                                "-af", "ebur128=framelog=quiet", "-f", "null", "-"],
                               capture_output=True, text=True)
            lufs = float([l for l in m.stderr.splitlines()
                          if "I:" in l and "LUFS" in l]
                         [-1].split("I:")[1].split("LUFS")[0].strip())
            ok("loudnorm ≈ -20 LUFS (±3)", -23 <= lufs <= -17, f"{lufs}")
        pg.uncheck("#normalize")

        # ===== F3: library import (fresh tab = user reopening the page) =====
        pg2 = b.new_page()
        pg2.goto(BASE)
        pg2.wait_for_selector("#health-badge.pill.ok", timeout=8000)
        pg2.click('.tab[data-tab="library"]')
        pg2.wait_for_function(
            "document.querySelectorAll('#lib-list tr').length > 0", timeout=10000)
        ok("library roots shown (书库名)", "library" in pg2.inner_text("#lib-roots"))
        pg2.get_by_text("testbook/").click()
        pg2.wait_for_function(
            "[...document.querySelectorAll('#lib-list .name-cell')]"
            ".some(e => e.textContent.includes('ch3.flac'))", timeout=10000)
        pg2.evaluate("state.uploads = []")   # isolate: only the library file
        pg2.locator('#lib-list input.libpick[data-libid*="ch3.flac"]').check()
        pg2.select_option("#preset", "audiobook_opus_48k")
        pg2.click("#btn-start")
        deadline = time.time() + 120
        lib_jobs = []
        while time.time() < deadline:
            js = json.loads(pg2.request.get(f"{BASE}/api/jobs").text())
            lib_jobs = [j for j in js
                        if any(s.startswith("lib:") for s in j["source_ids"])]
            if lib_jobs and all(j["status"] == "done" for j in lib_jobs):
                break
            time.sleep(0.5)
        ok("library import (zero upload)", len(lib_jobs) == 1
           and lib_jobs[0]["status"] == "done",
           f"n={len(lib_jobs)}")
        r1 = pg2.request.get(f"{BASE}/api/library/list?path=/etc")
        ok("403 outside whitelist", r1.status == 403, f"status={r1.status}")
        ok("UI 不暴露服务器路径", "/home/" not in pg2.inner_text("#col-files"))
        pg2.close()
        pg.screenshot(path=str(SHOTS / "07-library.png"))

        # ===== Test 8: cancel / retry / cancel-all / clear =====
        pg.click('.tab[data-tab="upload"]')
        pg.set_input_files("#file-input", ["/tmp/hac-e2e/long2.wav"])
        pg.wait_for_function("state.uploads.some(u=>u.name.includes('long2'))",
                             timeout=60000)
        pg.select_option("#preset", "audiobook_opus_32k")
        pg.click("#btn-start")
        pg.wait_for_selector("#job-list .badge.running", timeout=30000)
        pg.locator('[data-act="cancel"]').first.click()
        pg.wait_for_selector("#job-list .badge.cancelled", timeout=8000)
        ok("running job cancelled via UI", True)
        cancelled_id = next(j["id"] for j in jobs(pg) if j["status"] == "cancelled")
        pg.locator('[data-act="retry"]').first.click()
        rj = wait_job_status(pg, cancelled_id, ("done", "failed"), timeout=180)
        ok("retry re-runs to done", rj["status"] == "done")
        pg.click("#btn-cancel-all")
        deadline = time.time() + 15
        while time.time() < deadline:
            if not [j for j in jobs(pg)
                    if j["status"] in ("queued", "running", "tagging", "merging")]:
                break
            time.sleep(0.5)
        ok("cancel-all leaves no active", not [j for j in jobs(pg)
           if j["status"] in ("queued", "running", "tagging", "merging")])
        pg.click("#btn-clear-finished")
        deadline = time.time() + 10
        while time.time() < deadline:
            js = jobs(pg)
            if js and all(j.get("output_deleted_at") for j in js):
                break
            time.sleep(0.5)
        ok("clear-finished: 产物清理但历史保留",
           bool(js) and all(j.get("output_deleted_at") for j in js),
           str([(j["id"], bool(j.get("output_deleted_at"))) for j in js]))
        pg.screenshot(path=str(SHOTS / "08-cleared.png"))

        # ===== F8: 批量重命名 + 写 tag =====
        import subprocess as _sp
        _sp.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                 "-i", "sine=frequency=500:duration=0.3", "-c:a", "libmp3lame",
                 "/tmp/hac-e2e/1 风起·萧鼎.mp3"], check=True)
        _sp.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                 "-i", "sine=frequency=600:duration=0.3", "-c:a", "libmp3lame",
                 "/tmp/hac-e2e/2 云涌·萧鼎.mp3"], check=True)
        pg.click('.tab[data-tab="uploads"]')
        pg.set_input_files("#file-input",
                           ["/tmp/hac-e2e/1 风起·萧鼎.mp3", "/tmp/hac-e2e/2 云涌·萧鼎.mp3"])
        pg.wait_for_function(
            "(state.uploadsAllRaw||[]).some(u=>u.name.includes('风起'))",
            timeout=30000)
        pg.evaluate("""() => {
          document.querySelectorAll('#uploads-list input.up-pick').forEach(cb => {
            const u = (state.uploadsAllRaw||[]).find(x=>x.id===cb.dataset.upid);
            cb.checked = !!(u && /风起|云涌/.test(u.name));
            cb.dispatchEvent(new Event("change"));
          });
        }""")
        pg.click("#btn-batch")
        pg.wait_for_selector("#batch-drawer:not(.hidden)")
        pg.fill("#batch-template", "${TrackNum:3} ${TrackTitle}·${Artist}")
        pg.check("#batch-writetags")
        pg.wait_for_timeout(800)   # 预览
        rows = pg.evaluate("""[...document.querySelectorAll('#batch-preview tr')]
                           .map(tr => ({cls: tr.className,
                                        txt: tr.textContent.slice(0, 120)}))""" )
        ok("F8: 预览两行 ok", rows and all("bad" not in r for r in rows), str(rows))
        pg.click("#batch-run")
        pg.wait_for_timeout(1200)
        rep = pg.evaluate("document.getElementById('batch-report').textContent")
        ok("F8: 执行报告", "成功 2" in rep, rep)
        names = pg.evaluate("(state.uploadsAllRaw||[]).map(u=>u.name)")
        ok("F8: 注册表重命名", "001 风起·萧鼎.mp3" in names and "002 云涌·萧鼎.mp3" in names,
           str(names))
        # ffprobe 回读 tag
        import glob as _glob
        _f = _glob.glob(os.path.join(os.environ["E2E_DATA"], "uploads",
                                     "*_001 风起·萧鼎.mp3"))
        ok("F8: 重命名文件落盘", bool(_f), str(_f))
        hd = ffprobe(_f[0])
        tg = hd["format"].get("tags", {})
        ok("F8: tag 写入（artist/track）",
           tg.get("artist") == "萧鼎" and tg.get("track", "").startswith("1/"),
           str(tg))

        pg.click("#batch-close")

        # ===== F9: 播放 / A/B 对比 =====
        pg.click('.tab[data-tab="uploads"]')
        pg.click('#uploads-list [data-play]')
        pg.wait_for_selector("#mini-player:not(.hidden)")
        pg.wait_for_function(
            "document.getElementById('mp-audio').readyState >= 2", timeout=15000)
        _dur = pg.evaluate("document.getElementById('mp-audio').duration")
        ok("F9: mini 试听 canplay", _dur and _dur > 0.2, str(_dur))
        pg.click("#mp-close")

        # 产物转码（aac 输出）后 A/B
        pg.evaluate("""() => {
          document.getElementById('output-pattern').value = '';
        }""")
        pg.click('.tab[data-tab="upload"]')
        pg.set_input_files("#file-input", ["/tmp/hac-e2e/ch1.mp3"])
        pg.wait_for_function("state.uploads.some(u=>u.name.includes('ch1'))",
                             timeout=30000)
        pg.select_option("#preset", "audiobook_aac_lc_64k")
        pg.click("#btn-start")
        pg.wait_for_function(
            "Object.values(state.jobs).some(j=>j.mode==='single' && j.status==='done')",
            timeout=180000)
        pg.click('[data-act="abcmp"]')
        pg.wait_for_selector("#ab-drawer:not(.hidden)")
        pg.wait_for_function(
            "document.getElementById('ab-audio-a').readyState >= 2 && "
            "document.getElementById('ab-audio-b').readyState >= 2", timeout=15000)
        # A 侧 seek 到 0.3s → B 侧应同步
        pg.evaluate("document.getElementById('ab-audio-a').currentTime = 0.3")
        pg.wait_for_timeout(600)
        _a = pg.evaluate("document.getElementById('ab-audio-a').currentTime")
        _b = pg.evaluate("document.getElementById('ab-audio-b').currentTime")
        ok("F9: A/B seek 同步", abs(_a - _b) < 0.5, f"a={_a:.2f} b={_b:.2f}")
        # 双面板时长都有值（源/产物流可读）
        ok("F9: A/B 双侧时长", pg.evaluate(
            "document.getElementById('ab-audio-a').duration > 0.2") and pg.evaluate(
            "document.getElementById('ab-audio-b').duration > 0.2"))
        pg.click("#ab-close")

        # ===== F10: 分卷合并（UI 全流程）=====
        pg.click('.tab[data-tab="upload"]')
        _sp.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                 "-i", "sine=frequency=700:duration=0.3", "-c:a", "aac",
                 "/tmp/hac-e2e/f10a.m4a"], check=True)
        _sp.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                 "-i", "sine=frequency=800:duration=0.3", "-c:a", "aac",
                 "/tmp/hac-e2e/f10b.m4a"], check=True)
        _sp.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                 "-i", "sine=frequency=900:duration=0.3", "-c:a", "aac",
                 "/tmp/hac-e2e/f10c.m4a"], check=True)
        pg.click("#btn-clear-files")   # 隔离本用例：清掉前面步骤遗留的文件
        pg.wait_for_function("state.uploads.length === 0", timeout=10000)
        pg.set_input_files("#file-input",
                           ["/tmp/hac-e2e/f10a.m4a", "/tmp/hac-e2e/f10b.m4a",
                            "/tmp/hac-e2e/f10c.m4a"])
        pg.wait_for_function("state.uploads.length >= 3", timeout=30000)
        pg.check("#merge-on")
        pg.evaluate("document.getElementById('split-on').click()")
        pg.fill("#merge-split", "2")
        pg.fill("#merge-title", "分卷书")
        ok("F10: 拆分 hint 显示", pg.evaluate(
            "!document.getElementById('split-hint').classList.contains('hidden')"))
        pg.click("#btn-start")
        pg.wait_for_function(
            "Object.values(state.jobs).filter(j=>(j.output_filename||'').startsWith('分卷书')).length >= 2",
            timeout=30000)
        pg.wait_for_function(
            "Object.values(state.jobs).filter(j=>(j.output_filename||'').startsWith('分卷书')).every(j=>j.status==='done')",
            timeout=180000)
        _vols = [j for j in jobs(pg) if (j.get("output_filename") or "").startswith("分卷书")]
        ok("F10: 分卷 2 任务", len(_vols) == 2, str([j["output_filename"] for j in _vols]))
        ok("F10: 卷命名", sorted(j["output_filename"] for j in _vols) ==
           ["分卷书_01", "分卷书_02"], str([j["output_filename"] for j in _vols]))
        _f1 = _glob.glob(os.path.join(os.environ["E2E_DATA"], "outputs", "*_分卷书_01.m4b"))
        ok("F10: 卷1落盘", bool(_f1))
        _ch = ffprobe(_f1[0])
        _nch = len(_ch.get("chapters", []))
        ok("F10: 卷1 = 2 章", _nch == 2, str(_nch))

        # ===== F11: 直通合并（aac 源）=====
        # 直通：清列表后只放 2 个 aac（隔离早期 mp3 文件）
        pg.click("#btn-clear-files")
        pg.wait_for_function("state.uploads.length === 0", timeout=10000)
        pg.set_input_files("#file-input",
                           ["/tmp/hac-e2e/f10a.m4a", "/tmp/hac-e2e/f10b.m4a"])
        pg.wait_for_function("state.uploads.length >= 2", timeout=30000)
        pg.evaluate("document.getElementById('audio-copy').click()")
        ok("F11: 直通无 AAC 错误", pg.evaluate(
            "document.getElementById('copy-err').classList.contains('hidden')"))
        pg.evaluate("document.getElementById('split-off').click()")
        pg.click("#btn-start")
        pg.wait_for_function(
            "Object.values(state.jobs).some(j=>j.mode==='merge' && j.status==='done' && (j.output_filename||'').includes('直通') === false && !j.output_deleted_at && (j.merge ? j.merge.copy_audio === true : false))",
            timeout=180000)
        _pj = [j for j in jobs(pg)
               if j.get("merge", {}) and j["merge"].get("copy_audio")
               and j["status"] == "done"][-1]
        ok("F11: 直通任务 done", _pj["status"] == "done")
        _pf = ffprobe(_pj["output_path"])
        ok("F11: 音频流为 copy（aac 未重编码）",
           _pf["streams"][0]["codec_name"] == "aac")
        b.close()


if __name__ == "__main__":
    main()
    raise SystemExit(report("Part2"))

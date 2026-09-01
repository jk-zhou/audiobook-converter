"""E2E Part 1 — upload progress, preset wiring, transcode, verify panel, downloads."""
import json
import time
import zipfile

from common import BASE, SHOTS, ffprobe, ok, report
from playwright.sync_api import sync_playwright


def done_jobs(pg):
    return [j for j in json.loads(pg.request.get(f"{BASE}/api/jobs").text())
            if j["status"] == "done"]


def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1440, "height": 950})
        pg.goto(BASE)
        pg.wait_for_selector("#health-badge.pill.ok", timeout=8000)
        ok("page loads (3 panels + health)", pg.locator("#col-files").count() == 1
           and pg.locator("#col-settings").count() == 1
           and pg.locator("#col-jobs").count() == 1)
        pg.screenshot(path=str(SHOTS / "01-initial.png"))

        # 15MB first: its upload row stays visible long enough to observe
        pg.set_input_files("#file-input", ["/tmp/hac-e2e/long_ch.wav"])
        pg.wait_for_selector(".uprow", timeout=15000)
        ok("upload progress row visible during upload", pg.locator(".uprow").count() >= 1)
        pg.wait_for_function("state.uploads.some(u=>u.name.includes('long_ch'))",
                             timeout=30000)
        pg.set_input_files("#file-input", ["/tmp/hac-e2e/ch1.mp3", "/tmp/hac-e2e/ch2.m4a"])
        pg.wait_for_selector("#file-list tr:nth-child(3)", timeout=15000)
        txt = " ".join(pg.locator("#file-list tr").all_inner_texts())
        ok("files listed with size", "ch1.mp3" in txt and ("KB" in txt or "MB" in txt))
        pg.screenshot(path=str(SHOTS / "02-uploaded.png"))

        pg.select_option("#preset", "audiobook_opus_48k")
        ok("preset fills format/codec/bitrate/sr/ch",
           pg.input_value("#format") == "opus" and pg.input_value("#codec") == "libopus"
           and pg.input_value("#bitrate") == "48k"
           and pg.input_value("#samplerate") == "24000"
           and pg.input_value("#channels") == "1")
        pg.evaluate("document.getElementById('adv-box').open = true")
        pg.select_option("#bitrate", "64k")
        ok("manual change resets preset", pg.input_value("#preset") == "")
        pg.select_option("#preset", "audiobook_opus_48k")

        pg.click("#btn-start")
        pg.wait_for_selector('#job-list li:has-text("long_ch")', timeout=15000)
        samples = []
        long_bar = pg.locator('#job-list li:has-text("long_ch")').locator(".pbar > div")
        for _ in range(120):
            if long_bar.count():
                samples.append(float(long_bar.evaluate(
                    "el => parseFloat(el.style.width) || 0")))
            if samples and samples[-1] >= 100:
                break
            time.sleep(0.1)
        grew = sum(1 for s in samples if 0 < s < 100) >= 3
        ok("progress grew through intermediate values (real SSE)", grew,
           f"distinct={sorted(set(round(s) for s in samples))[:8]}")

        pg.wait_for_selector("#job-list .badge.done", timeout=120000)
        pg.wait_for_selector("#job-list .verify", timeout=10000)
        vtxt = pg.locator("#job-list .verify").first.inner_text()
        ok("verify panel shows codec", "opus" in vtxt, vtxt.strip()[:50])
        ok("verify shows savings", "省" in vtxt)
        pg.screenshot(path=str(SHOTS / "03-done-verify.png"))

        jobs = json.loads(pg.request.get(f"{BASE}/api/jobs").text())
        opus_jobs = [j for j in jobs
                     if j["status"] == "done" and j["settings"]["format"] == "opus"]
        info = ffprobe(opus_jobs[-1]["output_path"])
        st = info["streams"][0]
        ok("ffprobe: opus mono", st["codec_name"] == "opus" and st["channels"] == 1)
        br = int(info["format"]["bit_rate"])
        # Opus VBR overshoots on synthetic sine tones; real speech tracks target
        ok("ffprobe: bitrate ≈48k (VBR, sine tolerance)",
           36000 <= br <= 72000, f"{br}")

        with pg.expect_download() as dl:
            pg.locator('[data-act="dl"]').first.click()
        d = dl.value
        f1 = SHOTS / d.suggested_filename
        d.save_as(str(f1))
        ok("single download works", f1.exists() and f1.stat().st_size > 0,
           d.suggested_filename)

        ids = ",".join(j["id"] for j in done_jobs(pg))
        with pg.expect_download() as dl2:
            pg.evaluate(f"location.href='{BASE}/api/download/zip?ids={ids}'")
        d2 = dl2.value
        zt = SHOTS / d2.suggested_filename
        d2.save_as(str(zt))
        with zipfile.ZipFile(zt) as z:
            names = z.namelist()
        ok("zip download valid", len(names) == len(done_jobs(pg)),
           f"{len(names)} entries")
        b.close()


if __name__ == "__main__":
    main()
    raise SystemExit(report("Part1"))

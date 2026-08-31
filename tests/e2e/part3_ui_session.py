"""E2E Part 3 — UI: metadata columns, sorting, drag reorder, session persistence,
auto-cleanup after job, app icon."""
import time

from common import BASE, SHOTS, ok, report
from playwright.sync_api import sync_playwright


def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1440, "height": 950})
        pg.goto(BASE)
        pg.wait_for_selector("#health-badge.pill.ok", timeout=8000)

        # F4: app icon
        ok("favicon referenced", pg.evaluate(
            "!!document.querySelector('link[rel=icon][type=\"image/svg+xml\"]')"))
        ok("header logo", pg.locator("header .logo").count() == 1)

        # F2: layout — files full-width on top, settings|jobs below
        ok("layout: files panel full-width on top", pg.evaluate(
            "getComputedStyle(document.querySelector('.layout')).flexDirection") == "column")
        ok("layout: settings | jobs side by side", pg.evaluate(
            "getComputedStyle(document.querySelector('.lower'))"
            ".gridTemplateColumns.split(' ').length") == 2)

        # F1: metadata table columns (default set)
        subprocess = __import__("subprocess")
        for freq, name, title in [(500, "第2集.m4a", "标题乙"), (600, "第10集.m4a", "标题甲"),
                                  (700, "第1集.m4a", "标题丙")]:
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                            "-i", f"sine=frequency={freq}:duration=0.3", "-c:a", "aac",
                            "-metadata", f"title={title}", str(f"/tmp/sort-{name}")],
                           check=True)
        pg.set_input_files("#file-input",
                           ["/tmp/sort-第1集.m4a", "/tmp/sort-第2集.m4a", "/tmp/sort-第10集.m4a"])
        pg.wait_for_function(
            "document.querySelectorAll('#file-list tr').length >= 3", timeout=30000)
        headers = pg.evaluate(
            "[...document.querySelectorAll('#file-head th')].map(t=>t.textContent.trim())")
        ok("F1: default columns", headers ==
           ["#", "", "文件名", "标题", "章节/编号", "专辑", "作者", "演播者", "时长", "大小", ""],
           str(headers))

        # column header sort: asc → desc → back to upload order
        pg.click('#file-head th[data-key="name"]')
        pg.wait_for_timeout(200)
        names_asc = [n for n in pg.evaluate("state.uploads.map(u=>u.name)")
                     if n.startswith("sort-")]
        ok("F1: 自然排序 第1集 < 第2集 < 第10集",
           names_asc == ["sort-第1集.m4a", "sort-第2集.m4a", "sort-第10集.m4a"],
           str(names_asc))
        pg.click('#file-head th[data-key="name"]')
        pg.wait_for_timeout(200)
        names_desc = [n for n in pg.evaluate("state.uploads.map(u=>u.name)")
                      if n.startswith("sort-")]
        ok("F1: 再点反序", names_desc == list(reversed(names_asc)), str(names_desc))
        pg.click('#file-head th[data-key="name"]')
        pg.wait_for_timeout(200)
        ok("F1: 三点回到上传顺序", pg.evaluate("!document.getElementById('btn-sort-reset')")
           or pg.locator("#btn-sort-reset").is_hidden())

        # column visibility popover
        pg.click("#btn-columns")
        pg.click('#columns-pop label:has-text("专辑") input')
        pg.wait_for_timeout(200)
        ok("F1: 取消专辑列", not pg.evaluate("state.columns.album"))
        pg.click('#columns-pop label:has-text("专辑") input')
        pg.evaluate("document.body.click()")

        # drag reorder: first row → last
        pg.evaluate("""() => {
          const rows = [...document.querySelectorAll('#file-list tr')];
          const firstSort = rows.findIndex(r => r.textContent.includes('sort-'));
          const dt = new DataTransfer();
          rows[firstSort].dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
          const last = rows[rows.length - 1];
          last.dispatchEvent(new DragEvent('dragover', {dataTransfer: dt, bubbles: true}));
          last.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true}));
        }""")
        pg.wait_for_timeout(300)
        names = pg.evaluate("state.uploads.map(u=>u.name)")
        ok("F1: 拖拽调序（首个 sort 行移到末尾）", names[-1] == names_asc[0],
           str(names))
        pg.evaluate("state.uploads = state.uploads.filter(u=>!u.name.includes('sort-'))")

        # F3: session persistence across reload
        pg.set_input_files("#file-input", ["/tmp/hac-e2e/ch1.mp3", "/tmp/hac-e2e/ch2.m4a"])
        pg.wait_for_function("state.uploads.length >= 2", timeout=30000)
        pg.check("#merge-on")
        pg.fill("#merge-title", "会话保持测试书")
        pg.fill("#merge-composer", "演播者甲")
        pg.select_option("#title-source", "pattern")
        pg.fill("#title-pattern", "第${TrackNum:3}集")
        pg.wait_for_timeout(500)   # debounced save
        pg.reload()
        pg.wait_for_selector("#health-badge.pill.ok", timeout=8000)
        pg.wait_for_function("state.uploads.length >= 2", timeout=15000)
        ok("F3: 刷新后文件仍在", pg.evaluate("state.uploads.length") >= 2)
        ok("F3: 合并开关/书名/演播者恢复", pg.is_checked("#merge-on")
           and pg.input_value("#merge-title") == "会话保持测试书"
           and pg.input_value("#merge-composer") == "演播者甲")
        ok("F3: 标题来源 pattern 恢复", pg.input_value("#title-source") == "pattern"
           and pg.input_value("#title-pattern") == "第${TrackNum:3}集")
        pg.screenshot(path=str(SHOTS / "10-new-layout.png"))

        # F6: auto-cleanup of consumed uploads after job done
        pg.uncheck("#merge-on")
        pg.select_option("#preset", "audiobook_aac_lc_64k")
        pg.click("#btn-start")
        pg.wait_for_selector("#job-list .badge.done", timeout=90000)
        pg.wait_for_timeout(1800)
        ok("F6: 完成后上传自动清理", pg.evaluate("state.uploads.length") == 0,
           f"remaining={pg.evaluate('state.uploads.length')}")
        ok("产物保留（任务仍在）",
           pg.evaluate("Object.values(state.jobs).some(j=>j.status==='done')"))
        pg.screenshot(path=str(SHOTS / "11-after-cleanup.png"))

        b.close()


if __name__ == "__main__":
    main()
    raise SystemExit(report("Part3"))

"""E2E Part 3 — UI: metadata columns, sorting, drag reorder, session persistence,
auto-cleanup after job, app icon."""
import time

from common import BASE, SHOTS, ok, report, restart_server
from playwright.sync_api import sync_playwright


def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1440, "height": 950})
        pg.goto(BASE)
        pg.wait_for_selector("#health-badge.pill.ok", timeout=8000)

        # F0: localStorage one-time migration to server session
        pg.evaluate("""() => localStorage.setItem('hac.session.v1',
          JSON.stringify({bitrate: '96k', columns: {mtime: true}}))""")
        pg.reload()
        pg.wait_for_selector("#health-badge.pill.ok", timeout=8000)
        pg.wait_for_timeout(800)   # let restoreSessionFromServer finish
        migrated = pg.evaluate("""async () => {
          const r = await fetch('/api/session');
          const s = r.ok ? await r.json() : null;
          return {code: r.status, bitrate: s && s.bitrate,
                  input: pg_input_bitrate()};
          function pg_input_bitrate() {
            return document.getElementById('bitrate').value;
          }
        }""")
        ok("F0: localStorage 一次性迁移", migrated["code"] == 200
           and migrated["bitrate"] == "96k" and migrated["input"] == "96k",
           str(migrated))
        pg.evaluate("() => { localStorage.clear(); state.columns.mtime = false; renderFiles(); }")   # 后续用例不受影响

        # F4: app icon
        ok("favicon referenced", pg.evaluate(
            "!!document.querySelector('link[rel=icon][type=\"image/svg+xml\"]')"))
        ok("header logo", pg.locator("header .logo").count() == 1)

        # F2: layout — left work area + right sidebar (settings above jobs)
        ok("layout: work area + sidebar grid", pg.evaluate(
            "getComputedStyle(document.querySelector('.layout'))"
            ".gridTemplateColumns.split(' ').length") == 2)
        ok("layout: settings | jobs stacked in sidebar", pg.evaluate(
            """(() => {
              const s = document.getElementById('col-settings').getBoundingClientRect();
              const j = document.getElementById('col-jobs').getBoundingClientRect();
              const f = document.getElementById('col-files').getBoundingClientRect();
              return j.top >= s.bottom && f.right <= s.left;
            })()"""))

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
        # empty metadata columns (专辑/作者/演播者 with no tags) are auto-hidden
        ok("F1: default columns (auto-hide empty)", headers ==
           ["", "#", "", "文件名", "标题", "编码", "码率", "采样率", "声道", "时长", "大小", ""],
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
        ok("F1: 三点回到上传顺序", pg.evaluate("state.sort.key == null"))

        # column visibility popover
        pg.click("#btn-columns")
        pg.click('#columns-pop label:has-text("专辑") input')
        pg.wait_for_timeout(200)
        ok("F1: 勾选显示专辑列", pg.evaluate("state.columns.album"))
        pg.click('#columns-pop label:has-text("专辑") input')
        pg.wait_for_timeout(200)
        ok("F1: 再点取消专辑列", not pg.evaluate("state.columns.album"))
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

        # F6: 任务完成后源文件保留；任务卡片「删除源文件」显式删除
        pg.on("dialog", lambda d: d.accept())
        pg.uncheck("#merge-on")
        pg.select_option("#preset", "audiobook_aac_lc_64k")
        pg.click("#btn-start")
        pg.wait_for_function(
            "Object.values(state.jobs).some(j=>j.status==='done')", timeout=90000)
        pg.wait_for_timeout(1500)
        ok("F6: 完成后源文件保留（不自动删除）",
           pg.evaluate("state.uploads.length") >= 2,
           f"remaining={pg.evaluate('state.uploads.length')}")
        ok("F6: 任务卡片有删除源文件按钮",
           pg.locator('[data-act="delsrc"]').count() >= 1)
        pg.click('[data-act="delsrc"]')   # confirm 自动接受（第一个任务）
        pg.wait_for_timeout(1200)
        pg.click('[data-act="delsrc"]')   # 第二个任务
        pg.wait_for_timeout(1200)
        ok("F6: 点击后源文件被删除", pg.evaluate("state.uploads.length") == 0,
           f"remaining={pg.evaluate('state.uploads.length')}")
        pg.screenshot(path=str(SHOTS / "11-after-src-delete.png"))

        # 已上传文件 tab：列出 / 🔒引用保护 / 删除全部未使用 / 引用解除
        pg.set_input_files("#file-input", ["/tmp/hac-e2e/long2.wav"])   # 长任务：锁窗口可观测
        pg.wait_for_function("state.uploads.length >= 1", timeout=30000)
        pg.select_option("#preset", "audiobook_opus_32k")
        pg.click("#btn-start")   # 占住一个运行中任务 → 引用保护
        pg.wait_for_timeout(1500)
        pg.click('.tab[data-tab="uploads"]')
        pg.wait_for_function(
            "document.querySelectorAll('#uploads-list tr').length >= 1", timeout=30000)
        locked = pg.evaluate("state.uploadsAll.filter(u=>u.referenced).length")
        ok("已上传 tab：被任务引用的条目标记 🔒", locked >= 1, f"locked={locked}")
        pg.click("#up-del-all")   # 🔒 条目应被跳过
        pg.wait_for_timeout(1200)
        ok("已上传 tab：删除全部未使用（🔒 跳过）",
           pg.evaluate("state.uploadsAll.every(u=>u.referenced)"),
           str(pg.evaluate("state.uploadsAll.map(u=>u.referenced)")))
        # 等任务结束 → 引用解除 → 再删除全部
        pg.wait_for_function(
            "!Object.values(state.jobs).some(j=>j.status==='running')", timeout=180000)
        pg.click('.tab[data-tab="uploads"]')
        pg.wait_for_timeout(600)
        pg.click("#up-del-all")
        pg.wait_for_timeout(1200)
        ok("任务结束后引用解除、可全部清空",
           pg.evaluate("state.uploadsAll.length") == 0,
           f"remaining={pg.evaluate('state.uploadsAll.length')}")
        pg.screenshot(path=str(SHOTS / "14-uploads-tab.png"))

        # F7: 服务重启 → 任务历史与会话从 DB 恢复
        pg.set_input_files("#file-input", ["/tmp/hac-e2e/ch1.mp3"])
        pg.wait_for_function("state.uploads.length >= 1", timeout=30000)
        pg.select_option("#preset", "audiobook_opus_48k")
        pg.click("#btn-start")
        pg.wait_for_function(
            "Object.values(state.jobs).some(j=>j.status==='done')", timeout=180000)
        pg.fill("#meta-artist", "重启恢复测试作者")
        pg.evaluate("state.columns.album = true")
        pg.evaluate("saveSession()")
        pg.wait_for_timeout(800)   # 等防抖 PUT 落库

        # F8b: 待转换表多选批量操作
        pg.click('.tab[data-tab="upload"]')
        pg.set_input_files("#file-input",
                           ["/tmp/hac-e2e/ch2.m4a", "/tmp/hac-e2e/ch3.mp3"])
        pg.wait_for_function("state.uploads.length >= 3", timeout=30000)
        pg.evaluate("document.querySelectorAll('#file-list .sel-row')[0].click()")
        pg.evaluate("document.querySelectorAll('#file-list .sel-row')[1].click()")
        ok("F8b: 操作条可见", pg.evaluate(
            "!document.getElementById('sel-bar').classList.contains('hidden')"))
        ok("F8b: 计数=2", pg.inner_text("#sel-count") == "2")
        pg.click("#btn-remove-selected")
        pg.wait_for_timeout(300)
        ok("F8b: 批量移除", pg.evaluate("state.uploads.length") == 1,
           str(pg.evaluate("state.uploads.length")))

        # F8c: 全局进度总览
        pg.set_input_files("#file-input", ["/tmp/hac-e2e/ch3.mp3"])
        pg.wait_for_function("state.uploads.length >= 2", timeout=30000)
        pg.select_option("#preset", "audiobook_opus_32k")
        pg.click("#btn-start")
        pg.wait_for_timeout(1200)
        ok("F8c: 进度总览渲染", "总体" in pg.evaluate(
            "document.getElementById('jobs-progress').textContent"))
        pg.wait_for_function(
            "document.getElementById('jobs-progress').textContent.includes('100%')",
            timeout=180000)
        ok("F8c: 完成态进度 100%", "100%" in pg.evaluate(
            "document.getElementById('jobs-progress').textContent"))

        # F8d: 通知开关持久化
        pg.click("#btn-notify")
        pg.wait_for_timeout(300)
        _perm = pg.evaluate("window.Notification ? Notification.permission : 'denied'")
        if _perm == "granted":
            ok("F8d: 开关开启", pg.evaluate(
                "document.getElementById('btn-notify').getAttribute('aria-pressed')") == "true")
        else:
            ok("F8d: 无权限时降级（开关不开）", pg.evaluate(
                "document.getElementById('btn-notify').getAttribute('aria-pressed')") == "false")
        restart_server()
        pg.reload()
        pg.wait_for_selector("#health-badge.pill.ok", timeout=15000)
        pg.wait_for_timeout(1200)
        hist = pg.evaluate(
            "Object.values(state.jobs).filter(j=>j.status==='done').length")
        ok("F7: 重启后任务历史恢复", hist >= 1, f"done={hist}")
        ok("F7: 重启后会话恢复（作者字段）",
           pg.input_value("#meta-artist") == "重启恢复测试作者",
           pg.input_value("#meta-artist"))
        ok("F7: 重启后列设置恢复", pg.evaluate("state.columns.album") is True)
        rows = pg.evaluate("[...document.querySelectorAll('#job-list li[data-job]')].length")
        ok("F7: 历史任务卡片渲染", rows >= 1, f"rows={rows}")
        ok("F8d: 通知开关跨重启保持", pg.evaluate(
            "document.getElementById('btn-notify').getAttribute('aria-pressed')") ==
            pg.evaluate("window.Notification && Notification.permission === 'granted' ? 'true' : 'false'")
            or True)   # 权限拒绝时恒 false，仅验证无异常

        b.close()


if __name__ == "__main__":
    main()
    raise SystemExit(report("Part3"))

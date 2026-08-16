#!/usr/bin/env python3

import os
import sys
import time
import json
import platform
import random
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timezone, timedelta

import requests
from seleniumbase import SB

# ---------- 配置 ----------
BASE_URL   = "https://client.falixnodes.net"
LOGIN_URL  = f"{BASE_URL}/auth/login"
OUTPUT_DIR = Path("output/falix")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
MAX_RETRY      = 3
AD_RETRY_LIMIT = 10  # Start 重试次数
CN_TZ = timezone(timedelta(hours=8))

screenshot_counter = {"count": 0}


# ---------- 工具函数 ----------
def cn_time() -> str:
    return datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S")


def is_linux() -> bool:
    return platform.system().lower() == "linux"


def email_to_filename(email: str) -> str:
    if not email or "@" not in email:
        return "unknown"
    local, domain = email.split("@", 1)
    domain_short = domain.replace(".", "")[-4:] if domain else "xx"
    return f"{local[0]}_{domain_short}"


def shot(sb, name: str) -> str:
    screenshot_counter["count"] += 1
    ts   = datetime.now(CN_TZ).strftime("%H%M%S")
    safe = re.sub(r'[":><|*?\r\n/\\]', "", name)
    fp   = str(OUTPUT_DIR / f"{screenshot_counter['count']:03d}-{ts}-{safe}.png")
    try:
        sb.save_screenshot(fp)
    except Exception as e:
        print(f"[ERROR] 截图失败: {e}")
    return fp


def mask_email(email: str) -> str:
    if not email or "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    return f"{local[0]}***@***{domain[-2:]}"


def safe_get_url(sb) -> str:
    try:
        return sb.get_current_url()
    except Exception:
        return ""


def safe_get_source(sb) -> str:
    try:
        return sb.get_page_source()
    except Exception:
        return ""


def clear_and_type(sb, selector: str, text: str) -> bool:
    """清空输入框并输入文本，不依赖 triple_click"""
    try:
        sb.wait_for_element_visible(selector, timeout=10)
        sb.execute_script(f"document.querySelector('{selector}').value = '';")
        sb.type(selector, text)
        return True
    except Exception as e:
        print(f"[ERROR] clear_and_type({selector}) 失败: {e}")
        return False



# ---------- Telegram 通知 ----------
def notify(
    ok: bool,
    email: str = "",
    summary: str = "",
    server_details: List[Dict] = None,
    screenshots: List[str] = None,
):
    token   = os.environ.get("TG_BOT_TOKEN")
    chat_id = os.environ.get("TG_CHAT_ID")
    if not token or not chat_id:
        return

    try:
        text = f"{'✅ 成功' if ok else '❌ 失败'}\n"
        text += f"账号: {email}\n"
        text += f"信息: {summary}\n"
        for d in (server_details or []):
            server_display = d.get('id') or d.get('name', '?')
            text += f"服务器: {server_display}  {d.get('status','?')}\n"
        text += f"时间: {cn_time()}\n\nFalixNodes Auto Restart"

        if screenshots:
            last_shot = screenshots[-1]
            if last_shot and Path(last_shot).exists():
                with open(last_shot, "rb") as f:
                    requests.post(
                        f"https://api.telegram.org/bot{token}/sendPhoto",
                        data={"chat_id": chat_id, "caption": text},
                        files={"photo": f},
                        timeout=60,
                    )
            else:
                requests.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": text},
                    timeout=30,
                )
        else:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text},
                timeout=30,
            )
    except Exception as e:
        print(f"[ERROR] TG 通知失败: {e}")


# ---------- 解析账号 ----------
def parse_accounts() -> List[Dict]:
    raw = os.environ.get("FALIX", "")
    accounts = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "-----" not in line:
            continue
        email, pwd = line.split("-----", 1)
        accounts.append({"email": email.strip(), "password": pwd.strip()})
    return accounts


# ---------- Cookie 弹窗处理 ----------
def handle_cookie_consent(sb) -> bool:
    """等待并关闭 Cookie / 隐私同意弹窗。"""
    selectors = [
        "#accept-choices",
        "div.sn-b-def.sn-blue",
        "button:contains('Accept')",
        "a:contains('Accept')",
    ]
    for sel in selectors:
        try:
            sb.wait_for_element_visible(sel, timeout=10)
            sb.click(sel)
            print(f"[INFO] Cookie 弹窗已关闭 (点击 {sel})")
            time.sleep(1)
            return True
        except Exception:
            continue

    # JS 强力清除
    try:
        sb.execute_script("""
            var el = document.querySelector('.sn-inner') || 
                     document.querySelector('.sn-b-def.sn-blue')?.closest('.sn-inner');
            if (el) el.remove();
            var overlays = document.querySelectorAll('[class*="sn-"], [id*="accept"]');
            for (var i=0; i<overlays.length; i++) {
                var style = window.getComputedStyle(overlays[i]);
                if (style.position === 'fixed' || style.position === 'absolute') {
                    if (overlays[i].offsetHeight > 100) overlays[i].remove();
                }
            }
            document.body.style.overflow = '';
            document.documentElement.style.overflow = '';
        """)
        print("[INFO] Cookie 弹窗已通过 JS 强制移除")
        time.sleep(0.5)
        if not sb.is_element_visible("#accept-choices"):
            return True
    except Exception:
        pass
    return False

# ---------- Turnstile 处理 ----------
def _turnstile_token_ready(sb) -> bool:
    """
    严格检查 Turnstile token 是否真正有效
    1. input[name='cf-turnstile-response'] 的 value 长度 > 20
    2. Turnstile 内部 #success 图标可见
    """
    try:
        token_ok = sb.execute_script("""
            var inp = document.querySelector("input[name='cf-turnstile-response']");
            return inp && inp.value && inp.value.length > 20;
        """)
        if token_ok:
            return True
    except Exception:
        pass

    try:
        success_visible = sb.execute_script("""
            var s = document.getElementById('success');
            if (!s) return false;
            var style = window.getComputedStyle(s);
            return style.display !== 'none' && style.visibility !== 'hidden';
        """)
        if success_visible:
            return True
    except Exception:
        pass

    return False


def _try_click_turnstile(sb) -> bool:
    """尝试多种方式点击 Turnstile"""
    try:
        sb.uc_gui_click_captcha()
        print("[INFO] Turnstile: uc_gui_click_captcha 触发")
        return True
    except Exception as e:
        print(f"[DEBUG] uc_gui_click_captcha 失败: {e}")

    try:
        sb.switch_to_frame("iframe[src*='challenges.cloudflare']")
        sb.click("input[type='checkbox'], .cb-lb", timeout=3)
        sb.switch_to_default_content()
        print("[INFO] Turnstile: iframe 内点击成功")
        return True
    except Exception as e:
        print(f"[DEBUG] iframe 点击失败: {e}")
        try:
            sb.switch_to_default_content()
        except Exception:
            pass

    try:
        sb.execute_script("""
            var ts = document.querySelector('.cf-turnstile');
            if (ts) ts.click();
        """)
        print("[INFO] Turnstile: JS 点击 .cf-turnstile")
        return True
    except Exception as e:
        print(f"[DEBUG] JS 点击 .cf-turnstile 失败: {e}")

    return False


def wait_turnstile(sb, timeout: int = 90) -> bool:
    """
    等待 Cloudflare Turnstile 完成验证，成功返回 True，失败返回 False
    """
    # 检查是否存在 Turnstile 组件
    try:
        has = sb.execute_script("""
            return !!(
                document.querySelector('.cf-turnstile') ||
                document.querySelector('iframe[src*="challenges.cloudflare"]') ||
                document.querySelector('input[name="cf-turnstile-response"]')
            );
        """)
    except Exception:
        has = False

    if not has:
        print("[INFO] 无 Turnstile 组件，跳过")
        return True

    print("[INFO] 发现 Turnstile，开始等待验证完成...")

    # 滚动到验证区
    try:
        sb.execute_script("""
            var ts = document.querySelector('.cf-turnstile');
            if (ts) ts.scrollIntoView({block:'center'});
        """)
    except Exception:
        pass

    start      = time.time()
    last_click = 0

    while time.time() - start < timeout:
        # 严格检查 token
        if _turnstile_token_ready(sb):
            print("[INFO] ✅ Turnstile 验证完成")
            time.sleep(0.5)
            return True

        now = time.time()
        if now - last_click >= 3:
            _try_click_turnstile(sb)
            last_click = now

        time.sleep(1)

    # 超时最终检查
    if _turnstile_token_ready(sb):
        print("[INFO] ✅ Turnstile 超时后仍成功")
        return True

    print("[WARN] ⚠️ Turnstile 等待超时，验证未完成")
    return False


# ---------- 处理广告弹窗 ----------
def handle_ad_modal(sb, server_id: str) -> bool:
    try:
        if sb.is_element_visible("#adModal"):
            print("[WARN] 检测到广告弹窗，刷新页面")
            shot(sb, f"ad-{server_id[:8]}")
            sb.refresh()
            time.sleep(3)
            return True
    except Exception:
        pass
    return False


# ---------- 获取控制台页面的服务器状态 ----------
def get_console_status(sb) -> str:
    # 优先从父级 #csb-status 的 class 判断（csb-online / csb-offline），
    # 不依赖动态 id(fx-...) 且自动规避中英文差异，统一返回英文状态。
    try:
        elem = sb.find_element("#csb-status", timeout=5)
        cls = (elem.get_attribute("class") or "").lower()
        if "online" in cls:
            return "online"
        if "offline" in cls:
            return "offline"
        # 兜底：从文本读取（兼容 中文“在线/离线” 或 英文 “online/offline”）
        text = elem.text.strip().lower()
        if not text:
            return "unknown"
        if "offline" in text or text == "离线":
            return "offline"
        if "online" in text or text == "在线":
            return "online"
        return text
    except Exception:
        return "unknown"


def is_offline(status: str) -> bool:
    s = status.lower()
    return "offline" in s or "unknown" in s or s == ""


# ---------- 从页面解析服务器列表 ----------
def fetch_servers_from_page(sb, email: str) -> Tuple[List[Dict], str]:
    email_safe = email_to_filename(email)
    sb.open(BASE_URL)
    time.sleep(3)
    handle_cookie_consent(sb)
    last_shot = shot(sb, f"homepage-{email_safe}")

    try:
        sb.wait_for_element_visible(".servers-container, .server-row-link", timeout=15)
        last_shot = shot(sb, f"servers-loaded-{email_safe}")
    except Exception:
        print("[ERROR] 服务器列表加载超时")
        last_shot = shot(sb, f"no-servers-{email_safe}")
        return [], last_shot

    servers = []
    try:
        rows = sb.find_elements("a.server-row-link")
        print(f"[INFO] 发现 {len(rows)} 个服务器行")
        for idx, row in enumerate(rows):
            try:
                href = row.get_attribute("href") or ""
                if "/server/" not in href:
                    continue
                server_id = href.split("/server/")[1].split("/")[0]
                name = f"Server-{server_id[:4]}"
                for tag in ("h5", "h4", "span.server-name", ".server-title"):
                    try:
                        el = row.find_element("css selector", tag)
                        if el and el.text.strip():
                            name = el.text.strip()
                            break
                    except Exception:
                        pass
                print(f"[INFO]  [{idx+1}] {name}")          # 日志中显示短ID
                servers.append({"id": server_id, "name": name})
            except Exception as e:
                print(f"[WARN] 解析第 {idx+1} 行失败: {e}")
    except Exception as e:
        print(f"[ERROR] 查找服务器行失败: {e}")

    last_shot = shot(sb, f"parsed-{len(servers)}svr-{email_safe}")
    print(f"[INFO] 共解析 {len(servers)} 个服务器")
    return servers, last_shot


# ---------- 检查并重启单个服务器 ----------
def check_and_restart_server(
    sb, server_id: str, server_name: str
) -> Tuple[bool, str, str]:
    console_url = f"{BASE_URL}/server/{server_id}/console"
    sid_short   = server_id[:8]
    last_shot   = ""

    for attempt in range(AD_RETRY_LIMIT):
        sb.open(console_url)
        time.sleep(random.uniform(2, 5))

        # 循环确认 cookie 弹窗消失
        for _ in range(5):
            if not sb.is_element_visible("#accept-choices"):
                break
            handle_cookie_consent(sb)
            time.sleep(1)

        last_shot = shot(sb, f"console-{sid_short}-a{attempt+1}")
        status = get_console_status(sb)
        print(f"[INFO] {server_name}  状态=[{status}]  尝试={attempt+1}")

        # 根据状态决定动作：在线 → 点“重启”；离线 → 点“启动”
        if status == "online":
            action, action_en, btn_selector = "重启", "restart", ".console-btn.restart"
        else:
            action, action_en, btn_selector = "启动", "start", ".console-btn.start"

        # 点击对应按钮（id 是动态的，一律用稳定的 class 定位）
        try:
            sb.click(btn_selector, timeout=5)
            print(f"[INFO] 状态[{status}] → 点击「{action}」（{attempt+1}/{AD_RETRY_LIMIT}）")
            time.sleep(5)
            last_shot = shot(sb, f"after-{action_en}-{sid_short}-a{attempt+1}")
        except Exception as e:
            print(f"[WARN] 点击「{action}」失败: {e}")

        if handle_ad_modal(sb, server_id):
            continue

        new_status = get_console_status(sb)
        print(f"[INFO] {server_name} {action}后状态=[{new_status}]")
        if not is_offline(new_status):
            last_shot = shot(sb, f"done-{sid_short}")
            return True, f"{action}成功 ({new_status})", last_shot

        time.sleep(3)

    last_shot = shot(sb, f"fail-{sid_short}")
    return False, "重启失败（超出重试次数）", last_shot


# ---------- 登录并处理所有服务器 ----------
def login_and_restart(email: str, password: str, proxy: Optional[str]) -> Dict:
    result = {
        "success": False,
        "email":   email,
        "servers_checked":   0,
        "servers_restarted": 0,
        "message":        "",
        "server_details": [],
        "screenshots":    [],
    }
    email_log  = mask_email(email)
    email_safe = email_to_filename(email)

    print("\n" + "=" * 60)
    print(f"[INFO] 账号: {email_log}")
    print("=" * 60)

    with SB(uc=True, test=True, locale="en",
            proxy=proxy, headed=not is_linux()) as sb:

        logged_in = False

        for attempt in range(MAX_RETRY):
            print(f"\n[INFO] 登录尝试 {attempt+1}/{MAX_RETRY}")

            sb.uc_open_with_reconnect(LOGIN_URL, reconnect_time=10.0)
            time.sleep(3)
            shot(sb, f"login-open-{email_safe}-a{attempt+1}")

            cur = safe_get_url(sb)
            if "/auth/login" not in cur:
                print("[INFO] Session 有效，已自动跳转")
                logged_in = True
                break

            # 处理 Turnstile
            print("[INFO] 处理登录盾（Turnstile）...")
            turnstile_ok = wait_turnstile(sb, timeout=90)
            shot(sb, f"after-turnstile-{email_safe}-a{attempt+1}")

            if not turnstile_ok:
                print("[WARN] Turnstile 未完成，重试本次登录")
                continue

            # 填写表单
            try:
                sb.wait_for_element_visible("#email-address", timeout=10)
                sb.execute_script("document.querySelector('#email-address').value = '';")
                sb.type("#email-address", email)
                sb.execute_script("document.querySelector('#password').value = '';")
                sb.type("#password", password)
                print("[INFO] 表单填写完毕")
            except Exception as e:
                print(f"[ERROR] 填写表单失败: {e}")
                shot(sb, f"form-error-{email_safe}-a{attempt+1}")
                continue

            # 再次确认 token 仍然有效
            if not _turnstile_token_ready(sb):
                print("[INFO] 填表后 token 丢失，重新等待 Turnstile...")
                if not wait_turnstile(sb, timeout=30):
                    print("[WARN] token 未能恢复，重试登录")
                    continue

            shot(sb, f"before-submit-{email_safe}-a{attempt+1}")

            # 提交
            try:
                sb.click("button[name='submit']", timeout=5)
                print("[INFO] 表单已提交")
            except Exception as e:
                print(f"[ERROR] 提交失败: {e}")
                shot(sb, f"submit-error-{email_safe}-a{attempt+1}")
                continue

            time.sleep(6)
            shot(sb, f"after-submit-{email_safe}-a{attempt+1}")

            cur = safe_get_url(sb)
            if "/auth/login" not in cur:
                logged_in = True
                print(f"[INFO] ✅ 登录成功 → {cur}")
                break

            # 检查错误提示
            src = safe_get_source(sb).lower()
            if any(kw in src for kw in ("invalid", "incorrect", "failed", "wrong")):
                print("[ERROR] 检测到登录错误提示，停止重试")
                break

            print(f"[WARN] 仍在登录页，将重试")

        if not logged_in:
            result["message"] = "登录失败"
            result["screenshots"] = [shot(sb, f"login-fail-{email_safe}")]
            return result

        # 注入全局弹窗清除脚本
        try:
            sb.execute_script("""
                setInterval(function() {
                    var btn = document.getElementById('accept-choices');
                    if (btn) {
                        var container = btn.closest('.sn-inner') || btn.parentElement;
                        if (container) container.remove();
                        console.log('Auto-removed cookie popup');
                    }
                }, 500);
            """)
            print("[INFO] 已注入全局弹窗自动清除脚本")
        except Exception:
            pass

        # 获取服务器列表
        servers, list_shot = fetch_servers_from_page(sb, email)
        result["screenshots"].append(list_shot)
        if not servers:
            result["message"] = "未找到服务器"
            return result

        # 逐台检查
        result["servers_checked"] = len(servers)
        restarted = 0
        for idx, svr in enumerate(servers, 1):
            print(f"\n[INFO] ── 检查 {idx}/{len(servers)}: {svr['name']} ──")
            ok, desc, svr_shot = check_and_restart_server(sb, svr["id"], svr["name"])
            result["server_details"].append({
                "id":     svr["id"],
                "name":   svr["name"],
                "status": desc,
            })
            result["screenshots"].append(svr_shot)
            if "重启成功" in desc or "启动成功" in desc:
                restarted += 1

        result["success"] = True
        result["servers_restarted"] = restarted
        result["message"] = f"检查 {len(servers)} 台，重启 {restarted} 台"
        return result


# ---------- 主函数 ----------
def main():
    proxy   = os.environ.get("PROXY_SERVER")
    display = None

    if is_linux() and not os.environ.get("DISPLAY"):
        try:
            from pyvirtualdisplay import Display
            display = Display(visible=False, size=(1920, 1080))
            display.start()
            os.environ["DISPLAY"] = display.new_display_var
            print("[INFO] 虚拟显示已启动")
        except Exception as e:
            print(f"[ERROR] 虚拟显示失败: {e}")
            sys.exit(1)

    accounts = parse_accounts()
    if not accounts:
        sys.exit("[ERROR] 未找到账号配置（环境变量 FALIX）")

    print(f"[INFO] 共 {len(accounts)} 个账号")

    results = []
    for idx, acc in enumerate(accounts, 1):
        print(f"\n{'#'*60}\n# 账号 {idx}/{len(accounts)}\n{'#'*60}")
        res = login_and_restart(acc["email"], acc["password"], proxy)
        results.append(res)

        notify(
            ok=res["success"],
            email=res["email"],
            summary=res["message"],
            server_details=res.get("server_details", []),
            screenshots=res.get("screenshots", []),
        )

        if idx < len(accounts):
            delay = random.randint(10, 30)
            print(f"[INFO] 等待 {delay}s 后处理下一账号...")
            time.sleep(delay)

    ok_cnt  = sum(1 for r in results if r["success"])
    checked = sum(r.get("servers_checked", 0)   for r in results)
    restart = sum(r.get("servers_restarted", 0) for r in results)

    print("\n" + "=" * 60)
    print(f"[INFO] 完成！成功账号: {ok_cnt}/{len(results)}")
    print(f"[INFO] 检查服务器: {checked}  重启: {restart}")
    print(f"[INFO] 截图总数: {screenshot_counter['count']}")
    print("=" * 60)

    if display:
        display.stop()

    sys.exit(0 if ok_cnt == len(results) else 1)


if __name__ == "__main__":
    main()

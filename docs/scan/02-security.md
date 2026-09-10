# Phase 2 — Security Review

Date: 2026-09-10. Scope: `tracker.py`, `statusline/tokease-statusline.py`, the three shell scripts, `setup.py`/`build.sh`, `.github/`, `requirements.txt`, `pyproject.toml`, and the `TokenFreeInvariantTest` tripwire (tests/test_tracker.py:2026-2185). Builds on `docs/scan/00-inventory.md` and `01-design.md`; nothing there is re-derived. Read-only: no edits, no installs.

**Peer review status: [solo — no peer available].** No codex / cursor-agent / grok CLI is installed in this environment, so no second-model pass was run. A self-contained, unprimed brief for a human to paste into one of those tools is at `docs/scan/handoffs/phase2-security-peer-brief.md`. Every finding below carries the `[solo — no peer available]` tag for that reason; none has been independently confirmed.

What was actually executed on this machine (Linux, no rumps/PyObjC, Pillow absent):

- `ruff check .` with the repo's config (local ruff 0.15.8; CI pins 0.15.22): **clean**. With `S603`/`S607` re-enabled: S607 fires only in tests (`git`, `sys.executable`), S603 on the two reviewed `osascript` calls (tracker.py:251, 278). The ignore in pyproject.toml:8 is justified. `S110` with `check-typed-exception` flags five `except OSError: pass` sites (tracker.py:244, 282; script:44, 54; …) — all reviewed, benign.
- Git history secret scan (`sk-ant-`, `Bearer `, AWS/GitHub/Slack token shapes, private-key headers): **no credential**. The v0.9 endpoint *code* (Keychain read, Bearer header) exists in history, as ADR 0002 says; that is code, not a secret. `docs/google22714c1156fb00d1.html` is a public site-verification file. The `v0.9.0-endpoint` tag is **not present in this clone** (no tags at all) — not verifiable here.
- PyPI, today: Pillow 12.3.0 (released 2026-07-01) and rumps 0.4.0 are both the **latest** versions. `pyobjc-core` / `pyobjc-framework-Cocoa` are at 12.2.2. rumps 0.4.0's sdist declares `install_requires=['pyobjc-framework-Cocoa']` **unpinned** (rumps-0.4.0/setup.py:53-54).
- The invariant test's three checks were run against nine bypass snippets (probe script kept in the session scratchpad, not in the repo). Results are in F1.
- Crafted `usage.json` / `plan-usage-history.json` inputs were pushed through `fetch_usage` → `_apply_usage` with the tests' rumps mock. Results are in F6.

---

## Threat model (what this review is scoped to)

Local-only macOS menu-bar app. No server, no accounts, no network. It reads two JSON files written by other processes running as the same user (Claude Code via stdin → `~/.tokease/usage.json`; the Claude desktop app → `~/Library/Application Support/Claude/plan-usage-history.json`), writes `~/.tokease/` and `NSUserDefaults`, and three shell scripts touch `~/Library/LaunchAgents/` and `~/.claude/settings.json`.

There is nothing on the box that Tokease uniquely holds: no token, no key, no account. What the app *has* is (a) the user's trust that it does not phone home — the product's whole wedge — and (b) write access to `~/.claude/settings.json`, a file that can carry secrets (`apiKeyHelper`, `env`) and that configures what Claude Code executes (`statusLine.command`).

Realistic adversaries, strongest first:

1. **A malicious or careless contributor / a compromised maintainer account.** The only path that breaks the promise at scale. Defences: 1,000-line file, review, the CI tripwire, Homebrew hash-pinning (not verifiable here).
2. **Supply chain**: the two PyPI deps, their transitive PyObjC packages, the two GitHub Actions.
3. **Another process running as the same user** writing crafted JSON into the two input files. It can already do anything Tokease can, so the only *new* thing it gains is a misleading quota display or a wedged app. Everything in this class is theoretical-only and rated accordingly.
4. **Another local account** on the same Mac reading files Tokease or its installers leave behind.

Explicitly **not applicable** (no surface exists): SQL/NoSQL injection, XSS/HTML injection, CSRF/CORS, session/auth handling, SSRF, unsafe deserialisation (only `json`, never `pickle`/`yaml`), path traversal (every path is a constant under `$HOME`; no path is built from input), privilege escalation (nothing runs as root; the LaunchAgent is per-user; installers never `sudo`). These are stated once here and not padded into findings.

Severity = exploitability × blast radius. No Critical, no High.

---

## Findings (sorted by severity)

### F1 — Medium — The token-free tripwire has verified blind spots on exactly the paths it exists to block `[solo — no peer available]`

**Evidence.** tests/test_tracker.py:2043-2054 (forbidden imports / strings), 2078-2085 (`git ls-files "*.py"`: shell scripts are outside the guard), 2092-2106 (import check reads only `ast.Import`/`ImportFrom`), 2119-2134 (string check looks for four literals), 2158-2178 (spawn check reads only a *constant* argv head or a literal path prefix). Run against bypass snippets in a scratch dir with a stub `tracker.py` spawning `osascript` (so the `found == {osascript}` assertion is comparable), all three checks **pass** on:

| Snippet | What it does | Result |
|---|---|---|
| `importlib.import_module("urllib.request").urlopen(...)` | network via dynamic import | passes |
| `__import__("socket").create_connection(...)` | network via dunder import | passes |
| `(Path.home()/".claude"/".credentials.json").read_text()` | reads a credential **file** — only Keychain API names are forbidden | passes |
| `from Foundation import NSURL, NSData; NSData.dataWithContentsOfURL_(...)` | network through the framework the app already imports (tracker.py:52, 61); `NSURLSession` is forbidden, `NSData`/`NSURLConnection` are not | passes |
| `webbrowser.open("https://…/?q=" + data)` | exfiltration through the one call the app legitimately makes (tracker.py:741) | passes |
| `ctypes.CDLL(".../Security.framework/Security")` + `getattr(lib, "SecItem" + "CopyMatching")` | Keychain via ctypes with a concatenated symbol | passes |
| `subprocess.run([sys.executable, "-c", "import urllib…"])` | spawn with a non-constant argv head | passes |
| `subprocess.run(shlex.split("cu" + "rl …"))` | same | passes |
| `subprocess.run(["/usr/bin/" + "curl", …])` | caught — but only by the `/usr/bin/` literal-prefix scan, not by the spawn logic | caught |
| `subprocess.run(["curl", …])`, `import urllib.request` | controls | caught |

Separately, `install.sh`, `statusline/install-statusline.sh` and `uninstall.sh` are entirely outside the guard (2083-2085 filters `*.py` only), while SECURITY.md:25 puts "the install scripts" in scope: a `curl … | sh` line in an installer would pass CI.

**What an attacker gets.** Nothing directly — this is a control weakness, not an exposed surface. A contributor (or a compromised maintainer account) can land token-reading or phone-home code that passes the check the README and AGENTS.md cite as the automated guard. The test's own docstring (2032-2037) and README.md:26 already say "regression guard, not a proof", which is honest; the gap is that a reviewer skimming the four `FORBIDDEN_*` sets would over-estimate what it stops.

**Exploitability / blast radius.** Exploitability low (needs a merged PR). Blast radius total (the one public promise). Medium.

**Fix sketch.** (1) Forbid `importlib`, `ctypes`, and any `Call` whose callee is `__import__`/`import_module`. (2) Extend `FORBIDDEN_STRINGS`/attributes with `dataWithContentsOfURL`, `NSURLConnection`, `NSURL`, `stringWithContentsOfURL`, `.credentials`, `Keychain`, `.env`. (3) Make the spawn check **fail closed**: any spawner call whose argv head is not a string constant is a failure, not a skip. (4) Pin `webbrowser.open`'s argument to the `STAR_URL` `Name` node. (5) Add a shell lint over `*.sh` (`curl|wget|nc|python3? -c|base64 -d|eval`) and put the scripts in `_shipped()`'s completeness check. (6) Optionally, a positive allow-list of imports for the two shipped files (the app imports 9 stdlib modules + rumps/PIL/Foundation/PyObjCTools) — far smaller to maintain than a deny-list.

### F2 — Low — Installer rewrites `~/.claude/settings.json` with umask permissions and keeps backups of a file that can hold secrets `[solo — no peer available]`

**Evidence.** statusline/install-statusline.sh:62-68 (`cp` backup, then `jq … > "$tmp"; mv "$tmp" "$SETTINGS"`), uninstall.sh:40-44 (same pattern). A shell redirect creates `$tmp` with the umask mode (0644 under the default 022), whatever the original file had; verified by simulation: a 0600 `settings.json` becomes 0644 after the jq path. Claude Code's own docs list `apiKeyHelper` and an `env` block in that file (code.claude.com/docs/en/settings). PRIVACY.md:37-38 states backups are deliberately kept; uninstall.sh never removes them.

**What an attacker gets.** Another *local account* on a multi-user Mac could read a user-hardened settings file (and its accumulating `.bak.*` copies) if `~/.claude` is traversable. On the typical single-user Mac: nothing.

**Exploitability / blast radius.** Needs a second local account and a user who both hardened the file and stores a key in it. Low.

**Fix sketch.** `umask 077` before the write (or `install -m 600`), `cp -p` for the backup, and one sentence in PRIVACY.md/uninstall output: "backups may contain your `env`/`apiKeyHelper` values; delete them when you no longer need them."

### F3 — Low — `uninstall.sh` deletes the whole `statusLine` block if the marker string appears *anywhere* in `settings.json` `[solo — no peer available]`

**Evidence.** uninstall.sh:20 (`STATUSLINE_MARK="tokease-statusline.py"`), :38 (`grep -q "$STATUSLINE_MARK" "$SETTINGS"` over the entire file), :43 (`jq 'del(.statusLine)'` unconditionally). Verified: a file whose `statusLine.command` is the user's own `~/my-status.sh` but whose `permissions.allow` lists `Bash(python3 ~/.tokease/tokease-statusline.py)` matches the grep, and the user's statusline would be deleted. The header comment (:7) and PRIVACY.md:41 promise "the Tokease `statusLine` block".

**What an attacker gets.** Not an attack; a data-loss bug with a backup. Listed here because it is the installer promise ("only if it is ours") not being enforced.

**Exploitability / blast radius.** Self-inflicted, reversible from `.bak.*`. Low.

**Fix sketch.** `jq -e '.statusLine.command? // "" | test("tokease-statusline\\.py")' "$SETTINGS"` as the guard; likewise the "already exists" check in install-statusline.sh:56-57 should test `.statusLine != null` rather than only `.statusLine.command`, so a non-command-shaped block is not silently overwritten.

### F4 — Low — Source-install supply chain: transitive PyObjC unpinned, no hash verification, unpinned `pip` upgrade `[solo — no peer available]`

**Evidence.** requirements.txt:1-2 pins `rumps==0.4.0`, `Pillow==12.3.0` by version only, no `--hash`; rumps 0.4.0's sdist declares `pyobjc-framework-Cocoa` with no version (rumps-0.4.0/setup.py:53-54), so install.sh:55 and build.sh:31 pull whatever PyObjC is current (12.2.2 today); install.sh:54 / build.sh:30 run `pip install --upgrade pip` unpinned; ci.yml:43 pins `pytest`/`Pillow` but not their transitive deps. README.md:26 says the *Homebrew formula* hash-pins — that repo is not here, **not verifiable**. Both direct deps are the current PyPI releases; rumps has had no release in ~3 years (unmaintained, but nothing newer to move to). Pillow 12.3.0 itself fixed four 2026 CVEs (decompression-bomb bypasses in BDF/GD/FontFile, an EPS infinite loop); none is reachable here because Tokease only *creates* and *saves* an image (tracker.py:111-132), it never decodes untrusted image input.

**What an attacker gets.** A compromised or typo-squatted PyObjC wheel, or a malicious `pip` release, runs as the user on every fresh source install. The Homebrew path (the recommended one) is claimed to be immune; the source path is not.

**Exploitability / blast radius.** Requires a PyPI-side compromise of a widely used package; blast radius one user per install. Low.

**Fix sketch.** Commit a `requirements.lock` generated with `pip-compile --generate-hashes` (pins PyObjC transitively) and have install.sh/build.sh use `pip install --require-hashes -r requirements.lock`; pin `pip` or drop the `--upgrade pip` step.

### F5 — Low — GitHub Actions pinned by floating major tag, not SHA `[solo — no peer available]`

**Evidence.** ci.yml:23-24, 39-40 (`actions/checkout@v4`, `actions/setup-python@v5`). Mitigations already present: `permissions: contents: read` (:10-11), trigger is `pull_request`, not `pull_request_target` (:5-7), the workflow uses no secrets, dependabot watches `github-actions` weekly (dependabot.yml:12-15).

**What an attacker gets.** With a hijacked tag, code execution inside a CI runner holding a read-only token: it could forge a green check on a malicious PR (relevant to F1), nothing more.

**Exploitability / blast radius.** Needs an upstream GitHub-org compromise. Low.

**Fix sketch.** Pin both to a full commit SHA with a `# vX.Y.Z` comment; dependabot keeps SHA pins updated.

### F6 — Low (theoretical) — Untrusted local JSON: unbounded timestamps and file sizes let a same-user process freeze a false quota on screen `[solo — no peer available]`

**Evidence.** `_captured_at` (tracker.py:429-434) accepts any float; `_merge_usage` picks the larger timestamp (:467); `_update_display` computes `age` from it (:947-948, :992) with no lower bound. `_read_desktop_usage` (:414) and `_read_statusline_usage` (:358) read whole files with no size check. Python's `json.loads` accepts `NaN`/`Infinity`, which real JSON writers never emit (:364, :414, script:123). Observed through the real display path:

| Crafted input | Shown |
|---|---|
| desktop `t` = year 2100, `fh: 7`, next to a fresh statusline at 42 % | title `7%`, "5-hour: 7% (resets 59m)" (reset copied from the statusline), "Updated: 00:00 (via Claude app)" — never goes stale, always outranks the statusline |
| desktop `t: NaN` or `1e400` | title `7%`, no `~`, "⚠ capture time unknown" |
| statusline `captured_at` +31 years | `5%`, "Updated: 08:33", never stale |
| 100 000-deep nested array in either file | `RecursionError` escapes both readers' `except` (tracker.py:361-366, 415), is caught at :837 → title `?` (rows stale, cf. Phase 1 P12) |
| `used_percentage: {"a":1}`, `captured_at: [1,2]` | `~0%`, "⚠ capture time unknown" — degraded but honest |
| `resets_at` = a 10 MB string | `resets --`, no hang |

In the capture script, the same `RecursionError` is not a `ValueError` (script:124) so it reaches the backstop (:176), is logged, exit 0 — correct.

**What an attacker gets.** A process already running as the user can pin an arbitrary percentage on the menu bar as "fresh" forever, or wedge the worker on "…" with a multi-GB file. That process could equally replace `tracker.py` or `~/.tokease/tokease-statusline.py` (both user-writable; the latter is what Claude Code executes), so this is strictly weaker than what the attacker already has.

**Exploitability / blast radius.** Requires code execution as the user — a stronger position than the app's own trust boundary. Theoretical; Low.

**Fix sketch.** In `_captured_at`: `math.isfinite` and clamp `captured_at > now + 300` to "unknown" (returns 0.0 → existing `~`/⚠ path); `json.loads(..., parse_constant=_reject)`; `stat().st_size > 8 MiB` → treat as `error`; catch `RecursionError` alongside `JSONDecodeError` so the reader returns `error` cleanly.

### F7 — Info — File permissions, atomic write, symlinks: sound; one asymmetry `[solo — no peer available]`

**Evidence.** `~/.tokease` created 0700 by all three writers (tracker.py:131; script:41-45 also `chmod`s a pre-existing dir; install-statusline.sh:19-20). Files inside inherit umask (usage.json, icon, statusline.err at 0644) — acceptable behind a 0700 directory. Capture write is temp-in-same-dir + `os.replace` (script:96-100), temp removed on failure (:102); `os.replace` onto a symlinked `usage.json` replaces the link, not the target. Temp name `.usage.<pid>.tmp` is predictable and `open(tmp, "w")` follows a pre-planted symlink — same-user only, so not a finding. `tracker.py:131` does **not** tighten a pre-existing `~/.tokease` (the script does), so a directory created 0755 by hand stays 0755 until the capture script first runs. No `cwd`-relative paths, no `/tmp` use, no `os.chmod` on user-controlled paths.

**Fix sketch.** Mirror script:42-45 in `_render_dynamic_icon` (one `chmod` in a `try`). Cosmetic.

### F8 — Info — Subprocess / injection surface: one binary, argv form, unreachable on shipped installs `[solo — no peer available]`

**Evidence.** Both spawns use an absolute path and a list argv, no shell (tracker.py:251-255, 278-281). `_set_login_item` interpolates `app_path` into an AppleScript literal but rejects `"`, `\` and newline first (:264) and the value comes from `sys.executable` (:240-243); a CR in the path would also end the literal, but the path is the app's own. Both functions are reachable only when `sys.frozen` is set (:237, :621), i.e. the py2app bundle that is **not distributed** (ROADMAP.md:44, 68). install.sh interpolates `$SCRIPT_DIR`/`$VENV_DIR` into a plist heredoc and refuses `&`/`<` (:76-81); `>` and `"` are inert in XML text content. uninstall.sh escapes the path before `pkill -f` (:34); `pkill` can only signal the user's own processes. The `statusLine.command` written is a fixed constant (`python3 ~/.tokease/tokease-statusline.py`, install-statusline.sh:12) that Claude Code resolves through the user's PATH — same exposure as any statusline command; no Tokease-specific issue.

### F9 — Info — Secrets and repository hygiene `[solo — no peer available]`

**Evidence.** No credential in the working tree or in `git log --all -p` (patterns listed at the top). `.gitignore` excludes `.env`, `*.local.json`, `.claude/`, `.mcp.json`. `sonar-project.properties` carries no token (SonarCloud automatic analysis). The one env var the app reads is `RESOURCEPATH` (tracker.py:74, py2app-set); the script reads `TOKEASE_STATUSLINE_QUIET` (script:168). NSUserDefaults holds four display preferences only (tracker.py:159-162). The README/PRIVACY/SECURITY claims checked against code: "never reads a token / Keychain / network" — holds by inspection of the two shipped files (all imports: json, math, os, subprocess, sys, threading, webbrowser, datetime, pathlib, rumps, PIL, Foundation, PyObjCTools; time in the script) and by F1's tripwire, with F1's caveats; "no secrets on disk" — holds; "read-only on the Claude app's folder" — holds (single `read_text`, :414). The **shell-out to the browser** (`webbrowser.open(STAR_URL)`, :741) is the one network-adjacent action and PRIVACY.md:20-21 discloses it.

---

## Summary

| Severity | Count | IDs |
|---|---|---|
| Critical | 0 | — |
| High | 0 | — |
| Medium | 1 | F1 |
| Low | 5 | F2, F3, F4, F5, F6 (F6 theoretical) |
| Info | 3 | F7, F8, F9 |

The token-free promise **holds in the code as shipped today**: no network client, no credential API, no credential file path, one `osascript` spawn, one browser open to a constant URL. What does not hold up as well as the docs imply is the *automated* guard: F1 shows six cheap ways to reintroduce the v0.9 behaviour that the CI tripwire would wave through. Since that test is the only thing standing between a merged PR and a broken public promise, tightening it is the one change in this review with a payoff proportional to the product's positioning. Everything else is hygiene on the installers and the dependency chain.

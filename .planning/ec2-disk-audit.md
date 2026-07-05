# EC2 Disk-Usage Audit — `personalai` (Ubuntu 24.04, x86_64)

**Date:** 2026-07-05
**Host:** private AWS EC2, reached via `ssh personalai`
**Root volume:** `/dev/root` — 24 GB, **22 GB used, 1.5 GB free (94% full)**
**Mode:** READ-ONLY inspection. Nothing on the server was changed, deleted, moved, or restarted.

---

## TL;DR

- The box is **legitimately full of active workloads**, not junk. The two largest consumers — the container image store (~5.2 GB) and the Hermes agent runtime (~3.6 GB across `~/.hermes` + `/opt/hermes-workspace`) — are **in active use and must not be touched**.
- **`du -sh /*` sums to ~28 GB but only 22 GB is actually used.** The ~4–5 GB gap is `du` double-counting: `/var/lib/docker/rootfs/overlayfs` is just the **live overlay mounts of the 3 running containers**, whose underlying layers already live in `/var/lib/containerd`. Deleting one does **not** free the other — same blocks.
- **Docker prune reclaims ≈ 0.** No dangling images, no stopped containers, build cache is 0 B. All 3 images are attached to running containers.
- **Realistically safe-to-reclaim without touching active services: ~0.3–1.1 GB** (log/journal/package/pip/npm/tmp caches). Pushing further (~1.8 GB more) means clearing the Playwright browser cache and pnpm store, which only costs re-download time but is a judgment call.
- **`careeros-pm` does not exist** on this box right now — only `~/.config/careeros-secrets` (8 KB) and a stray `/tmp/careeros-regen-*` remain.

---

## Summary table

| Category | Size | Reclaimable? | Notes |
|---|---:|---|---|
| **`/var/lib/containerd`** (docker/moby image + snapshot store) | 5.2 GB | ❌ No | 3 active images, 0 dangling. **DO NOT TOUCH — active** |
| **`/var/lib/docker/rootfs/overlayfs`** | 4.2 GB | ❌ No (double-counted) | Live overlay mounts of the 3 running containers. **DO NOT TOUCH — active** |
| **`~/.hermes`** (Hermes agent runtime) | 2.2 GB | ❌ No | venv 710M + node_modules 414M + state.db 83M + logs 81M. **DO NOT TOUCH — active** |
| **`/opt/hermes-workspace`** | 1.4 GB | ❌ No | Active workspace mounted into the hermes container. **DO NOT TOUCH — active** |
| `/usr` (system: `/usr/lib` 1.9G, `/usr/share` 1.2G, `/usr/bin` 720M) | 4.3 GB | ❌ No | OS + toolchains (incl. TeX Live). Leave alone |
| `/swapfile` | 4.1 GB | ❌ No | Active swap. **DO NOT TOUCH** |
| `~/.local/share/pnpm/store` | 1.2 GB | ⚠️ Partial | Global pnpm content store; `pnpm store prune` removes only unreferenced. Medium risk |
| **`~/.cache/ms-playwright`** | 646 MB | ⚠️ Yes (re-downloads) | Chromium 379M + headless-shell 262M + ffmpeg 5M. Medium risk |
| `/snap` + `/var/lib/snapd` | 625M + 181M | ❌ No (mostly) | 3 snaps: amazon-ssm-agent, core22, snapd. Base OS tooling |
| `~/.npm/_cacache` | 172 MB | ✅ Yes (re-downloads) | npm download cache. Low risk |
| `/var/log/journal` (journald) | 106 MB | ✅ Partial | Vacuum to ~50M ⇒ ~56M. Low risk |
| `/var/cache/apt` | 112 MB | ✅ Partial | Only 5.3M is `archives`; rest is regenerable index. Low risk |
| `~/.local/share/uv` (uv cache) | 97 MB | ✅ Yes | Rebuilds on demand. Low risk |
| `/var/lib/texmf` + `~/.texlive2023` | 79 MB | ❌ No | LaTeX/PDF toolchain, used by the pipeline |
| `~/.cache/pip` | 14 MB | ✅ Yes | pip cache. Low risk |
| `/tmp` cruft | ~30 MB | ✅ Yes | Stale screenshots, node_modules, logs, `.bak`. Low risk |
| Kernels (2 installed) | ~107 MB each | ❌ Not now | Running = 1017, pending-boot = 1019. Neither safely removable yet |
| **`~/n8n` + n8n docker volumes** | 8 KB + 96 MB | ❌ No | **DO NOT TOUCH — active** |

---

## 1. Top-level overview

```
Filesystem      Size  Used Avail Use% Mounted on
/dev/root        24G   22G  1.5G  94% /
```

**One-line summary:** 24 GB root volume, **22 GB used / 1.5 GB free / 94% full**.

Top-level tree (`sudo du -sh /* | sort -rh`):

| Path | Size | What it is |
|---|---:|---|
| `/var` | 11 GB | Container stores + logs + package data (see §2/§3) |
| `/home` | 4.5 GB | `ubuntu` user: Hermes runtime, caches, projects (see §7) |
| `/usr` | 4.3 GB | OS libraries, shared data, binaries, toolchains |
| `/swapfile` | 4.1 GB | Swap file — active, do not touch |
| `/root` | 1.7 GB | root user home |
| `/opt` | 1.4 GB | `/opt/hermes-workspace` (active) |
| `/snap` | 625 MB | Mounted snap packages |
| `/boot` | 169 MB | Kernels + initrd |
| `/tmp` | 27 MB | Temp files (some stale) |

> **Note on the numbers:** the column above sums to ~28 GB, which is *more* than the 22 GB actually used. This is expected — `du` counts the running containers' overlay merged views under `/var/lib/docker/rootfs` **and** their source layers under `/var/lib/containerd` as if they were distinct, but they share the same on-disk blocks. See §3.

---

## 2. Biggest space consumers (drill-down)

### `/var` = 11 GB — dominated by `/var/lib`

`sudo du -sh /var/lib/* | sort -rh`:

| Path | Size | What it is | Verdict |
|---|---:|---|---|
| `/var/lib/containerd` | 5.2 GB | Docker's actual image + snapshot store (moby namespace) | **Active — do not touch** |
| `/var/lib/docker` | 4.3 GB | Docker state; 4.2 GB is live container overlay mounts | **Active — double-counts containerd** |
| `/var/lib/apt` | 186 MB | apt package lists/metadata | Regenerable, low value |
| `/var/lib/snapd` | 181 MB | snap runtime data | Base tooling |
| `/var/lib/texmf` | 79 MB | TeX Live font/format cache | Used by PDF pipeline |
| `/var/lib/dpkg` | 57 MB | dpkg database | Do not touch |

`/var/cache` = 156 MB, `/var/log` = 135 MB (see §4/§5).

### `/home` = 4.5 GB, `/usr` = 4.3 GB, `/opt` = 1.4 GB

- `/home` breakdown in §7. Dominated by `~/.hermes` (2.2 GB) and `~/.local` (1.5 GB).
- `/usr`: `/usr/lib` 1.9 GB, `/usr/share` 1.2 GB, `/usr/bin` 720 MB, `/usr/src` 331 MB (kernel headers). Normal OS footprint — leave alone.
- `/opt`: `/opt/hermes-workspace` 1.4 GB (active), `/opt/hermes-workspace-data` 60 KB.

---

## 3. Docker footprint

**Storage driver:** `overlayfs` via the **containerd image store** (`io.containerd.snapshotter.v1`). Docker's single containerd namespace is `moby`. This is why the image data lives in `/var/lib/containerd` (5.2 GB) rather than a classic `/var/lib/docker/overlay2`.

### `docker system df -v`

| Images | Tag | Disk usage | Content | Containers |
|---|---|---:|---:|---:|
| `n8nio/n8n` | latest | 2.49 GB | 390 MB | 1 |
| `ghcr.io/outsourc-e/hermes-workspace` | latest | 2.31 GB | 451 MB | 1 |
| `postgres` | 14 | 628 MB | 163 MB | 1 |

- **Build cache: 0 B.** **Dangling images: none.**
- **Local volumes:** `n8n_postgres_data` 78.3 MB, `n8n_n8n_data` 18.1 MB.

### `docker ps -a` — all 3 containers are UP, none stopped

| Container | Image | Status | Flag |
|---|---|---|---|
| `n8n_n8n_1` | n8nio/n8n | Up 4 days | **DO NOT TOUCH — active (n8n)** |
| `n8n_postgres_1` | postgres:14 | Up 4 days | **DO NOT TOUCH — active (n8n db)** |
| `hermes-workspace` | ghcr.io/outsourc-e/hermes-workspace | Up 8 days (healthy) | **DO NOT TOUCH — active (hermes)** |

### Reclaimable via prune

- `docker system prune` → **≈ 0 B** (no stopped containers, no dangling images, no build cache).
- `docker system prune -a` → still **≈ 0 B**, because all 3 images are attached to running containers. It would attempt to remove "unused" images but finds none.

### The `/var/lib/docker/rootfs` "duplicate" — explained (important)

`/var/lib/docker/rootfs/overlayfs` (4.2 GB) contains exactly **3 subdirectories**, each an `overlay` mount whose name is one of the running **container IDs** (`1b3fe…` hermes, `7f383…` postgres, `da63a…` n8n). Confirmed via `/proc/mounts` / `findmnt`: these are the **live merged rootfs mounts** of the running containers. Their lower layers are the snapshots in `/var/lib/containerd/io.containerd.snapshotter.v1.overlayfs` (4.2 GB) + content blobs (958 MB).

**Conclusion:** the container image footprint is **~5.2 GB total, not ~9.5 GB.** The apparent duplication is `du` counting shared overlay blocks twice. There is **no orphaned/legacy docker storage** to reclaim here — no `overlay2` dir, no `image` dir, `daemon.json` absent (defaults).

---

## 4. Logs

- **journald:** `Archived and active journals take up 106.3M` → `/var/log/journal` = 107 MB.
- `/var/log` breakdown (`sudo du -sh /var/log/* | sort -rh`):

| Path | Size |
|---|---:|
| `/var/log/journal` | 107 MB |
| `/var/log/syslog` | 14 MB |
| `/var/log/sysstat` | 6.4 MB |
| `/var/log/auth.log.1` | 2.4 MB |
| `/var/log/syslog.2.gz` | 1.7 MB |
| `/var/log/amazon` | 1.0 MB |

No runaway rotated logs. Journal is the only meaningful target (vacuum to ~50 MB is safe).

> Separately, `~/.hermes/logs` = 81 MB (agent.log + 3 rotations of 5 MB each + errors.log). **Active agent — do not touch;** it already self-rotates.

---

## 5. Package / apt caches, kernels, snap

- **`/var/cache/apt` = 112 MB**, of which **`archives` = only 5.3 MB** (downloaded `.deb`s). The rest is the regenerable package index. `apt clean` frees ~5 MB of real space.
- **Kernels (`dpkg --list | grep linux-image`):**
  - `linux-image-6.17.0-1017-aws` — **currently running** (`uname -r` = `6.17.0-1017-aws`)
  - `linux-image-6.17.0-1019-aws` — installed, **pending next reboot** (meta `linux-image-aws` points here)
  - Modules ~32 MB each in `/usr/lib/modules`; ~75 MB each in `/boot`.
  - ⚠️ **Neither is safely removable now:** 1017 is live, 1019 is the next boot target. `autoremove` will only prune old kernels *after* a reboot into 1019. Reclaim potential ≈ 0 today.
- **snap:** `/var/lib/snapd` = 181 MB, `/snap` = 625 MB. `snap list`:
  - `amazon-ssm-agent` (classic), `core22`, `snapd` — all base/AWS tooling. No old revisions to trim. Leave alone.

---

## 6. Playwright / browser caches

- **`~/.cache/ms-playwright` = 646 MB** (owned by `ubuntu`):
  - `chromium-1228` = 379 MB
  - `chromium_headless_shell-1228` = 262 MB
  - `ffmpeg-1011` = 4.9 MB
- No duplicate Playwright browser copies were found under project `node_modules` (only this single shared cache; `.hermes/hermes-agent/node_modules` 414 MB does not contain a browser bundle).
- **Likely still used** for screenshot/automation (stale `careeros_*_smoke.png` in `/tmp` were produced by a Playwright run). Removable but re-downloads on next use → **medium risk**.

---

## 7. Home directory breakdown (`/home/ubuntu`)

`sudo du -sh /home/ubuntu/* /home/ubuntu/.* | sort -rh`:

| Path | Size | What it is | Verdict |
|---|---:|---|---|
| `~/.hermes` | 2.2 GB | Hermes agent runtime (venv 710M, node_modules 414M, state.db 83M, logs 81M, node 204M, bin 80M, skills 69M) | **DO NOT TOUCH — active** |
| `~/.local` | 1.5 GB | `share/pnpm` 1.2 GB (store), `share/uv` 97 MB, `lib` 74 MB, `bin` 59 MB | Caches partly prunable (§8) |
| `~/.cache` | 660 MB | `ms-playwright` 646 MB, `pip` 14 MB, `uv` 28 KB | Prunable (re-downloads) |
| `~/.npm` | 189 MB | `_cacache` 172 MB, `_npx` 18 MB | Prunable |
| `~/.claude` | 7.3 MB | Claude Code state | Small, leave |
| `~/moatdaily` | 2.5 MB | Project checkout | Active project, small |
| `~/backups` | 1.0 MB | Small backup dir — inspect contents before assuming stale | Tiny; negligible |
| `~/n8n` | 8 KB | n8n compose/config | **DO NOT TOUCH — active** |
| `~/.config/careeros-secrets` | 8 KB | careeros secrets | Active config — leave |

Notes:
- **No `careeros-pm` directory exists.** Only leftovers: `~/.config/careeros-secrets` (8 KB) and `/tmp/careeros-regen-NJo8iI` (244 KB).
- No large stale archives, tarballs, or duplicate project checkouts were found in the home tree.

---

## 8. Redundancy / waste findings

1. **Overlay double-count (not real waste, but explains the "missing" space):** `/var/lib/docker/rootfs/overlayfs` (4.2 GB) = live mounts of running containers, sharing blocks with `/var/lib/containerd` (4.2 GB). Real container footprint ≈ 5.2 GB. Nothing to reclaim.
2. **npm cache** `~/.npm/_cacache` (172 MB) — pure download cache, safe to clear.
3. **pnpm global store** `~/.local/share/pnpm/store` (1.2 GB) — content-addressed store; some fraction is unreferenced. `pnpm store prune` (read-only impact: removes only packages no project links to) would reclaim an unknown but likely meaningful slice. Medium risk (pnpm hardlinks from here into project `node_modules`).
4. **uv cache** `~/.local/share/uv` (97 MB) + `~/.cache/uv` — rebuildable.
5. **pip cache** `~/.cache/pip` (14 MB) — rebuildable.
6. **Playwright browsers** (646 MB) — single shared copy (good, no duplication), but reclaimable if browser automation is idle.
7. **journald** (106 MB) — over the effective need; vacuum to ~50 MB.
8. **`/tmp` stragglers** (~30 MB): `/tmp/node_modules` 18 MB, `/tmp/node-compile-cache` 5.3 MB, `/tmp/reports-server.log` 2 MB, `careeros_*_smoke.png` 640 KB, `sierra-*.html` 276 KB, `/tmp/pdf.md.bak`, `/tmp/careeros-regen-*`.
9. **Old kernel** (1017) — will become removable only *after* a reboot into 1019; ~107 MB then.
10. **No dangling docker images, no stopped containers, no build cache** — nothing to prune there.

---

## Safe to reclaim (prioritized) — *recommendations only; nothing was executed*

### Tier 1 — Low risk, quick wins (~0.3 GB)
| Action | Est. reclaim | Risk |
|---|---:|---|
| Vacuum journald to 50 MB (`journalctl --vacuum-size=50M`) | ~56 MB | Low |
| Clear npm cache (`npm cache clean --force`) | ~172 MB | Low (re-downloads) |
| Clear pip + uv caches | ~110 MB | Low (rebuilds) |
| `apt clean` (archives only) | ~5 MB | Low |
| Remove stale `/tmp` files (node_modules, logs, screenshots, `.bak`) | ~30 MB | Low |
| **Tier 1 subtotal** | **~0.37 GB** | |

### Tier 2 — Medium risk, costs re-download/rebuild time (~1.8 GB)
| Action | Est. reclaim | Risk |
|---|---:|---|
| Clear Playwright browser cache (`~/.cache/ms-playwright`) | ~646 MB | Medium — re-downloads on next automation run |
| `pnpm store prune` (unreferenced packages only) | up to ~1.2 GB (actual less) | Medium — verify no active project depends on pruned entries |
| **Tier 2 subtotal** | **~0.6–1.8 GB** | |

### Deferred (needs a reboot first)
- After rebooting into kernel `6.17.0-1019-aws`, `apt autoremove --purge` can drop the old `6.17.0-1017-aws` kernel → ~107 MB. Do not remove before reboot.

**Combined realistic headroom without touching any active service: ~1 GB immediately, up to ~2.2 GB if caches are cleared.** This lifts free space from 1.5 GB toward ~2.5–3.7 GB. For a durable fix, the only large lever is **growing the 24 GB EBS volume** — the genuine consumers (containers 5.2 GB, Hermes 3.6 GB, OS 4.3 GB, swap 4.1 GB) are all legitimate and here to stay.

---

## Do NOT touch (active / load-bearing)

- **`/var/lib/containerd` (5.2 GB)** and **`/var/lib/docker` (4.3 GB)** — active docker/containerd image store + live container mounts.
- **`hermes-workspace` container + image (2.31 GB)**, **`~/.hermes` (2.2 GB)**, **`/opt/hermes-workspace` (1.4 GB)** — active Hermes agent runtime.
- **`n8n_n8n_1` + `n8n_postgres_1` containers**, **`~/n8n`**, **`n8n_n8n_data` / `n8n_postgres_data` volumes (96 MB)** — active n8n stack.
- **`postgres:14` image (628 MB)** — backing the running n8n DB.
- **`/swapfile` (4.1 GB)** — active swap.
- **Both installed kernels** — 1017 running, 1019 pending boot.
- **`~/.config/careeros-secrets`** — active credentials.

---

## Appendix — exact commands run (reproducible, all read-only)

<details>
<summary>Commands executed via <code>ssh personalai "…"</code></summary>

```bash
# Overview
df -h /
df -h --total /
sudo du -sh /* 2>/dev/null | sort -rh | head -15

# /var drill-down
sudo du -sh /var/* 2>/dev/null | sort -rh | head -12
sudo du -sh /var/lib/* 2>/dev/null | sort -rh | head -12

# Docker
sudo docker system df -v
sudo docker ps -a
sudo docker images -a
sudo docker images -f dangling=true
sudo docker info | grep -iE 'storage driver|containerd|images:|containers:'
sudo cat /etc/docker/daemon.json

# containerd vs docker storage (glob run as root so it expands root-only dirs)
sudo sh -c 'du -sh /var/lib/containerd/*/ 2>/dev/null | sort -rh'
sudo sh -c 'du -sh /var/lib/docker/*/ 2>/dev/null | sort -rh'
sudo ctr namespaces list
for ns in $(sudo ctr namespaces list -q); do sudo ctr -n $ns images list; sudo ctr -n $ns containers list; done
findmnt -o TARGET,SOURCE,FSTYPE | grep -iE 'docker|containerd|overlay'
sudo sh -c 'ls /var/lib/docker/rootfs/overlayfs/'

# Logs
journalctl --disk-usage
sudo du -sh /var/log/* 2>/dev/null | sort -rh | head

# apt / kernels / snap
sudo du -sh /var/cache/apt /var/cache/apt/archives
dpkg --list | grep linux-image
uname -r
sudo du -sh /usr/lib/modules/* 2>/dev/null | sort -rh
sudo du -sh /boot/* 2>/dev/null | sort -rh
du -sh /var/lib/snapd
snap list

# Home + caches
sudo du -sh /home/ubuntu/* /home/ubuntu/.* 2>/dev/null | sort -rh | head -25
sudo du -sh /home/ubuntu/.hermes/* 2>/dev/null | sort -rh
sudo du -sh /home/ubuntu/.local/share/* 2>/dev/null | sort -rh
sudo du -sh /home/ubuntu/.cache/* 2>/dev/null | sort -rh
du -sh /home/ubuntu/.cache/ms-playwright/* | sort -rh
sudo du -sh /home/ubuntu/.npm/* 2>/dev/null | sort -rh

# opt / tmp / careeros
sudo du -sh /opt/* 2>/dev/null | sort -rh
sudo du -sh /tmp/* 2>/dev/null | sort -rh | head
sudo find / -maxdepth 4 -type d -name 'careeros*' 2>/dev/null
```
</details>

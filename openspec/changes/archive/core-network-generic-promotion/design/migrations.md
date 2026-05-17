# core-network-generic-promotion — Migrations

本文件承接 design.md Migrations 节详细内容 — 旧 ckpt / cfg / registry / dossier / ADR 处理 + 备份步骤。

## 旧 ckpt(r009/r011/r012/...)
- **不迁移,直接删**:`rm -rf artifacts/checkpoints/*`(gitignored,本不在 git)
- 历史 reference 通过 `git checkout pre-core-network-redesign-2026-05-17` + 老代码 load

## 旧 cfg(`configs/{active,shipped,smoke}/`)
- **显式归档**到 `configs/_archived/pre_redesign_2026_05_17/`(跟现有 `configs/_archived/ppo_apr/` pattern 一致):
  `git mv configs/{active,shipped,smoke} configs/_archived/pre_redesign_2026_05_17/`
- 老 cfg 设计参考价值高(40+ toml 涵盖 r001-r012 + s001-s068 ablation),保留在 working tree 内可直接 `ls` / `grep` 检索,不依赖 git history 翻档
- `configs/_archived/ppo_apr/` 保留原位(早期 archive 已 frozen,不动)
- 新 `configs/<paradigm>/{default,smoke,runs/}.toml` 全部重写,与 `_archived/` 同级
- 5 paradigm 各写 1 个 `default.toml` + 1 个 `smoke.toml`(共 10 个新 toml)

## 旧 registry(`docs/4_runs/registry.md` 11 行 r001-r012)
- **一次性 dump 到 `docs/5_history/runs_pre_redesign_2026_05_17.md`**(git tracked,documentation)
- 老 registry.md `git rm`
- 新 run history 全部走 `tools.runs.*` CLI + `artifacts/runs/<id>.toml`

## 旧 dossier(`docs/paradigms/<X>/`)
- 引用旧 ckpt / 旧 cfg 路径的段落更新或标 SUPERSEDED
- 不迁移 dossier 主体内容(实验性记录,git history 保留)

## ADR
- ADR-0009(RL paradigm pivot,含 r009 production fallback 条款)→ 标 SUPERSEDED-BY: `core-network-generic-promotion`
- ADR-0019(typed obs ckpt break)→ 加 follow-up note:本 change 后整 ckpt schema 重设计,ADR-0019 break 被新 schema 吸收
- 撤销 cfr/C6.2 r008 reproducibility(spec inline 修订)
- 撤销 W4-PPO closure 残留引用(PPO 收编为 first-class generic backbone user)

## 备份步骤(Phase 0 一次性)

```bash
# 1. git tag(永久锚)
git tag -a pre-core-network-redesign-2026-05-17 \
         -m "before core-network-generic-promotion change"

# 2. 物理 rm(本来 gitignored)
rm -rf artifacts/checkpoints/* artifacts/replays/*

# 3. configs/ 老树显式归档(保留参考价值)
mkdir -p configs/_archived/pre_redesign_2026_05_17/
git mv configs/active configs/shipped configs/smoke configs/_archived/pre_redesign_2026_05_17/
git commit -m "configs: archive pre-redesign tree (active/shipped/smoke → _archived/pre_redesign_2026_05_17/)"

# 4. 老 registry dump 到 docs/5_history/
git mv docs/4_runs/registry.md docs/5_history/runs_pre_redesign_2026_05_17.md
# 加 banner + 顶部说明 sealed 2026-05-17,然后 commit
```

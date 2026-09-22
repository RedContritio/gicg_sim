# Historical ADR pointers

The ADR files in this directory preserve the original decision narratives. ADR
0001–0012 and 0017–0019 were migrated to OpenSpec change archives on
2026-05-15. Current behavior is specified under `openspec/specs/`; use the
archives below to understand why a decision was made.

| ADR | Decision | Canonical archive |
|---|---|---|
| [0001](adr-0001-web_live_mcts_cancel.md) | Web live MCTS cancellation | [`0001-web-live-mcts-cancel`](../../openspec/changes/archive/0001-web-live-mcts-cancel/) |
| [0002](adr-0002-capi_obs_d5_d9.md) | C API and observation space | [`0002-capi-obs-d5-d9`](../../openspec/changes/archive/0002-capi-obs-d5-d9/) |
| [0003](adr-0003-engine_bugs_d10_d13.md) | Engine fixes D10–D13 | [`0003-engine-bugs-d10-d13`](../../openspec/changes/archive/0003-engine-bugs-d10-d13/) |
| [0004](adr-0004-is_mcts_migration.md) | IS-MCTS migration | [`0004-is-mcts-migration`](../../openspec/changes/archive/0004-is-mcts-migration/) |
| [0005](adr-0005-az_decisions_d1_d14.md) | AZ decisions D1–D14 | [`0005-az-decisions-d1-d14`](../../openspec/changes/archive/0005-az-decisions-d1-d14/) |
| [0006](adr-0006-training_layout.md) | Training layout | [`0006-training-layout`](../../openspec/changes/archive/0006-training-layout/) |
| [0007](adr-0007-ppo_bc_warmstart.md) | PPO BC warm start | [`0007-ppo-bc-warmstart`](../../openspec/changes/archive/0007-ppo-bc-warmstart/) |
| [0008](adr-0008-rl_paradigm_pivot.md) | RL paradigm pivot | [`0008-rl-paradigm-pivot`](../../openspec/changes/archive/0008-rl-paradigm-pivot/) |
| [0009](adr-0009-rl_paradigm_pivot_terminus.md) | Pivot terminus | [`0009-rl-paradigm-pivot-terminus`](../../openspec/changes/archive/0009-rl-paradigm-pivot-terminus/) |
| [0010](adr-0010-rl_research_reopen.md) | RL research reopened | [`0010-rl-research-reopen`](../../openspec/changes/archive/0010-rl-research-reopen/) |
| [0011](adr-0011-pool_versioning.md) | Pool versioning | [`0011-pool-versioning`](../../openspec/changes/archive/0011-pool-versioning/) |
| [0012](adr-0012-specialty_and_prepare_skill.md) | Specialty and prepare skill | [`0012-specialty-and-prepare-skill`](../../openspec/changes/archive/0012-specialty-and-prepare-skill/) |
| [0017](adr-0017-dsl_v4.md) | DSL v4 prototype | [`0017-dsl-v4`](../../openspec/changes/archive/0017-dsl-v4/) |
| [0018](adr-0018-dsl_v5_event_sourcing.md) | DSL v5 event sourcing | [`0018-dsl-v5-event-sourcing`](../../openspec/changes/archive/0018-dsl-v5-event-sourcing/) |
| [0019](adr-0019-dsl_v6_semantic_engine.md) | DSL v6 semantic engine | [`0019-dsl-v6-semantic-engine`](../../openspec/changes/archive/0019-dsl-v6-semantic-engine/) |

Early D1–D4 DSL API decisions remain in
[`docs/5_history/decisions_legacy/`](../5_history/decisions_legacy/).

For a new decision, start from [`_template.md`](_template.md), then follow the
current OpenSpec workflow in [AGENTS.md](../../AGENTS.md).

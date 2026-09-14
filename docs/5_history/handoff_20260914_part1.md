# 历史交接记录（非当前状态）

原 docs/HANDOFF.md 的时间线存档；其中“正在运行”等措辞只描述当时。当前状态见 [实时入口](../0_status/README.md)。

# GICG_MONO 交接文档

最新正式任务（2026-09-14）：辅助RL冒烟cell3046/session92481已退出0，报告native_auxiliary_checked_20260914.json；run000028/000029，辅助优化器18→32，有限参数及恢复检查通过。现已启动辅助/普通RL同预算对照：session67309，完成等待器cell3054，根artifacts/native_auxiliary_comparison_20260914。auxiliary_pipeline.py先auxiliary beta.5，再control beta0，各4×256、8workers、同初始000016 iteration7、seed94700、value baseline/T.5/D2、50%变体，stride4最多8动作；每轮原生开发93100，随后93990变体选模（包括初始），94890各110场景440局独立复核、配对比较。这是发展阶段一训练种子对照，非最终稳定验收。新progress支持此root的rl/变体评估，stdout≤200B；可按需查询。当前训练源冻结，结束自动拉摘要/日志/配对。还需完成五角色反事实响应和结算预测泛化检查，不能只凭辅助loss或单次胜率达标。

最新活动（2026-09-14）：辅助RL已集成：network可返回共享state/actions（默认logits不变）；rule_auxiliary训练头预测9字段，loss梯度进hook/action表示；rl_rollout每4个己方决策采集最多8个逻辑动作（执行动作+技能优先），独立Python RNG不消耗策略torch RNG；rl_update合并辅助loss，共享net lr1e-5、独立头lr3e-4；rl.py保存/恢复头+优化器+配置。14测试通过，实际整局开启/关闭标签动作/概率/回报完全一致，aux梯度进入hook且不直接训练Q head。CLI提取rl_cli保持代码<300行。56首次冒烟session41010在评估时因dev_scenarios=1不满足55倍数而退出（已完成采集和更新，不是训练梯度错误）；已增加启动前eval_cases校验，修正55并新目录重试。当前session92481/完成等待器cell3046，native_auxiliary_checked_20260914_0/_1，两轮4局，beta.5/stride4，seed94610/dev94620，value baseline/T.5/D2，检查优化器步数递增，结束拉native_auxiliary_checked_20260914.json。未启动正式预算。如同一错误再失败必须按CLAUDE请求独立review。

最新开发（2026-09-14）：新增rule_outcomes.py训练用引擎标签，9字段（actor相对双方HP/能量/存活变化、terminal/result/pending），snapshot/step/restore；五角色真实引擎恢复与伤害交换6测试通过。没有策略最优标签假设，没有接入当前RL或新训练。下一步和限制落盘docs/3_plans/cards/rule_auxiliary_training.md：真实变体对局持续辅助结算预测+RL、共享表示梯度、独立胜率及五角色规则响应联合验收。当前无活动训练任务。

最新完成与证据（2026-09-14）：保守DAgger cell3008/session18464已退出0，耗时1660s；3轮开发31.82/31.82/32.73%，均低于初始40%。94490独立复核仍选初始000016 iteration7，39.55%[33.18,45.91]，没有收益。全部摘要已归档native_conservative_20260914。新增只读反事实检查session15602退出0，counterfactual.json已拉回：复用rule_probe.variant/trio_case/damage_oracle/rank，在3v3含手牌/全能骰下交换凯亚两技能伤害(2,6)/(6,2)/(4,8)/(8,4)，seed94510/94511、layout7/19，初始RL/保守第1轮/第3轮均8/16即时伤害排名正确，始终偏好霜袭；分数随伤害变化仅约0.01，原偏好差约4，不能声称已学规则。此为受限即时HP比较，不是全局最优，完整动作还可能优先出牌。当前无训练运行；下一步应设计覆盖五角色的持续规则辅助训练+RL，避免仅凯亚小探针代替目标，不再盲加D2监督。旧活动状态均为历史。

用户新增进度工具（2026-09-14）：semantic_training.progress已实现并在56实测，stdout含换行≤200 UTF-8字节；按需调用cfg+任务目录，输出阶段计数/累计耗时/更新年龄，见VARIANTS.md。最新一次：轮3/3、采集112/256、累计16.9m、6s前更新。任务session18464/cell3008继续运行；用户允许用此工具查进度，仍避免无意义高频查询。

最新活动（2026-09-14）：保守DAgger任务已启动56，exec session18464，完成等待器cell3008。先2轮4局/2更新冒烟（含replay/有限KL断言），成功后自动正式3×256局/各1000更新，初始000016 iteration7，训练seed仍94120–94122，set目标/lr1e-5/anchor_beta1（每轮冻结该轮初始），93990开发选模、94490新独立440局复核。输出artifacts/native_conservative_20260914；结束自动拉completion/status/console/paired。只等cell3008退出，不轮询中间指标，不重复启动。5相关测试通过；core指纹未变，远端启动前断言7b4ef71…及旧DAgger已complete。此为联合训练设置对照，不能单独归因学习率/并列目标/KL各项。

最新诊断（2026-09-14）：只读fit审计session72268正常退出，fit_audit.json已拉回。每轮均匀reservoir256决策；并列标签占54–60%，DAgger相对初始改变动作39–48%，D2标签命中仅略升（如round1样本77.73→81.25%），训练fit提升不能代表胜率。已在本机加入可选tie_objective=set（最大化并列集合概率，不强迫集合内部均匀）、learning_rate、anchor_beta冻结初始策略KL；默认uniform/3e-4/0保持旧实验可复现。新增4个损失测试＋实际DAgger采集测试通过。新选项尚未同步56或运行训练。下一步从000016 iteration7做保守监督对照（建议set/lr1e-5/anchor_beta1），需冒烟、正式变体开发、独立复核；禁止宣称已超过D2或规则泛化完成。

最新收尾（2026-09-14）：DAgger cell2989/session62844 已退出0，两轮冒烟通过，正式三轮256局/1000更新完成。变体开发93990原模型40%，三轮27.27/29.09/21.82%；因此保留000016 iteration7。94290独立440局复核原模型38.64%[32.73,44.55]，候选是同一模型，配对差0，不构成DAgger收益。completion/status/paired/log已归档native_dagger_20260914。当前在56运行只读训练数据拟合/漂移审计audit_dagger.py，session72268；固定每轮256条样本，比较4模型D2并列集命中、概率质量、交叉熵、KL与动作改变率。训练学习率3e-4与均匀并列目标是待验证原因，不是已证实缺陷；未启动下一轮训练。


最新结果与下一步（2026-09-14）：延长训练及变体选模/复核已结束，session85843/cell2976退出0，run000016，耗时3609秒。93990选中第7轮；94090独立复核基线第4轮35.45%、候选42.73%[36.82,48.64]，配对+7.27pp[+1.36,+13.18]，有收益但未超过D2。报告native_variants_extended_20260914已归档。第12轮变体开发39.09%，不继续盲目追加同一路径。已实现D2 DAgger：模型实际执行动作、D2在同一变体局面重新提供标签、对手D2；半原生半变体，后轮minibatch新/旧数据各半，旧数据来源指纹必须匹配；38相关测试通过。dagger_variants.py单脚本3×256局/各1000更新，seed94120–94122，93990选模、94290独立复核。起点000016 iteration7；这是监督聚合非RL。远端将先跑两轮4局/2更新的收集与replay冒烟，成功后自动运行正式预算到completion.json，不查询中间指标。旧“任务仍运行”文字均为历史。

最新目标与动作（2026-09-14）：用户将活动目标改为“解决学习不到规则的问题，在随机变体的情况下能稳定胜过D2”。上一轮已完整结束并归档：run000014 BC、000015 RL，512示范/4000更新+4×256RL约2507秒；正式D1 75.45%、D2 39.09%，未见变体D2 33.64%[26.36,40.91]，均非目标完成。前4轮无KL早停，正式D2逐步上升，按用户增加训练方向完整恢复优化器继续至12轮（新增8×256局）。新增extend_variants.py单次脚本先训练后按93990未见变体开发选模，再对第4轮与候选分别用94090/110场景440局复核。variant verifier从catalog/seed重建逐局参数，核对席位/布局一致并重算CI，31相关测试通过。后台执行后仅等待退出事件，不查询中间指标。延长任务已启动，output=artifacts/native_variants_extended_20260914，exec session85843、后台完成等待器cell2976；本次续接仅确认等待器仍在运行，未读取中间指标。等待cell2976完成后再检查completion.json；旧80529已完成，禁止重复原pipeline。

最新实施（2026-09-14）：用户批准直接增加随机规则变体训练，并要求单脚本结束后返回，避免不断监测。已新增30参数的native_variants.toml及公共variants.py（每局1–2参数、五角色伤害/治疗/指定元素骰费、半原生半变体、训练/heldout修改值分开）；BC/RL重新在实际变体采集，逐局manifest，heldout评估两席位/布局用同一变体。variant_pipeline.py单次远端调用依次512局BC/4000更新→正式及heldout评估→4×256 RL→选模与复评，结果completion.json、日志console.log。67相关测试通过，详[变体说明](../../tools/rule_validation/VARIANTS.md)。56冒烟4局/2更新/1×4RL正在执行session8500，之后由工具等待器检查退出码，成功才同步新增验收守卫并自动启动完整预算artifacts/native_variants_20260914。不要再轮询中间指标，也不要重复启动；完成事件/退出状态是首选依据。当前工具无独立关闭会话后外部事件唤醒接口，不承诺未配置的自动唤醒。旧28570已退出0：规则初始化BC的D1 67.27%、D2 33.64%，规则probe仍遗忘；之前“活动28570”已失效。

最新训练（2026-09-14）：新表达完整原生BC run202609140320_000010_semantic_warmup已结束，stream84087退出0；128局6487行、1000更新耗时212秒。开发seed93100 D1=66.36%[58.18,74.55]、D2=40%[31.82,49.09]；各220局、所有110物理局的两布局轨迹一致，verify_native_panel重算通过，报告native_new_expression_bc_20260914已拉回。SHA=7593f755fef9863cfbaf4dfd4aec664e2a0c13fd43e316ada06baf771c29c642，经远端文件独立核对。32例rule_probe仍总选霜袭，普攻10伤变体0/16，霜袭10伤16/16；单靠通路修复+原生示范未获得反事实规则响应。现在活动exec session28570：run202609140326_000011_semantic_warmup，control=artifacts/native_rule_initialized_bc_20260914，已经48/128采集；从新表达rule-learning run000009 step1000起步，其他128示范/1000更新/seed123000/8workers相同，自动D1/D2各220局及32例规则诊断。属于规则预训练→BC，额外1000规则更新，不能称等总预算或纯RL。源码冻结指纹7b4ef71f7f13fed5d148fb2df3c21f7260c6375bec99a91daf9caf4dfe104ad1。下一步轮询28570检查对战强度和规则遗忘，尚未启动新表达RL/最终三种子验收；目标仍未达成。旧gicg_dev early_l6_followup进程52284/54600未操作。

最新活动（2026-09-14）：旧表达的 8×512 局对照已完整结束，run202609140131_000008_semantic_rl，耗时4089秒，D2开发依次41.82/43.64/38.18/31.82/39.09/35.45/35.45/34.55%，无稳定提升。随后新表达及B17同步56并重建，本机/56指纹一致为7b4ef71f7f13fed5d148fb2df3c21f7260c6375bec99a91daf9caf4dfe104ad1；旧权重不得重标或续训。新鲜规则学习诊断run202609140249_000009_semantic_rules已结束，1000更新约87秒，36训练行、16未见数值行、16间接语法行；1v1与3v3各分组均从50%到100%。这仅证明受限伤害比较任务可学，不证明完整IR泛化或D2优势。新检查点step_1000.pt SHA=6b42a28d7441bca48f39669a939d4a1d31b53dd895f6f4f8e1169959e75cd949。用户打断要求复用规则patch验证：已提取tools/rule_validation，TOML配置、隔离补丁、快照oracle、公开状态断言、模型排名和JSON报告；旧probe/lessons复用公共实现。13相关测试通过，56两份示例端到端通过，stream51183退出0。用法见[工具说明](../../tools/rule_validation/README.md)。当前无本轮训练任务运行；下一步恢复新表达下完整原生BC/RL及D1/D2评估，三种子最终验收尚未开始。下文活动描述均为历史。

用户新增要求：所有这类规则边界集中记入 [游戏内规则核验清单](../3_plans/cards/in_game_rule_verification.md)，供后续逐项实测；新增边界必须同步追加。当前整理36项原生边界＋8项自定义约定，均未取得本次游戏内实测证据。白垩之术溢出已收到用户回复：两个后台各扣1、出战封顶、允许溢出；下文“等待回复”已过时。

当前开发状态（2026-09-14）：五原生角色23牌、3v3随机合法30张、三组55场预检已完成，规则边界仍待用户实测。56独立D:/gicg_native（venv），旧D:/gicg_goal不动。预热run202609132004_000001：128局6471行、1000更新；D1开发67.27%、D2 43.64%。旧基线RL共12轮已完成，stream10660成功退出；pilot run202609132358_000002第1–4轮，extended run202609140018_000003第5–12轮。D2最好第2轮47.27%，第11/12轮44.55/45.45%，没有证明稳定优势。第2轮候选D1 70%；新开发seed93300预热/候选D2各440局为44.09/41.82%，无可靠RL收益。全部旧运行报告已拉回。

当前转向状态价值基线：本机已增加可选value_head、采集old_value、固定蒙特卡洛优势、独立价值优化器（不反传策略编码）、完整checkpoint/恢复；CLI新增--value-baseline及--opponent-depth。23相关测试通过，包含真实整局概率/价值批处理一致、梯度隔离、价值优化器恢复与验收器。一次整数奖励MSE反传错误已修float32；按CLAUDE重试规则由review_state_value独立只读复核，无阻断发现。旧任务结束后7文件定向同步56（含evaluate新scenario/max_game_steps元数据和verify_native_panel），源码再次冻结。冒烟stream43688已成功结束：run000004完成第1轮、run000005完整恢复完成第2轮，价值优化器步数6→14，所有值头参数有限；配置/身份/逐局报告经verify_native_panel实测核对，强度门槛未过是预期（2局流程测试）。报告已归档。新状态基线正式对照已启动stream74475，输出native_value_pilot_20260914，run为D:/gicg_native/artifacts/202609140052_000006_semantic_rl；从原预热step_1000全新起步，同旧seed93200、4轮×128局8workers、D2采集/开发seed93100。第一轮完成，D2开发36.36%、采样19.53%，value_loss0.7056。与旧控制第一轮128局/5878行逐项核对：行数、动作、奖励、old_logp完全一致，old_value全零；策略参数最大差约1.55e-4，但开发成绩相同，尚未专项确定数值差异来源。结果native_value_first_collection_parity_20260914.json和dev_1已归档。第2轮D2开发41.82%（旧控制第2轮47.27%），采样21.09%；继续第3–4轮。冻结old_value对下一轮真实回报的解释方差第2/3轮约5.07/8.84%，MSE0.674/0.593，低于滞后席位基线0.883/0.793，但尚未证明胜率收益；native_value_prediction_audit_20260914.json及dev_2已归档。源码冻结，不重复启动。三种子最终验收尚未启动，未达到目标。 最新：价值基线四轮已完成（stream74475退出），D2开发36.36/41.82/38.18/42.73%，没有优于预热；完整报告已拉回。现活动stream20778，输出native_temperature_pilot_20260914，run D:/gicg_native/artifacts/202609140107_000007_semantic_rl；同BC起点/状态基线/seed93200/4×128/8workers，仅temperature=0.5，首轮完成：采样28.125%（同起点T1为19.531%），D2开发42.73%（同轮T1为36.36%）；配对差+6.36pp、95%[-3.64,+16.36]pp，尚无确定优势。第二轮已完成：D2开发46.36%、采样27.34%，相对预热+2.73pp、配对95%[-8.18,+13.64]pp，仍无稳定优势。继续第3–4轮；采集审计、dev_1/2与配对结果已归档。若4轮保持改善，下一阶段优先扩大每轮新对局量，暂未启动。采集、更新与anchor KL统一除温度，参数存settings并守卫resume；评估仍argmax。25相关测试通过，旧任务结束后4文件定向同步，当前源码冻结。下一步比较采样胜率与D2开发，不凭低价值损失宣称强度提升。

最新补充（2026-09-14）：鸣神大社已接入，通用牌15/18、行动牌20/23。使用独立实例progress保存每回合已用次数；任意3费、打出当回合可用、奇数骰才触发、每张每回合2次、无3回合期限。双席位/两张依次重查奇偶/次数与跨回合、clone隔离及生产加载路径NN可见性测试通过。正式factory检查发现并修复reaction_kind缺编码token、菲谢尔多技能合并hook超过64寄存器（已按技能拆回调）；五角色全部10种三人镜像阵容、固定30张两份通用牌、静态和动态obs构建通过。这只是加载/表达准入证据，不等于组合规则或训练验收完成。支援obs行现带关联buff的值和progress，无rawID。剩余白垩（溢出问答未回复）、送你一程、一掷乾坤、满支援区替换、合法性审计和训练；未启动原生训练。

最新补充（2026-09-14）：派蒙已接入，当前通用牌14/18（行动牌19/23）。新增spawn_support_buff及SupportInst.BuffID内部关联，用独立buff保存每张支援的状态；实例内remove_support只移除关联支援，外部移除同步清效果。同名派蒙错开回合进入、产骰/各自到期、克隆隔离、checkpoint恢复及reset专项通过，完整Go引擎回归通过（后补checkpoint专项亦通过）。剩余鸣神大社、白垩之术、送你一程、一掷乾坤；支援满区替换与NN关联仍待补。白垩溢出边界已向用户异步询问：仅缺1能量且两个后台各有1时，是否仍各扣1并溢出1；未收到回答前不锁定该边界。以下“13通用牌/派蒙未实现”由本段取代，原生训练尚未开始。

最新（2026-09-14）：native_latest 已含五角色＋五天赋＋13张通用牌（18个行动牌文件）。本轮新增“本大爷还没有输！”及击倒条件/每回合限用测试，并为此前12张通用牌补专项：双方食物目标/饱腹、披萨后台治疗两次、莲花酥保留于穿透、普攻食物费用/次数/回合失效，切换牌跨回合保留/强制不消耗/主动消耗，鹤归技能后切换，抽牌/充能/万能骰。穿透组合测试覆盖增伤、减伤、护盾、免伤同时存在且效果不被消耗。剩余白垩之术、派蒙、鸣神大社、一掷乾坤、送你一程；还需合法打出条件逐条审计、支援独立实例/替换、选择与重投的NN表达、3v3/clone/reset准入及56新训练和D1/D2验收。当前尚未启动原生训练。下方进度段落均为历史，不代表最新完成范围。

最新进度：native_latest独立池已含五角色基础技能、寒冰之棱/火附魔/歌声之环/大型风灵/奥兹。原phase2仍为旧简化池。新增五角色定向测试与完整Go引擎回归通过。剩余5天赋＋18通用牌、召唤物选择/重投、3v3与NN准入和新训练。native池card目录目前为空，不能配置成正式训练。此前段落“角色未实现”已由本进度取代；完整批次仍未完成。

当前目标已由用户替换：完成第一批五原生角色＋23牌接入，并训练显著优于D1、稳定胜于D2。最新进展：扩散已补齐，支持四元素/双席位/连锁反应，纯附着扩散无伤害；新增on_after_reaction和ctx.reaction_element用于大型风灵转换。伤害管道不再把反应后最终伤害类型擦成None。完整Go包与新增定向测试通过。大型风灵和五角色/23牌仍未完成，尚未启动原生训练。

最新修复（2026-09-14）：冻结+1、物理碎冰、超导/感电主目标+1且仅原目标之外受穿透已改；新增apply_element独立纯附着入口和ctx.attachment_only，纯附着不走伤害管道、不生成反应附加伤害，冻结等非伤害效果保留；护盾全吸收的攻击照常结算附加伤害。结晶护盾上限2、只保护出战角色，并补原生反应主伤害+1。新回归测试与完整go test ./gicg_engine/...通过。五角色/23牌仍未完成，扩散尚待补齐。当前修改仅本机，56状态未成功复核（上次命令使用相对路径失败，纠正后的读取遇自动审批超时）；不声称已停止/重启远端。旧共享反应实现有误，其训练结果不再作为当前规则验收证据，严禁重标权重指纹。

第一批实施（2026-09-14）：用户授权开始五原生角色＋18通用牌＋5天赋。已选取并严格清洗28条最新源记录，修复 tools/cards HTML提前解码导致正文污染、为转换显式传入同快照 raw_list 路径；67项工具测试通过。已新增 force_switch_previous 原语（向前循环跳过阵亡、复用实际切换事件），注册执行器/Tokenizer/audit，并新增双席位三角色测试；Go interp/dsl/tests三个完整包通过。规则清单 `docs/3_plans/cards/native_first_batch_audit.md`，输入产物 `artifacts/native_first_batch/`。发现系统缺扩散/纯附着、冻结与超导感电语义不符原生，送你一程/一掷乾坤需要选择交互；角色和23牌尚未完成，不得宣称本批已可训练。新增本机源码未同步56，原教学运行继续使用其原源码快照；之后验证/迁移须核对指纹，不可改标签掩盖差异。

最新目标修订（2026-09-13）：用户明确只支持最新官方版本，不维护过时玩法。两个核心目的：为真实七圣召唤PvE逐决策提供胜率/评分建议，帮助更快完成关卡；争取形成论文。详 `docs/3_plans/pve_assistant_and_research.md`，优先于下方历史的“仅算法可学性研究”定位。最新资料抓取完成于 `artifacts/official_latest_20260913/`，当前教学训练不变。用户确认1秒响应和PvE攻略暂放长期，不进入当前开发。攻略候选形式为只用技能/切换，手牌仅调和、按可观察状态分支。用户提出建议1秒响应以及每关预计算、不依赖手牌的方案；已在产品路线补充计时边界、预算内基础建议/搜索、关卡条件策略与必胜验证边界，目前无真实3v3/PvE并行游戏延迟测试，不能承诺已满足。

当前状态（2026-09-13）：用户明确空出56 GPU并授权继续，**恢复训练已启动，活动stream13637**。新CUDA矩阵计算/稳定排序验证通过，旧000022 latest确认迭代9；`recover_curriculum`恢复模型/优化器/随机状态，从第10轮接到12轮，再执行三个最终种子及独立面板。总预算、种子、有效batch和算法不变。自动收尾新句柄 **67126**；早期L6最终策略审计新句柄 **16612**。原4817/59571/51800均已退出，不再使用。

原中断：L6第10轮CUDA unknown error，用户确认当时Lightroom占用显存并崩溃。前9轮权重与评估保留，旧失败目录不覆盖；根失败状态保存 `recovery_1/failed_master.json`。恢复记录在 `l6/rl_recovery_1`，前后完整轮次合并到 `recovery_1/combined_l6_rl.json` 后选最佳。恢复源码另存 `recovery_1/source.tar.gz`，11项相关测试通过。当前主状态以56 `artifacts/full_pool_curriculum/result.json` 为准。

- 用户目标：完整 L1–L6 共26种原牌加入，固定30张随机合法构筑、每种最多两张；五练习角色随机不重复2v2，稳定胜D1且优于D2。当前候选池另保留两个demo，所有原牌均保留。大规模计算全部在56。
- 已完成 L3：BC000015→RL000016第11轮，D2开发40.83%→53.33%。已完成 L4：BC000017→RL000018第9轮，59.17%→59.58%。这些是开发集选模结果，不能代替独立验收。L5全部完成：BC000019→RL000020第11轮，51.25%→65.00%；迁移候选240/240布局轨迹一致。
- 自动流程：每级1024局D2示范、8000 BC步、12×256对D2 RL；L6结束后，从同一最终迁移模型启动三个独立RL种子，各24×256局。三者全部冻结后，各720场景×双席位×双布局评估D1/D2，并检查四布局动作/支付一致性。
- 已诊断L5 RL第1轮1/240布局轨迹差异：float32近似并列舍入边界导致不同调和骰子，第2轮全部轨迹一致。记录 `l5/layout_case_1.json`；未改训练策略，最终候选一致性仍待验收。
- 用户新增原生内容分批规划：`docs/3_plans/cards/native_content_curriculum.md`，本次仅规划。实际资料138角色/507行动/61怪物；phase2仅7角色7牌且大量机制TODO，不是完整原生池。2026-09-14用户确定第一批凯亚、迪卢克、芭芭拉、砂糖、菲谢尔五角色一并接入，凝光后移；建议配18通用牌＋5天赋（牌单尚为建议）。同一五角色池先2v2验证再单独3v3验收，双方不再强制角色互斥。后续柯莱坎蒂丝、克洛琳德、玛薇卡逐批。用户已确认对齐官方版本。已找到 tools/cards/fetch.py 与 fetch_list.py（米游社百科当前接口，不支持指定历史版本；详情跳过已有文件）。最新要求只支持最新正式服。最新官方接口已全量抓取并核验：147角色、554行动、61魔物，共762条，零下载失败，目录/详情ID一致且无重复/空详情。相对旧资料角色新增9；行动新增48、缺失1（净增47，缺失需审核，不能直接视为删除）。manifest及逐文件SHA在 artifacts/official_latest_20260913/manifest.json；未完成新资料规则/清洗审计。转换器固定读取 data/raw_list 的限制也需在快照化时处理。当前训练保持不变。
- 用户明确将AlphaZero式纯RL列为长期方向：`docs/3_plans/pure_rl_long_term.md`。从随机初始化、无专家示范、无BC权重/经验、自我对弈为主；允许自我搜索目标，但须处理隐藏信息。当前BC+RL全池训练继续完成并作基准，尚未启动纯RL新任务。
- 用户要求逐卡价值量化方案，已提出“随机合法两卡位替换胜率差”和“全部合法机会的单动作时机价值”，详 `docs/3_plans/cards/card_value_evaluation.md`；仅方案落盘，全牌价值测量尚未执行，不能拿早期胜局选例代替无偏评分。
- 用户新增早期L6策略例子审计：`early_l6.py`，56活动stream **63740**，输出 `artifacts/early_l6_initial`，使用000022第1轮权重、4 workers。先搜240场景双侧的第1/2回合L6出牌，再最多每牌3例×32配对分支，区别出牌后获胜与单动作增益。最终BC/三个冻结候选同口径比较已排队，stream **16612**（`early_l6_followup`），等待主验收/逐卡覆盖完成后开始；不能仅靠早期基线声称RL学会。初始搜索480局发现乘胜7局/以攻8局/以逸3局前两回合出牌，以逸其中2局第1回合，3局均赢且D2选择不同，初始配对已完成，63740正常退出：乘胜场景121首回合24/32对11/32，早期以逸三例近乎无差异；详 `docs/5_history/early_l6_initial.md`。
- 自动收尾进程已在56启动，stream句柄 **67126**：`finalize_curriculum` 等待主流程结束，再复核独立强度并审计三个冻结候选；结果写 `finalization.json`。两项测试已通过。主流程失败时收尾退出报错，不重启训练；收尾完成后仍须拉回产物和审阅报告。
- 训练结束不等于目标完成：逐个独立候选D1/D2场景聚类95%下界均须超过50%；还需运行 `verify_curriculum`、冻结候选 `card_coverage`、拉回产物并写最终报告。若不达标继续诊断改进，不标目标完成。
- D2完整池480局逐卡参照已完成，`artifacts/full_pool_teacher_coverage.json`：26种牌均入组且见过，但三张天赋及以逸待劳从未使用。候选审计应区分入组、见过、合法机会和实际使用，不能要求无条件出每张牌。
- 详细协议和阶段记录：`docs/3_plans/cards/full_pool_curriculum.md`；当前生产源码指纹 `4a591c4993e2383100d958b0050283d3d94234224fe7d974a4bc73d59687d595`。训练运行中保持生产源码不变。
- 早前16张试验已完成但未达D2目标：RL对D1 59.86%、D2 32.36%，报告 `docs/5_history/semantic_duo_tactics.md`。旧小池全面评估RL对D1 78.06%、D2 56.11%，报告 `docs/5_history/semantic_duo_ladder.md`；不可混用为完整卡池成绩。
- 网页体验优化暂缓；本机8080服务此前使用旧指纹权重，后续接入新模型时需处理兼容性。以下保留的是历史状态，权重不可重标为当前环境。

56新源码目录D:/gicg_goal，配置configs/dmc/semantic_goal.toml；解释器D:/gicg_dev/.venv/Scripts/python.exe（新目录venv junction不可用，已移除）。当前生产指纹a1808181ec4bdc29749c5e7243ac5584a67c9ddb46b745cb592b578a7ce51abe；以下历史1v1权重指纹b3e84a0a399cb7e0958f540917abb2c473c72ca7aa7fa4b96eab65d4adfb15a2，不可直接加载。旧D:/gicg_dev保留历史兼容。BC run202609121729_000001_semantic_warmup/ckpts/latest.pt；首轮RL run202609121827_000004_semantic_rl/ckpts/iteration_7.pt为候选、latest.pt为第8轮恢复点。权重/配置/原始结果/源码归档已拉回。RL支持--resume，已验证优化器10→20步连续。

多RL种子复现已完成：固定BC，新增132000/133000/134000/135000，加原128000共5种子，均完成8×128预算。新holdout136000每模型2048局：BC81.05%，RL五种子82.62%–85.55%，平均84.26%；平均配对提升3.20个百分点，训练seed×场景双轴95%[+1.56,+5.08]；仅前瞻4新种子平均+3.08，95%[+1.37,+5.08]。四布局成绩均相同；stability137000合计11901次模型状态检查动作/支付100%一致。56 artifacts/semantic_rl_replication 全部任务正常结束，原始结果/候选/恢复点/配置/源码已留档，严格指纹/种子/轮数/SHA校验通过。详docs/5_history/semantic_rl_replication.md。此结论只适用于同一监督起点与当前池；下一步对手/任务迁移与不同BC初始化。历史复现任务已结束，dev未提交。 五练习角色1v1平衡评估已完成（artifacts/character_balance，23040局）：当前牌组D2赤蝶38.92%、墨客26.37%、猫咪56.45%、刻师傅82.91%、天星45.36%得分；刻师傅在两档策略/两牌组均强，天星D1仅15.04%说明策略依赖明显。10回合非镜像排名不变，猫咪镜像8回合平局48%；注意DSL第10回合同存活人数判首回合后手胜，猫咪镜像10回合仍有46/256局据此判胜。详docs/5_history/character_balance.md。未改数值。

> 编写日期:2026-08-10。项目最后活动 2026-06-12,已停工。
> **材料来源与可信度分级**:
> - **[代码]** = 从当前仓库代码/测试/git 直接验证,事实基准。
> - **[指令]** = 从用户指令时间线(3091 条,2026-04-10 ~ 06-12)推断的意图,带日期。
>   助手回复已被清理,**只知道作者要什么、否决了什么,不知道最终实现成什么样**。
> - **[记忆]** = `~/.claude/projects/-Users-redcontritio-Projects-gicg-mono/memory/`
>   下的 104 个 memory 文件(项目级私有笔记,`MEMORY.md` 是索引)。
> 代码与指令冲突时以代码为准,冲突本身在文中标注。

---

## 1. 项目是什么

GICG(Genius Invokation Card Game)用《原神》七圣召唤这个 **不完全信息 + 镜像纳什 + 大动作空间 + 长 horizon** 的卡牌游戏做 testbed,验证 RL / AZ / CFR / BC / DMC 等 paradigm 的 **可学性边界**。

**关键定位:这不是在训一个 SOTA agent,verdict 本身就是产出**(`openspec/project.md` §1)。作者在 2026-04-28 12:50 说得最直白:「我希望把这个工作全部完成 指**证明其 rl 不可解,或实现一个解法**,再考虑发表」。

**技术栈**(三层,数据流单向向上):

```
data/**/*.lua      Lua 语法子集 DSL — 全部游戏规则(角色/卡牌/系统)
      ↓ 自研解释器(gicg_engine/interp/,非 LuaJIT,无 cgo 桥)
gicg_engine/       Go 1.21+ 通用执行器(counter + hook 模型)
gicg_mcts/         Go MCTS / IS-MCTS / PUCT
      ↓ go build -buildmode=c-shared → libgicg.dylib
gicg_env/          Python 3.14 ctypes 绑定 + GicgEnv(gymnasium 风格)
      ↓
training/          core/(算法无关)+ paradigms/{az,ppo,cfr,dmc,bc}/
gicg_actor/        Go 侧 actor(I29,跨语言 N-subprocess 采样池)
tools/             运行/评测/数据清洗脚本(runs / eval / cards / dataset)
```

**规模**[代码]:267 commits,53 个活跃天。Python + Go 混合,全仓库有 pre-commit 强制的单文件行数上限(代码 300 行 / 测试 500 行 / docs 500 行)。

**完成度判断**:
- **基础设施:生产级,基本完工**。引擎、DSL、5 paradigm 统一管线、跨语言 actor 池、远程训练工具链、run 生命周期管理、OpenSpec 规约体系全部 ship 并有测试覆盖。
- **科研目标:未达成,且在停工前刚被重新定义**。5 个 paradigm 全部撞墙(详 §3.9),最好成绩是 BC 模仿学习 0.75 胜率(非 RL),纯 RL 最高 DMC run 150 的 5.1%。2026-06-11 作者把「学会」的判据从「胜率」改成「能发现 combo」,并放行搜索——**新方向零实现**。

---

## 2. 当前状态

### 2.1 git 状态 — 最重要的一条

[代码] **`main` 停在 `c87c73c`(2026-06-03)。6 月的工作分散在两个未合并的分支上,`main` 上看不到。**

| 分支 | 领先 main | 内容 | 状态 |
|---|---|---|---|
| **`i33-roundend-actor-ctx`**(当前 HEAD) | **3 commits** | 06-11 combo 审计的三项 fail-loud 修复(引擎 actor 帧 / topo loader / 显式牌组全链路) | **未合并** |
| **`i32-dmc-per`** | **6 commits** | 06-03~06-05 的 PER 实现 + γ<1 discounted MC return + `stage3_gamma99_resume.toml` | **未合并** |
| `i31-cfr-az-mp-pool-unification` | 33 commits | 已 squash 进 main(`b3d0922`) | 陈旧,可删 |
| `dev/maintenance-governance` | 3 commits | 已 squash 进 main(`c87c73c`) | 陈旧,可删 |

**关于 i33 的三个 commit**:内容是 2026-06-11/12 做的,但**提交动作发生在 2026-08-10 13:03-13:04**(即本交接文档编写当天,由仓库主人补提交)。在此之前这批改动一直以未提交的工作区形式存在了两个月。commit message 写得很完整(WHY + 逐文件清单 + 测试计数),可直接当变更说明读:

```
cdc3f8b  config/env: 牌组全链路显式化，消除静默截断
6542a52  engine: actor 视角解析改 fail-loud，修回合末友伤
1b69639  engine/dsl: topo loader 依赖不可解析改 fail-loud，复活以逸待劳
```

**仍未纳入版本控制的**:`_f4_probe_decks.py` / `_f4_verify_cfg_decks.py` / `_f4_verify_fixture_decks.py` 三个 F4 迁移验证探针。这是**刻意的** —— `cdc3f8b` 的 commit message 明写「探针依赖 /tmp 基线,属一次性工具,未纳入提交」。它们依赖 `/tmp/f4_probe_before.json`,该基线大概率已随系统清理消失,**现在已不可重跑**。

另有 3 个 git worktree 停在 `.claude/worktrees/`,各含一个 06-12 的未提交审计探针测试(详 §5.1)。**这三个 worktree 里的测试是唯一记录了 6 个已确认引擎 bug 的地方,不要清理掉。**

### 2.2 能不能跑 — 已实测

[代码] 2026-08-10 在本机(macOS / darwin-arm64 / go1.26.2 / Python 3.14.4 / torch 2.11.0)实测:

| 检查项 | 命令 | 结果 |
|---|---|---|
| Go 编译 | `go build ./...` | **PASS** |
| Go 全量测试 | `go test ./gicg_engine/...` | **全绿**(dsl / interp / interp-ir / tests / v2) |
| Python env 测试 | `.venv/bin/python -m pytest -n 4 gicg_env/tests/ -q` | **131 passed** |
| Python 训练层测试 | `.venv/bin/python -m pytest -n 4 training/tests/ -q` | **exit 0,无 failure**(约 1080 项,6 项 skip;进度条打到 100% 但汇总行未落盘,以 exit code 为准) |
| c-shared 库 | `gicg_env/libgicg.dylib` | 存在,构建于 2026-06-12 17:13(**已含未提交的引擎改动**) |

即:**未提交的工作区是自洽且全量测试通过的**,不是坏掉的中间态。注意这套测试是在非沙盒终端跑的——见 §5.5 关于 sandbox 假失败的说明。

### 2.3 标准命令

全部命令 **必须从 repo root 运行**,Python **必须用 `-m` 模块方式**(不变量 I7)。

```bash
# 构建
go build ./...
go build -buildmode=c-shared -o gicg_env/libgicg.dylib ./gicg_engine/capi/

# 测试
go test ./gicg_engine/tests/ -v -count=1
.venv/bin/python -m pytest -n 4 gicg_env/tests/ training/tests/ -q   # n=4 是甜点,再高会 oversubscribe
.venv/bin/python -m pytest -m smoke training/tests/ -q               # 5 paradigm 快速冒烟 ~5s
.venv/bin/python -m pytest -m smoke_full training/tests/ -q          # 真训练 100 步 + resume,25-50min,默认不收集

# 训练(单命令 atomic 全生命周期;remote cfg 会自动 sync + ssh 转发)
.venv/bin/python -m tools.runs.train configs/dmc/stage3_b_v_legacy.toml
.venv/bin/python -m tools.runs.train --resume artifacts/<dir>/ckpts/latest.pt <cfg>

# run 管理 / ckpt 检查 / 一次性启用 pre-commit hook
.venv/bin/python -m tools.runs.{list,show,mark,recover,sync}   # 详见 CLAUDE.md
.venv/bin/python -m tools.ckpt.info <path>.pt
git config core.hooksPath .githooks
```

### 2.4 功能完整度

| 子系统 | 状态 |
|---|---|
| Go 引擎 + counter/hook 模型 + 伤害管线 | **完整**,生产级 |
| Lua DSL 子集 + 自研解释器 + IR obs 编码 | **完整**,`gicg_engine/interp/ir/` |
| 卡池版本管理(ADR-0011) | **完整**,`data/pools/{test_basic,v_legacy,v_phase2,spike}/` |
| 5 paradigm 统一管线(core + paradigms) | **完整**,~92-95% 统一度 |
| Go actor 池(I29) | **DMC 完整**,AZ/PPO/CFR/BC 未 port(backlog I29-D3) |
| 远程训练工具链(tools/runs/) | **完整**,cfg 驱动,零手写 ssh |
| Web UI(`web/`) | 后端 + 前端可用,仅剩视觉打磨 [记忆 `project_web_ui_plan`] |
| **正式卡池录入(300+ 张真实卡)** | **未开始**,仅有 infra 与转换源调研 |
| **搜索 / ExIt 训练(06-11 新主线)** | **零实现** |

---

## 3. 架构与关键设计决策

这一节是全文最重要的部分。每条给出:**决策 / 为什么 / 否决过什么**。

### 3.1 引擎无知(Engine Ignorance)—— 第一立约


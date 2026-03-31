# 引擎设计完成标准

## 阶段划分

```
Phase 1: 核心引擎 (MVP)
Phase 2: RL 接口
Phase 3: 优化与验证
Phase 4: 生产就绪
```

## Phase 1: 核心引擎完成标准 ✅

### 1.1 基础数据结构
- [ ] `Side` 结构：3角色 + Counter Map + Mod 列表
- [ ] `Character` 结构：HP/Energy/Element
- [ ] `Counter` 系统：create/get/set/inc/dec
- [ ] `Mod` 系统：attach/trigger/执行
- [ ] `World` 状态：双方 Side + 当前回合/阶段

### 1.2 Lua 运行时
- [ ] Lua 沙箱封装
- [ ] 14个 API 绑定实现
- [ ] Counter 对象绑定 (UD + metatable)
- [ ] 预扫描器提取 Counter/Mod
- [ ] 脚本编译缓存

### 1.3 游戏循环
- [ ] 阶段管理 (投掷/行动/结束)
- [ ] 事件分发系统
- [ ] 伤害计算流程
- [ ] 元素反应系统
- [ ] Mod 触发执行

### 1.4 角色实现验证
至少实现3个角色验证架构：
- [ ] 菲谢尔 (召唤物)
- [ ] 迪卢克 (连击计数器)
- [ ] 阿蕾奇诺 (Token层数)

### 1.5 单元测试
- [ ] Counter 操作测试
- [ ] Mod 触发测试
- [ ] 伤害计算测试
- [ ] 元素反应测试
- [ ] 完整回合测试

**Phase 1 完成标志**: `go test ./...` 全通过，3个角色对局可正常运行

---

## Phase 2: RL 接口完成标准 🎯

### 2.1 C API 层
- [ ] `create_game()` / `destroy_game()`
- [ ] `reset(seed)`
- [ ] `step(action)` → (obs, reward, done, info)
- [ ] `get_valid_actions()` → mask
- [ ] `serialize()` / `deserialize()` (用于 MCTS)

### 2.2 观察值编码
- [ ] 基础状态向量 (HP/能量/附着等)
- [ ] Counter 状态编码
- [ ] 技能代码 tokenize
- [ ] Mod 代码 tokenize
- [ ] 固定维度输出 (batch 友好)

### 2.3 Python 绑定
- [ ] CFFI 绑定
- [ ] Gymnasium Env 包装
- [ ] Vectorized Env 支持 (多环境并行)

### 2.4 性能基准
- [ ] 单步执行 < 100μs (P0)
- [ ] 状态拷贝 < 500ns (P0)
- [ ] 观察值编码 < 10μs (P1)
- [ ] batch 128 环境 < 5ms/步 (P1)

### 2.5 集成测试
- [ ] Python 可调用 Go 引擎
- [ ] 观察值维度正确
- [ ] 动作掩码正确
- [ ] 多环境并行无竞态

**Phase 2 完成标志**: 
```python
env = GicgEnv()
obs, info = env.reset()
obs, reward, done, truncated, info = env.step(action)
# 以上运行无错误，且性能达标
```

---

## Phase 3: 优化与验证标准 🚀

### 3.1 压力测试
- [ ] 10万局随机对局无崩溃
- [ ] 内存使用稳定无泄漏
- [ ] 长时间运行性能不衰减

### 3.2 复杂角色支持
实现5个高难度角色验证扩展性：
- [ ] 芙宁娜 (双形态)
- [ ] 玛薇卡 (夜魂机制)
- [ ] 莫娜 (被动触发)
- [ ] 甘雨 (多目标)
- [ ] 一个自定义角色

### 3.3 特征验证
- [ ] 技能代码 token 可被网络学习
- [ ] Mod 逻辑可被网络理解
- [ ] 观察值包含足够决策信息

### 3.4 工具链
- [ ] 技能调试工具
- [ ] 对局回放功能
- [ ] 性能分析工具

**Phase 3 完成标志**: 
- 5个复杂角色完整实现
- 随机 AI 可完成完整对局
- 性能测试报告通过

---

## Phase 4: 生产就绪标准 🏁

### 4.1 文档
- [ ] API 文档完整
- [ ] 角色开发指南
- [ ] 性能调优指南
- [ ] 部署文档

### 4.2 可观测性
- [ ] 日志系统
- [ ] 指标收集 (prometheus)
- [ ] 错误追踪

### 4.3 稳定性
- [ ] 异常处理完善
- [ ] 输入验证严格
- [ ] 资源限制保护

### 4.4 CI/CD
- [ ] 自动化测试
- [ ] 性能回归测试
- [ ] 多平台构建

**Phase 4 完成标志**: 可交付给 ML 工程师训练模型

---

## 当前阶段: Phase 1

### 本周目标 (3-4天)
1. 完成基础数据结构
2. 实现 Lua 运行时 + API
3. 实现菲谢尔角色
4. 跑通单回合测试

### 验收测试用例
```go
// Test: 菲谢尔完整回合
func TestFischlTurn(t *testing.T) {
    world := NewWorld()
    world.LoadCharacter("fischl", 0)
    world.LoadCharacter("dummy", 1)
    
    // 使用 E 技能
    world.ExecuteSkill(0, "fischl_e")
    
    // 验证：奥兹 Counter = 2
    assert.Equal(t, 2, world.Sides[0].GetCounter("fischl_oz_uses"))
    
    // 进入结束阶段
    world.EndPhase()
    
    // 验证：敌方受到 1 点雷伤
    assert.Equal(t, 9, world.Sides[1].Characters[0].HP)
    
    // 验证：奥兹 Counter = 1
    assert.Equal(t, 1, world.Sides[0].GetCounter("fischl_oz_uses"))
}
```

### 完成检查点
- [ ] `go test -v ./...` 全绿
- [ ] `go run cmd/test_game/main.go` 可运行演示对局
- [ ] 代码 Review 通过

---

## 进度追踪

| 阶段 | 状态 | 预计时间 | 实际时间 |
|------|------|----------|----------|
| Phase 1 | 🔄 进行中 | 3-4天 | - |
| Phase 2 | ⏳ 待开始 | 2-3天 | - |
| Phase 3 | ⏳ 待开始 | 3-4天 | - |
| Phase 4 | ⏳ 待开始 | 2-3天 | - |

**总计**: 约 2 周完成核心可用版本

# CS:GO FPS 游戏 - 核心方案设计

## 当前进度状态
- ✅ 第一步：核心机制与范围定义
- ✅ 第二步：项目结构设置
- ✅ 第三步：实现玩家控制器
- ✅ 第四步：设计武器系统
- 🔄 **第五步：构建经济与回合逻辑（进行中）**

---

## 第五步核心方案设计

### 一、回合管理系统 (RoundManager.cs)

#### 1. 核心职责
- 控制回合计时器（标准 1 分 55 秒）
- 管理回合状态（准备中、进行中、结算中）
- 判定回合胜负条件
- 触发回合开始/结束事件

#### 2. 关键属性
```csharp
- float roundTime = 115f; // 1 分 55 秒
- float currentRoundTime;
- int currentRound = 1;
- int maxRounds = 24; // 先赢 13 局
- RoundState currentState; // enum: Preparing, Playing, Settling
- Team winningTeam; // enum: Terrorist, CounterTerrorist, None
```

#### 3. 核心方法
- `StartRound()`: 重置计时器，通知所有玩家准备
- `Update()`: 每帧更新计时器
- `EndRound(Team winner)`: 结算回合，触发经济系统
- `CheckWinCondition()`: 检查是否达到 13 胜

#### 4. 胜负判定逻辑
- **T 方胜利条件**:
  - 安放 C4 并成功爆炸
  - 歼灭所有 CT 玩家
  - CT 方未在规定时间内拆除 C4
  
- **CT 方胜利条件**:
  - 拆除 C4
  - 歼灭所有 T 玩家
  - 在规定时间内阻止 T 方安包

---

### 二、经济系统完善 (EconomySystem.cs)

#### 1. 核心职责
- 管理每队/每名玩家的经济
- 计算回合结束后的奖金
- 处理购买物品的扣款
- 实现失败奖金递增机制

#### 2. 关键属性
```csharp
- Dictionary<Player, int> playerMoney; // 玩家资金
- Dictionary<Team, int> consecutiveLosses; // 连续失败次数
- int baseLossBonus = 1400; // 基础失败奖金
- int lossBonusIncrement = 500; // 失败奖金递增
- int maxLossBonus = 3400; // 最高失败奖金
```

#### 3. 奖金计算规则
- **失败奖金**: `min(baseLossBonus + (consecutiveLosses * 500), 3400)`
- **胜利奖金**:
  - 歼灭敌人/超时未安包：3250
  - 拆除 C4:3500（拆除者额外 +300）
  - C4 爆炸胜利：3500（下包者额外 +300）

#### 4. 核心方法
- `CalculateEndRoundBonus(Team team, RoundResult result)`: 计算奖金
- `AddMoney(Player player, int amount)`: 增加资金
- `SpendMoney(Player player, int cost)`: 扣除资金
- `ResetConsecutiveLosses(Team team)`: 重置失败计数

---

### 三、购买菜单系统 (BuyMenu.cs)

#### 1. 核心职责
- 显示可购买物品列表
- 处理玩家购买操作
- 更新 UI 显示（价格、可用资金）
- 与武器系统联动

#### 2. UI 组件
- 当前资金显示
- 武器分类选项卡（手枪、步枪、狙击枪）
- 物品列表（图标、名称、价格）
- 购买按钮（每个物品）
- 确认/取消按钮

#### 3. 可购买物品分类
```csharp
// 手枪类
- Glock18 (T 方): $200
- Deagle: $500

// 步枪类
- AK47 (T 方): $2700
- M4A4 (CT 方): $3100
- M4A1-S (CT 方): $2900

// 护甲类
- 防弹衣：$650
- 防弹衣 + 头盔：$1000

// 弹药补给
- 步枪弹药包：$400
```

#### 4. 核心方法
- `OpenMenu(Player player)`: 打开购买菜单
- `CloseMenu()`: 关闭菜单
- `BuyItem(Player player, ItemType item)`: 购买物品
- `UpdateUI(Player player)`: 更新 UI 显示

---

### 四、游戏管理器 (GameManager.cs)

#### 1. 核心职责
- 整合所有系统（回合、经济、玩家、武器）
- 管理游戏流程（准备→开始→进行→结算）
- 处理游戏事件和状态转换
- 协调各模块间的数据传递

#### 2. 游戏状态机
```csharp
enum GameState {
    Lobby,      // 大厅准备
    PreRound,   // 回合前准备（购买阶段）
    InRound,    // 回合进行中
    EndRound,   // 回合结算
    GameOver    // 游戏结束
}
```

#### 3. 核心方法
- `StartGame()`: 开始新游戏
- `StartNewRound()`: 开始新回合
- `TransitionToNextState(GameState state)`: 状态转换
- `EndGame(Team winner)`: 游戏结束处理

#### 4. 系统整合流程
```
游戏开始
  ↓
准备回合 (PreRound)
  ↓ 触发经济系统分配初始资金
打开购买菜单 (30 秒购买时间)
  ↓ 玩家购买武器/护甲
开始回合 (InRound)
  ↓ 玩家重生，回合计时器启动
回合进行中...
  ↓ 触发胜负条件
结算回合 (EndRound)
  ↓ 经济系统计算奖金
准备下一回合
```

---

### 五、爆点与 C4 系统设计方案

#### 1. 爆点系统 (BombSite.cs)

**核心职责**:
- 标记 A/B 爆点区域
- 检测玩家是否进入爆点范围
- 处理安包/拆包事件

**关键属性**:
```csharp
- Vector3 siteCenter; // 爆点中心位置
- float siteRadius = 5f; // 爆点半径
- string siteName; // "A" 或 "B"
- bool isBombPlanted; // 是否已安包
```

**核心方法**:
- `PlayerEnterBombSite(Player player)`: 玩家进入爆点
- `PlayerExitBombSite(Player player)`: 玩家离开爆点
- `PlantBomb(C4Bomb bomb)`: 安放炸弹
- `DefuseBomb(Player player)`: 拆除炸弹

#### 2. C4 炸弹 (C4Bomb.cs)

**核心职责**:
- 管理 C4 炸弹状态
- 处理安包/拆包逻辑
- 倒计时爆炸机制

**关键属性**:
```csharp
- bool isPlanted; // 是否已安放
- float bombTimer = 40f; // 倒计时 40 秒
- Player planter; // 安放者
- BombSite currentSite; // 当前所在爆点
```

**核心方法**:
- `PlantBomb(Player player, BombSite site)`: 安放炸弹
- `StartTimer()`: 开始倒计时
- `DefuseBomb(Player player)`: 拆除炸弹
- `Explode()`: 炸弹爆炸

---

### 六、模块依赖关系图

```
GameManager (总控)
  ├── RoundManager (回合管理)
  │     ├── 回合计时器
  │     ├── 胜负判定
  │     └── 状态转换
  │
  ├── EconomySystem (经济系统)
  │     ├── 资金管理
  │     ├── 奖金计算
  │     └── 购买扣款
  │
  ├── PlayerController (玩家系统)
  │     ├── Movement (移动)
  │     ├── Shooting (射击)
  │     └── PlayerHealth (健康)
  │
  ├── WeaponManager (武器系统)
  │     ├── 武器切换
  │     └── 弹药管理
  │
  ├── BuyMenu (购买菜单)
  │     └── UI 交互
  │
  └── BombSite + C4Bomb (爆点系统)
        ├── 安包逻辑
        └── 拆包逻辑
```

---

### 七、数据流设计

#### 1. 回合开始数据流
```
GameManager.StartNewRound()
  → RoundManager.StartRound()
  → EconomySystem.ResetRoundEconomy()
  → PlayerController.SpawnPlayers()
  → BuyMenu.OpenMenu()
```

#### 2. 购买物品数据流
```
Player clicks BuyButton
  → BuyMenu.BuyItem(player, item)
  → EconomySystem.SpendMoney(player, cost)
  → WeaponManager.EquipWeapon(player, weapon)
  → UI 更新显示
```

#### 3. 回合结算数据流
```
RoundManager.EndRound(winner)
  → EconomySystem.CalculateBonus(team, result)
  → GameManager.UpdateScore(winner)
  → GameManager.CheckGameOver()
  → UI 显示结算信息
```

---

### 八、下一步实施计划

#### 优先级 1: 核心系统搭建
1. 创建 `RoundManager.cs` - 回合计时器和状态管理
2. 完善 `EconomySystem.cs` - 奖金计算和资金管理
3. 创建 `GameManager.cs` - 整合所有系统

#### 优先级 2: 购买系统实现
4. 完善 `BuyMenu.cs` - UI 界面和购买逻辑
5. 连接经济系统与武器系统

#### 优先级 3: 爆点系统实现
6. 创建 `BombSite.cs` 和 `C4Bomb.cs`
7. 实现安包/拆包机制

#### 优先级 4: 测试与调优
8. 单元测试各模块
9. 整合测试完整游戏循环
10. 参数调优（时间、金钱、武器平衡）

---

*文档创建时间：核心方案设计阶段*
*下一步：开始实施优先级 1 的核心系统*

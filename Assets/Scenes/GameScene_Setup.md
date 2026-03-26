# 游戏场景设置指南

## 场景对象层级结构

```
GameManager (Singleton)
├── RoundManager
├── EconomySystem
└── BuyMenu

Map
├── BombSite_A
│   └── C4Bomb (Prefab)
└── BombSite_B
    └── C4Bomb (Prefab)

Players
├── Player_T_1
│   ├── CharacterController
│   ├── PlayerController
│   ├── Movement
│   ├── Shooting
│   ├── PlayerHealth
│   └── Weapon (AK47/M4A4 等)
├── Player_T_2
├── ...
└── Player_CT_5

Camera (Main Camera)
```

## 组件配置步骤

### 1. GameManager 设置
- 创建空物体命名为 "GameManager"
- 添加 GameManager 组件
- 设置 maxRounds = 13
- 设置 roundTime = 115
- 拖拽 RoundManager 和 EconomySystem 到引用字段

### 2. RoundManager 设置
- 创建空物体命名为 "RoundManager"
- 添加 RoundManager 组件
- 设置 standardRoundTime = 115
- 设置 buyTime = 15
- 拖拽 GameManager 和 EconomySystem 到引用字段

### 3. EconomySystem 设置
- 创建空物体命名为 "EconomySystem"
- 添加 EconomySystem 组件
- 配置经济参数（起始资金、奖金等）

### 4. 爆点设置
- 创建空物体命名为 "BombSite_A" 和 "BombSite_B"
- 添加 BombSite 组件
- 设置 siteName 为 "A" 或 "B"
- 设置 siteRadius = 5
- 设置 playerLayer 为玩家层
- 在爆点中心放置 C4Bomb Prefab

### 5. 玩家设置
- 创建玩家物体，添加以下组件：
  - CharacterController
  - PlayerController
  - Movement
  - Shooting
  - PlayerHealth
  - Weapon (选择具体武器)
- 设置 PlayerHealth 的 playerId (1-10)
- 设置 PlayerController 的移动参数

## 游戏循环验证

### 回合开始
1. GameManager.StartNewGame() 被调用
2. GameManager 调用 RoundManager.StartRound()
3. RoundManager 开始购买阶段倒计时 (15 秒)
4. EconomySystem.ResetRoundEconomy() 为所有玩家分配资金

### 购买阶段
1. 玩家可以打开 BuyMenu 购买武器和护甲
2. 购买时调用 EconomySystem.TryBuyItem()
3. 资金不足时购买失败

### 游戏阶段
1. 购买阶段结束后，RoundManager 进入 Playing 状态
2. 玩家开始移动、射击
3. 武器 Fire() 方法触发射线检测
4. 击中 PlayerHealth 时调用 TakeDamage()
5. 玩家死亡时触发 OnPlayerKilled 事件
6. EconomySystem 监听击杀事件并分配击杀奖金

### 回合结束
1. 时间耗尽或一方全灭时，调用 RoundManager.EndRound(winner)
2. RoundManager 通知 GameManager.EndRound(winner)
3. GameManager 更新比分并调用 EconomySystem.EndRoundSettlement()
4. EconomySystem 为获胜方分配胜利奖金
5. 等待 5 秒后自动开始下一回合

## 调试检查点

- [ ] GameManager 正确初始化，roundManager 和 economySystem 引用正确
- [ ] RoundManager 倒计时正常，购买阶段和游戏阶段切换正常
- [ ] EconomySystem 正确分配初始资金和失败奖金
- [ ] 玩家移动正常，反身移动和急停有效
- [ ] 武器射击正常，后坐力系统工作
- [ ] 玩家死亡时经济系统正确分配击杀奖金
- [ ] 回合结束时经济系统正确分配胜利奖金
- [ ] 爆点系统正常工作，C4 炸弹可以放置和拆除
- [ ] 游戏结束判定正确

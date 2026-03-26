# CS:GO 风格 FPS 游戏

## 项目概述
基于 Unity 引擎开发的 3D 第一人称射击游戏，实现 CS:GO 的核心机制。

## 核心特性
- **经济系统**: 失败奖金递增、胜利奖励、ECO 局策略
- **移动机制**: 反身移动 (Counter-strafing)、移动速度与声音关系
- **枪械机制**: 喷射模式 (Spray Patterns)、后坐力补偿

## 项目结构
```
/workspace/repo/
├── README.md
├── ProjectSettings/
│   └── settings.json
├── Scripts/
│   ├── Player/
│   │   ├── PlayerController.cs
│   │   └── PlayerMovement.cs
│   ├── Weapons/
│   │   ├── WeaponBase.cs
│   │   ├── WeaponData.cs
│   │   └── WeaponManager.cs
│   └── GameManager/
│       ├── GameManager.cs
│       └── EconomySystem.cs
└── CS_GO_Mechanics_Research.md
```

## 开发状态
- [x] 步骤 1: CS:GO 核心机制研究
- [ ] 步骤 2: 游戏项目初始化 (进行中)
- [ ] 步骤 3: 核心玩法实现
- [ ] 步骤 4: 经济和回合系统

## 技术栈
- 游戏引擎：Unity 2022 LTS
- 编程语言：C#
- 渲染管线：URP (Universal Render Pipeline)

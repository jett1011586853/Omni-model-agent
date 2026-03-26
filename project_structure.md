# CS:GO 风格 FPS 游戏 - 项目结构

## 引擎选择：Unity

选择 Unity 作为游戏引擎，因其强大的 FPS 模板和广泛的资源市场支持。

## 文件夹结构

```
/CS_GO_Game/
├── Assets/
│   ├── Animations/
│   │   ├── Player/
│   │   │   ├── Idle.fbx
│   │   │   ├── Walk.fbx
│   │   │   ├── Run.fbx
│   │   │   ├── Shoot.fbx
│   │   │   └── Reload.fbx
│   │   └── Weapons/
│   │       ├── AK47/
│   │       │   ├── Fire.fbx
│   │       │   └── Reload.fbx
│   │       └── M4A4/
│   │           ├── Fire.fbx
│   │           └── Reload.fbx
│   ├── Materials/
│   │   ├── Player/
│   │   ├── Weapons/
│   │   ├── Map/
│   │   └── UI/
│   ├── Models/
│   │   ├── Characters/
│   │   │   ├── CT_Soldier.fbx
│   │   │   └── T_Terrorist.fbx
│   │   ├── Weapons/
│   │   │   ├── AK47.fbx
│   │   │   ├── M4A4.fbx
│   │   │   ├── M4A1_S.fbx
│   │   │   └── Deagle.fbx
│   │   └── Map/
│   │       ├── Props/
│   │       ├── Barriers/
│   │       └── C4_Bomb.fbx
│   ├── Prefabs/
│   │   ├── Player/
│   │   │   ├── CT_Player.prefab
│   │   │   └── T_Player.prefab
│   │   ├── Weapons/
│   │   │   ├── AK47.prefab
│   │   │   ├── M4A4.prefab
│   │   │   └── Deagle.prefab
│   │   ├── Map/
│   │   │   └── Props/
│   │   └── UI/
│   │       ├── Crosshair.prefab
│   │       ├── AmmoCounter.prefab
│   │       └── RoundTimer.prefab
│   ├── Scenes/
│   │   ├── MainMenu.unity
│   │   ├── Game.unity
│   │   └── Prototype_Map.unity
│   ├── Scripts/
│   │   ├── Core/
│   │   │   ├── GameManager.cs
│   │   │   ├── RoundManager.cs
│   │   │   └── EconomySystem.cs
│   │   ├── Player/
│   │   │   ├── PlayerController.cs
│   │   │   ├── Movement.cs
│   │   │   ├── Shooting.cs
│   │   │   └── PlayerHealth.cs
│   │   ├── Weapons/
│   │   │   ├── WeaponBase.cs
│   │   │   ├── AK47.cs
│   │   │   ├── M4A4.cs
│   │   │   └── WeaponManager.cs
│   │   ├── Map/
│   │   │   ├── BombSite.cs
│   │   │   └── C4Bomb.cs
│   │   ├── UI/
│   │   │   ├── Crosshair.cs
│   │   │   ├── AmmoHUD.cs
│   │   │   ├── RoundHUD.cs
│   │   │   └── BuyMenu.cs
│   │   └── Utilities/
│   │       ├── SoundManager.cs
│   │       └── DataManager.cs
│   ├── Audio/
│   │   ├── Weapons/
│   │   │   ├── AK47_Fire.wav
│   │   │   ├── M4A4_Fire.wav
│   │   │   └── Reload.wav
│   │   ├── Player/
│   │   │   ├── Footsteps_Run.wav
│   │   │   ├── Footsteps_Walk.wav
│   │   │   └── Jump.wav
│   │   ├── UI/
│   │   │   ├── Select.wav
│   │   │   └── Confirm.wav
│   │   └── Ambience/
│   │       └── Map_Ambience.wav
│   ├── Textures/
│   │   ├── Player/
│   │   ├── Weapons/
│   │   ├── Map/
│   │   └── UI/
│   └── Settings/
│       ├── ProjectSettings.asset
│       └── QualitySettings.asset
├── Packages/
│   └── manifest.json
├── ProjectSettings/
│   ├── AudioManager.asset
│   ├── ClusterInputManager.asset
│   ├── DynamicsManager.asset
│   ├── EditorBuildSettings.asset
│   ├── EditorSettings.asset
│   ├── GraphicsSettings.asset
│   ├── InputManager.asset
│   ├── NavMeshAreas.asset
│   ├── NetworkManager.asset
│   ├── Physics2DSettings.asset
│   ├── PhysicsMaterialDatabase.asset
│   ├── PresetManager.asset
│   ├── ProjectSettings.asset
│   ├── ProjectVersion.txt
│   ├── QualitySettings.asset
│   ├── TagManager.asset
│   ├── TimeManager.asset
│   ├── UnityConnectSettings.asset
│   └── VFXManager.asset
└── UserSettings/
    └── EditorUserSettings.asset
```

## 关键组件说明

### 1. 核心系统 (Core)
- **GameManager**: 管理游戏状态、回合开始/结束
- **RoundManager**: 控制回合时间、胜负判定
- **EconomySystem**: 处理金钱系统、购买逻辑

### 2. 玩家系统 (Player)
- **PlayerController**: 主控制器，整合移动、射击、交互
- **Movement**: 实现反身移动、急停、跳跃
- **Shooting**: 处理射击逻辑、后坐力
- **PlayerHealth**: 生命值管理、死亡处理

### 3. 武器系统 (Weapons)
- **WeaponBase**: 武器基类，定义通用属性
- **AK47/M4A4**: 具体武器实现，包含独特喷射模式
- **WeaponManager**: 武器切换、弹药管理

### 4. 地图系统 (Map)
- **BombSite**: A/B 爆点逻辑
- **C4Bomb**: C4 炸弹放置与拆除

### 5. UI 系统
- **Crosshair**: 准星显示
- **AmmoHUD**: 弹药显示
- **RoundHUD**: 回合信息显示
- **BuyMenu**: 购买菜单

## 下一步行动
1. 在 Unity 中创建新项目
2. 按照上述结构创建文件夹
3. 创建基础场景 (Prototype_Map.unity)
4. 实现核心脚本框架

---
*创建日期：项目结构设置阶段*
*状态：结构已定义，待实施*

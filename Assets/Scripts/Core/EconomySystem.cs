using UnityEngine;
using System.Collections.Generic;

/// <summary>
/// EconomySystem - 经济系统
/// 管理玩家的金钱、购买和奖金
/// </summary>
public class EconomySystem : MonoBehaviour
{
    [Header("经济设置")]
    [SerializeField] private int tStartingMoney = 800;
    [SerializeField] private int ctStartingMoney = 800;
    [SerializeField] private int firstRoundBonus = 1400;
    [SerializeField] private int maxBonus = 3400;
    [SerializeField] private int bonusIncrement = 500;
    
    [Header("胜利奖金")]
    [SerializeField] private int winByElimination = 3250;
    [SerializeField] private int winByBomb = 3500;
    [SerializeField] private int bombPlanterBonus = 300;
    [SerializeField] private int bombDefuserBonus = 300;
    
    // 玩家经济数据
    private Dictionary<int, PlayerEconomy> playerEconomies;
    private int currentRound;
    private int consecutiveLosses = 0;
    
    private void Start()
    {
        playerEconomies = new Dictionary<int, PlayerEconomy>();
        currentRound = 0;
        consecutiveLosses = 0;
    }
    
    /// <summary>
    /// 重置回合经济
    /// </summary>
    public void ResetRoundEconomy(int round)
    {
        currentRound = round;
        
        // 计算失败奖金
        int failureBonus = CalculateFailureBonus();
        
        // 为所有玩家分配初始资金或失败奖金
        foreach (var playerEconomy in playerEconomies.Values)
        {
            if (round == 1)
            {
                // 第一回合使用起始资金
                playerEconomy.money = playerEconomy.isT ? tStartingMoney : ctStartingMoney;
            }
            else
            {
                // 后续回合使用失败奖金
                playerEconomy.money = failureBonus;
            }
        }
        
        Debug.Log($"第 {round} 回合开始，失败奖金：${failureBonus}");
    }
    
    /// <summary>
    /// 计算失败奖金
    /// </summary>
    private int CalculateFailureBonus()
    {
        int bonus = firstRoundBonus + (consecutiveLosses * bonusIncrement);
        return Mathf.Min(bonus, maxBonus);
    }
    
    /// <summary>
    /// 添加新玩家
    /// </summary>
    public void AddPlayer(int playerId, bool isT)
    {
        if (!playerEconomies.ContainsKey(playerId))
        {
            playerEconomies[playerId] = new PlayerEconomy
            {
                playerId = playerId,
                isT = isT,
                money = isT ? tStartingMoney : ctStartingMoney
            };
        }
    }
    
    /// <summary>
    /// 玩家死亡
    /// </summary>
    public void OnPlayerDeath(int playerId, int killerId)
    {
        if (playerEconomies.ContainsKey(playerId))
        {
            PlayerEconomy economy = playerEconomies[playerId];
            
            // 如果击杀了敌人，击杀者获得奖金
            if (killerId > 0 && playerEconomies.ContainsKey(killerId))
            {
                playerEconomies[killerId].money += 300; // 击杀奖金
                Debug.Log($"玩家 {killerId} 击杀玩家 {playerId}，获得 $300");
            }
        }
    }
    
    /// <summary>
    /// 回合结束结算
    /// </summary>
    /// <param name="winner">获胜方，0=T 方，1=CT 方</param>
    public void EndRoundSettlement(int winner)
    {
        if (winner == 0)
        {
            // T 方获胜，CT 方连续失败数 +1
            consecutiveLosses++;
            
            // 为 T 方玩家添加胜利奖金
            foreach (var economy in playerEconomies.Values)
            {
                if (economy.isT)
                {
                    economy.money += winByElimination;
                }
            }
        }
        else
        {
            // CT 方获胜，T 方连续失败数 +1
            consecutiveLosses++;
            
            // 为 CT 方玩家添加胜利奖金
            foreach (var economy in playerEconomies.Values)
            {
                if (!economy.isT)
                {
                    economy.money += winByElimination;
                }
            }
        }
        
        Debug.Log($"回合结束，{winner == 0 ? "T 方" : "CT 方"} 获胜，连续失败数：{consecutiveLosses}");
    }
    
    /// <summary>
    /// 玩家购买物品
    /// </summary>
    public bool TryBuyItem(int playerId, int cost)
    {
        if (playerEconomies.ContainsKey(playerId))
        {
            PlayerEconomy economy = playerEconomies[playerId];
            
            if (economy.money >= cost)
            {
                economy.money -= cost;
                Debug.Log($"玩家 {playerId} 购买物品，花费 ${cost}，剩余 ${economy.money}");
                return true;
            }
            else
            {
                Debug.Log($"玩家 {playerId} 资金不足，需要 ${cost}，只有 ${economy.money}");
                return false;
            }
        }
        return false;
    }
    
    /// <summary>
    /// 获取玩家资金
    /// </summary>
    public int GetPlayerMoney(int playerId)
    {
        if (playerEconomies.ContainsKey(playerId))
        {
            return playerEconomies[playerId].money;
        }
        return 0;
    }
    
    /// <summary>
    /// 添加下包者奖金
    /// </summary>
    public void AddBombPlanterBonus(int playerId)
    {
        if (playerEconomies.ContainsKey(playerId))
        {
            playerEconomies[playerId].money += bombPlanterBonus;
            Debug.Log($"玩家 {playerId} 获得下包奖金 ${bombPlanterBonus}");
        }
    }
    
    /// <summary>
    /// 添加拆包者奖金
    /// </summary>
    public void AddBombDefuserBonus(int playerId)
    {
        if (playerEconomies.ContainsKey(playerId))
        {
            playerEconomies[playerId].money += bombDefuserBonus;
            Debug.Log($"玩家 {playerId} 获得拆包奖金 ${bombDefuserBonus}");
        }
    }
    
    /// <summary>
    /// 重置连续失败计数
    /// </summary>
    public void ResetConsecutiveLosses()
    {
        consecutiveLosses = 0;
        Debug.Log("连续失败计数已重置");
    }
    
    // 玩家经济数据类
    [System.Serializable]
    private class PlayerEconomy
    {
        public int playerId;
        public bool isT;
        public int money;
    }
}

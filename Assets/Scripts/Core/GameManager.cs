using UnityEngine;
using System.Collections;

/// <summary>
/// GameManager - 管理游戏全局状态
/// </summary>
public class GameManager : MonoBehaviour
{
    [Header("游戏设置")]
    [SerializeField] private int maxRounds = 13;
    [SerializeField] private float roundTime = 115f; // 1 分 55 秒
    
    [Header("引用")]
    [SerializeField] private RoundManager roundManager;
    [SerializeField] private EconomySystem economySystem;
    
    // 游戏状态
    public enum GameState
    {
        Waiting,
        InRound,
        RoundEnd,
        GameEnd
    }
    
    public GameState currentState { get; private set; }
    public int currentRound { get; private set; }
    public int tScore { get; private set; }
    public int ctScore { get; private set; }
    
    private void Start()
    {
        currentState = GameState.Waiting;
        currentRound = 0;
        tScore = 0;
        ctScore = 0;
        
        if (roundManager == null)
        {
            Debug.LogWarning("RoundManager 未设置，将自动查找");
            roundManager = FindObjectOfType<RoundManager>();
        }
        
        if (economySystem == null)
        {
            Debug.LogWarning("EconomySystem 未设置，将自动查找");
            economySystem = FindObjectOfType<EconomySystem>();
        }
    }
    
    /// <summary>
    /// 开始新游戏
    /// </summary>
    public void StartNewGame()
    {
        currentRound = 0;
        tScore = 0;
        ctScore = 0;
        currentState = GameState.InRound;
        
        StartNextRound();
    }
    
    /// <summary>
    /// 开始下一回合
    /// </summary>
    public void StartNextRound()
    {
        currentRound++;
        currentState = GameState.InRound;
        
        if (roundManager != null)
        {
            roundManager.StartRound(currentRound, roundTime);
        }
        
        if (economySystem != null)
        {
            economySystem.ResetRoundEconomy(currentRound);
        }
        
        Debug.Log($"开始第 {currentRound} 回合");
    }
    
    /// <summary>
    /// 回合结束
    /// </summary>
    /// <param name="winner">获胜方，0=T 方，1=CT 方</param>
    public void EndRound(int winner)
    {
        currentState = GameState.RoundEnd;
        
        if (winner == 0)
        {
            tScore++;
            Debug.Log("T 方获胜");
        }
        else
        {
            ctScore++;
            Debug.Log("CT 方获胜");
        }
        
        // 调用经济系统结算
        if (economySystem != null)
        {
            economySystem.EndRoundSettlement(winner);
        }
        
        CheckGameEnd();
    }
    
    /// <summary>
    /// 检查游戏是否结束
    /// </summary>
    private void CheckGameEnd()
    {
        if (tScore >= maxRounds || ctScore >= maxRounds || currentRound >= maxRounds * 2)
        {
            currentState = GameState.GameEnd;
            
            if (tScore > ctScore)
            {
                Debug.Log("游戏结束：T 方获胜!");
            }
            else if (ctScore > tScore)
            {
                Debug.Log("游戏结束：CT 方获胜!");
            }
            else
            {
                Debug.Log("游戏结束：平局!");
            }
        }
    }
    
    /// <summary>
    /// 获取获胜方 (用于 UI 显示)
    /// </summary>
    public string GetWinner()
    {
        if (tScore > ctScore) return "T 方 (恐怖分子)";
        if (ctScore > tScore) return "CT 方 (反恐精英)";
        return "平局";
    }
}

using UnityEngine;
using System;

/// <summary>
/// RoundManager - 回合管理器
/// 负责回合计时、回合阶段管理和回合流程控制
/// </summary>
public class RoundManager : MonoBehaviour
{
    [Header("回合设置")]
    [SerializeField] private float standardRoundTime = 115f; // 1 分 55 秒
    [SerializeField] private float buyTime = 15f; // 购买阶段时间
    [SerializeField] private float roundEndDelay = 5f; // 回合结束延迟
    
    [Header("引用")]
    [SerializeField] private GameManager gameManager;
    [SerializeField] private EconomySystem economySystem;
    
    // 回合状态
    public enum RoundPhase
    {
        Buying,      // 购买阶段
        Playing,     // 游戏阶段
        Ending,      // 回合结束
        WaitingNext  // 等待下一回合
    }
    
    public RoundPhase currentPhase { get; private set; }
    public float timeRemaining { get; private set; }
    public int currentRound { get; private set; }
    
    // 事件
    public event Action<float> OnTimeUpdate;
    public event Action OnRoundStart;
    public event Action OnBuyPhaseEnd;
    public event Action OnRoundEnd;
    public event Action<int, int> OnRoundResult; // (tScore, ctScore)
    
    private bool isRoundActive = false;
    private Coroutine roundCoroutine;
    
    private void Start()
    {
        if (gameManager == null)
        {
            gameManager = FindObjectOfType<GameManager>();
        }
        
        if (economySystem == null)
        {
            economySystem = FindObjectOfType<EconomySystem>();
        }
    }
    
    /// <summary>
    /// 开始新回合
    /// </summary>
    public void StartRound(int roundNumber, float roundTime = -1f)
    {
        if (roundTime < 0)
        {
            roundTime = standardRoundTime;
        }
        
        currentRound = roundNumber;
        timeRemaining = roundTime;
        currentPhase = RoundPhase.Buying;
        isRoundActive = true;
        
        Debug.Log($"=== 第 {roundNumber} 回合开始 ===");
        Debug.Log($"回合时间：{roundTime}秒，购买阶段：{buyTime}秒");
        
        // 触发回合开始事件
        OnRoundStart?.Invoke();
        
        // 开始回合协程
        if (roundCoroutine != null)
        {
            StopCoroutine(roundCoroutine);
        }
        roundCoroutine = StartCoroutine(RoundLoop());
    }
    
    /// <summary>
    /// 回合主循环协程
    /// </summary>
    private IEnumerator RoundLoop()
    {
        // 购买阶段倒计时
        float buyTimeRemaining = buyTime;
        while (buyTimeRemaining > 0 && isRoundActive)
        {
            buyTimeRemaining -= Time.deltaTime;
            timeRemaining = buyTimeRemaining + (standardRoundTime - buyTime);
            currentPhase = RoundPhase.Buying;
            
            OnTimeUpdate?.Invoke(timeRemaining);
            yield return null;
        }
        
        // 购买阶段结束
        if (isRoundActive)
        {
            currentPhase = RoundPhase.Playing;
            OnBuyPhaseEnd?.Invoke();
            Debug.Log("购买阶段结束，游戏开始！");
        }
        
        // 游戏阶段倒计时
        float gameTimeRemaining = standardRoundTime - buyTime;
        while (gameTimeRemaining > 0 && isRoundActive)
        {
            gameTimeRemaining -= Time.deltaTime;
            timeRemaining = gameTimeRemaining;
            currentPhase = RoundPhase.Playing;
            
            OnTimeUpdate?.Invoke(timeRemaining);
            yield return null;
        }
        
        // 时间结束
        if (isRoundActive)
        {
            TimeExpired();
        }
    }
    
    /// <summary>
    /// 时间耗尽
    /// </summary>
    private void TimeExpired()
    {
        timeRemaining = 0;
        currentPhase = RoundPhase.Ending;
        Debug.Log("时间耗尽！");
        
        // 默认 CT 方获胜（如果 T 方未下包）
        EndRound(1, RoundWinReason.TimeExpired);
    }
    
    /// <summary>
    /// 手动结束回合
    /// </summary>
    /// <param name="winner">获胜方：0=T 方，1=CT 方</param>
    /// <param name="reason">获胜原因</param>
    public void EndRound(int winner, RoundWinReason reason = RoundWinReason.Elimination)
    {
        if (!isRoundActive)
        {
            Debug.LogWarning("回合已结束，无法再次结束");
            return;
        }
        
        isRoundActive = false;
        currentPhase = RoundPhase.Ending;
        timeRemaining = 0;
        
        Debug.Log($"回合结束：{reason}，获胜方：{(winner == 0 ? "T 方" : "CT 方")}");
        
        // 触发回合结束事件
        OnRoundEnd?.Invoke();
        
        // 通知 GameManager
        if (gameManager != null)
        {
            gameManager.EndRound(winner);
        }
        
        // 触发回合结果事件
        OnRoundResult?.Invoke(gameManager?.tScore ?? 0, gameManager?.ctScore ?? 0);
        
        // 等待延迟后准备下一回合
        StartCoroutine(WaitForNextRound());
    }
    
    /// <summary>
    /// 等待下一回合协程
    /// </summary>
    private IEnumerator WaitForNextRound()
    {
        currentPhase = RoundPhase.WaitingNext;
        yield return new WaitForSeconds(roundEndDelay);
        
        Debug.Log($"准备进入第 {currentRound + 1} 回合");
        
        // 通知 GameManager 开始下一回合
        if (gameManager != null)
        {
            gameManager.StartNextRound();
        }
    }
    
    /// <summary>
    /// 立即开始下一回合（跳过延迟）
    /// </summary>
    public void ForceNextRound()
    {
        if (roundCoroutine != null)
        {
            StopCoroutine(roundCoroutine);
        }
        
        if (gameManager != null)
        {
            gameManager.StartNextRound();
        }
    }
    
    /// <summary>
    /// 添加额外时间（例如炸弹延长）
    /// </summary>
    public void AddTime(float seconds)
    {
        if (currentPhase == RoundPhase.Playing)
        {
            timeRemaining += seconds;
            Debug.Log($"添加时间：{seconds}秒，剩余：{timeRemaining}秒");
            OnTimeUpdate?.Invoke(timeRemaining);
        }
    }
    
    /// <summary>
    /// 检查回合是否活跃
    /// </summary>
    public bool IsRoundActive()
    {
        return isRoundActive;
    }
    
    /// <summary>
    /// 获取格式化时间显示
    /// </summary>
    public string GetFormattedTime()
    {
        int minutes = Mathf.FloorToInt(timeRemaining / 60);
        int seconds = Mathf.FloorToInt(timeRemaining % 60);
        return $"{minutes:D2}:{seconds:D2}";
    }
}

/// <summary>
/// 回合获胜原因
/// </summary>
public enum RoundWinReason
{
    Elimination,      // 歼灭
    TimeExpired,      // 时间耗尽
    BombExploded,     // 炸弹爆炸
    BombDefused       // 炸弹被拆
}

using UnityEngine;
using UnityEngine.UI;

/// <summary>
/// 回合 HUD - 显示回合时间、比分、阶段信息
/// </summary>
public class RoundHUD : MonoBehaviour
{
    [Header("UI 组件引用")]
    [Tooltip("回合时间文本")]
    public Text roundTimeText;
    
    [Tooltip("比分文本（T 方:CT 方）")]
    public Text scoreText;
    
    [Tooltip("回合阶段文本（购买阶段/游戏阶段）")]
    public Text roundPhaseText;
    
    [Tooltip("阶段颜色（购买阶段用不同颜色）")]
    public Text phaseColorText;
    
    [Header("显示设置")]
    [Tooltip("时间格式：MM:SS 或 SS")]
    public bool showMinutes = true;
    
    [Tooltip("是否显示回合阶段")]
    public bool showPhase = true;
    
    private int tScore = 0;
    private int ctScore = 0;
    private bool isBuyPhase = false;
    
    /// <summary>
    /// 更新回合时间显示
    /// </summary>
    public void UpdateRoundTime(float remainingTime)
    {
        if (roundTimeText != null)
        {
            int minutes = Mathf.FloorToInt(remainingTime / 60f);
            int seconds = Mathf.FloorToInt(remainingTime % 60f);
            
            if (showMinutes)
            {
                roundTimeText.text = string.Format("{0:00}:{1:00}", minutes, seconds);
            }
            else
            {
                roundTimeText.text = seconds.ToString("00");
            }
        }
    }
    
    /// <summary>
    /// 更新比分
    /// </summary>
    public void UpdateScore(int tScore, int ctScore)
    {
        this.tScore = tScore;
        this.ctScore = ctScore;
        
        if (scoreText != null)
        {
            scoreText.text = string.Format("T 方：{0} - {1} CT 方", tScore, ctScore);
        }
    }
    
    /// <summary>
    /// 设置回合阶段
    /// </summary>
    public void SetRoundPhase(bool isBuyPhase)
    {
        this.isBuyPhase = isBuyPhase;
        
        if (roundPhaseText != null && showPhase)
        {
            if (isBuyPhase)
            {
                roundPhaseText.text = "购买阶段";
                if (phaseColorText != null)
                {
                    phaseColorText.color = Color.green;
                }
            }
            else
            {
                roundPhaseText.text = "游戏阶段";
                if (phaseColorText != null)
                {
                    phaseColorText.color = Color.yellow;
                }
            }
        }
    }
    
    /// <summary>
    /// 回合结束时隐藏阶段显示
    /// </summary>
    public void HidePhase()
    {
        if (roundPhaseText != null)
        {
            roundPhaseText.text = "";
        }
    }
    
    /// <summary>
    /// 添加 T 方一分
    /// </summary>
    public void AddTScore()
    {
        tScore++;
        UpdateScore(tScore, ctScore);
    }
    
    /// <summary>
    /// 添加 CT 方一分
    /// </summary>
    public void AddCTScore()
    {
        ctScore++;
        UpdateScore(tScore, ctScore);
    }
    
    /// <summary>
    /// 重置比分（新游戏开始）
    /// </summary>
    public void ResetScore()
    {
        tScore = 0;
        ctScore = 0;
        UpdateScore(tScore, ctScore);
    }
}

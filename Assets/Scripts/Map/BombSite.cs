using UnityEngine;
using System.Collections.Generic;

/// <summary>
/// BombSite - 爆点区域管理
/// 管理 A/B 爆点的状态、玩家占领和 C4 放置
/// </summary>
public class BombSite : MonoBehaviour
{
    [Header("爆点设置")]
    [SerializeField] private string siteName = "A"; // A 或 B
    [SerializeField] private float siteRadius = 5f; // 爆点半径
    [SerializeField] private LayerMask playerLayer; // 玩家层
    
    [Header("引用")]
    [SerializeField] private Transform siteCenter; // 爆点中心
    [SerializeField] private GameObject siteMarker; // 爆点标记物（用于视觉反馈）
    
    // 爆点状态
    public enum SiteStatus
    {
        Empty,      // 无炸弹
        BombPlaced, // 已放置 C4
        BombExploded // 炸弹已爆炸
    }
    
    public SiteStatus currentStatus { get; private set; }
    public C4Bomb placedBomb { get; private set; }
    
    // 事件
    public delegate void SiteEventHandler(BombSite site);
    public event SiteEventHandler OnBombPlaced;
    public event SiteEventHandler OnBombExploded;
    public event SiteEventHandler OnBombDefused;
    
    // 在爆点内的玩家列表
    private List<GameObject> playersInSite = new List<GameObject>();
    
    private void Start()
    {
        currentStatus = SiteStatus.Empty;
        placedBomb = null;
        
        if (siteMarker == null)
        {
            siteMarker = gameObject;
        }
    }
    
    private void Update()
    {
        CheckPlayersInSite();
    }
    
    /// <summary>
    /// 检查哪些玩家在爆点内
    /// </summary>
    private void CheckPlayersInSite()
    {
        Collider[] colliders = Physics.OverlapSphere(siteCenter.position, siteRadius, playerLayer);
        
        // 更新在爆点内的玩家列表
        playersInSite.Clear();
        foreach (Collider collider in colliders)
        {
            if (!playersInSite.Contains(collider.gameObject))
            {
                playersInSite.Add(collider.gameObject);
            }
        }
        
        // 移除已离开爆点的玩家
        for (int i = playersInSite.Count - 1; i >= 0; i--)
        {
            if (!colliders.Contains(playersInSite[i].GetComponent<Collider>()))
            {
                playersInSite.RemoveAt(i);
            }
        }
    }
    
    /// <summary>
    /// 放置 C4 炸弹
    /// </summary>
    /// <param name="player">放置炸弹的玩家</param>
    /// <param name="bomb">C4 炸弹实例</param>
    public bool TryPlaceBomb(GameObject player, C4Bomb bomb)
    {
        if (currentStatus != SiteStatus.Empty)
        {
            Debug.Log($"爆点{siteName}已有炸弹，无法再次放置");
            return false;
        }
        
        if (!IsPlayerInSite(player))
        {
            Debug.Log($"玩家不在爆点{siteName}范围内，无法放置炸弹");
            return false;
        }
        
        currentStatus = SiteStatus.BombPlaced;
        placedBomb = bomb;
        
        // 设置炸弹位置为爆点中心
        bomb.transform.position = siteCenter.position;
        bomb.transform.SetParent(siteCenter);
        
        // 激活炸弹
        bomb.Activate();
        
        Debug.Log($"玩家 {player.name} 在爆点{siteName}放置了 C4 炸弹");
        
        // 触发事件
        OnBombPlaced?.Invoke(this);
        
        return true;
    }
    
    /// <summary>
    /// 拆除炸弹
    /// </summary>
    /// <param name="player">拆除炸弹的玩家</param>
    public bool TryDefuseBomb(GameObject player)
    {
        if (currentStatus != SiteStatus.BombPlaced || placedBomb == null)
        {
            Debug.Log($"爆点{siteName}没有可拆除的炸弹");
            return false;
        }
        
        if (!IsPlayerInSite(player))
        {
            Debug.Log($"玩家不在爆点{siteName}范围内，无法拆除炸弹");
            return false;
        }
        
        // 拆除炸弹
        placedBomb.Deactivate();
        currentStatus = SiteStatus.Empty;
        placedBomb = null;
        
        Debug.Log($"玩家 {player.name} 拆除了爆点{siteName}的 C4 炸弹");
        
        // 触发事件
        OnBombDefused?.Invoke(this);
        
        return true;
    }
    
    /// <summary>
    /// 炸弹爆炸
    /// </summary>
    public void ExplodeBomb()
    {
        if (currentStatus != SiteStatus.BombPlaced)
        {
            Debug.LogWarning($"爆点{siteName}状态异常，无法爆炸");
            return;
        }
        
        currentStatus = SiteStatus.BombExploded;
        
        // 触发自定义爆炸效果
        CreateExplosionEffect();
        
        Debug.Log($"爆点{siteName}的 C4 炸弹已爆炸！");
        
        // 触发事件
        OnBombExploded?.Invoke(this);
    }
    
    /// <summary>
    /// 创建爆炸效果
    /// </summary>
    private void CreateExplosionEffect()
    {
        // TODO: 创建爆炸粒子效果、闪光效果等
        // 这里可以添加一个爆炸预制体实例化
    }
    
    /// <summary>
    /// 重置爆点状态（用于回合开始）
    /// </summary>
    public void ResetSite()
    {
        if (placedBomb != null)
        {
            placedBomb.Deactivate();
            placedBomb = null;
        }
        
        currentStatus = SiteStatus.Empty;
        playersInSite.Clear();
        
        Debug.Log($"爆点{siteName}已重置");
    }
    
    /// <summary>
    /// 检查玩家是否在爆点内
    /// </summary>
    public bool IsPlayerInSite(GameObject player)
    {
        if (player == null) return false;
        
        Vector3 playerPos = player.transform.position;
        float distance = Vector3.Distance(siteCenter.position, playerPos);
        
        return distance <= siteRadius;
    }
    
    /// <summary>
    /// 获取爆点名称
    /// </summary>
    public string GetSiteName()
    {
        return siteName;
    }
    
    /// <summary>
    /// 获取爆点半径
    /// </summary>
    public float GetSiteRadius()
    {
        return siteRadius;
    }
    
    /// <summary>
    /// 获取在爆点内的玩家数量
    /// </summary>
    public int GetPlayerCountInSite()
    {
        return playersInSite.Count;
    }
    
    /// <summary>
    /// 获取在爆点内的玩家列表
    /// </summary>
    public List<GameObject> GetPlayersInSite()
    {
        return new List<GameObject>(playersInSite);
    }
}

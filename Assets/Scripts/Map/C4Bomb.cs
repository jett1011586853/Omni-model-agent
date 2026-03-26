using UnityEngine;
using System;

/// <summary>
/// C4Bomb - C4 炸弹逻辑
/// 管理炸弹的放置、倒计时和爆炸
/// </summary>
public class C4Bomb : MonoBehaviour
{
    [Header("炸弹设置")]
    [SerializeField] private float bombTimer = 40f; // 炸弹倒计时（秒）
    [SerializeField] private float explosionRadius = 10f; // 爆炸半径
    [SerializeField] private int explosionDamage = 100; // 爆炸伤害
    
    [Header("音效")]
    [SerializeField] private AudioClip placeSound; // 放置音效
    [SerializeField] private AudioClip tickSound; // 倒计时音效
    [SerializeField] private AudioClip explodeSound; // 爆炸音效
    
    [Header("视觉反馈")]
    [SerializeField] private GameObject bombModel; // 炸弹模型
    [SerializeField] private GameObject explosionEffect; // 爆炸效果
    
    // 炸弹状态
    public enum BombState
    {
        Inactive,   // 未激活
        Active,     // 已激活（倒计时中）
        Exploded    // 已爆炸
    }
    
    public BombState currentState { get; private set; }
    public float timeRemaining { get; private set; }
    public bool isDefused { get; private set; }
    
    // 引用
    private BombSite bombSite;
    private GameObject planter; // 放置炸弹的玩家
    
    // 事件
    public event Action<float> OnTimerUpdate;
    public event Action OnBombExploded;
    
    private Coroutine timerCoroutine;
    
    private void Start()
    {
        currentState = BombState.Inactive;
        timeRemaining = bombTimer;
        isDefused = false;
        
        if (bombModel != null)
        {
            bombModel.SetActive(false);
        }
    }
    
    /// <summary>
    /// 激活炸弹（开始倒计时）
    /// </summary>
    public void Activate()
    {
        if (currentState != BombState.Inactive)
        {
            Debug.LogWarning("炸弹已激活，无法再次激活");
            return;
        }
        
        currentState = BombState.Active;
        timeRemaining = bombTimer;
        isDefused = false;
        
        // 显示炸弹模型
        if (bombModel != null)
        {
            bombModel.SetActive(true);
        }
        
        // 播放放置音效
        PlaySound(placeSound);
        
        // 开始倒计时协程
        timerCoroutine = StartCoroutine(BombTimer());
        
        Debug.Log("C4 炸弹已激活，开始倒计时");
    }
    
    /// <summary>
    /// 炸弹倒计时协程
    /// </summary>
    private IEnumerator BombTimer()
    {
        while (timeRemaining > 0 && currentState == BombState.Active)
        {
            timeRemaining -= Time.deltaTime;
            
            // 触发计时器更新事件
            OnTimerUpdate?.Invoke(timeRemaining);
            
            // 每隔 1 秒播放一次滴答声
            if (Mathf.Floor(timeRemaining) != Mathf.Floor(timeRemaining + Time.deltaTime))
            {
                PlaySound(tickSound);
            }
            
            yield return null;
        }
        
        // 时间耗尽，爆炸
        if (currentState == BombState.Active && !isDefused)
        {
            Explode();
        }
    }
    
    /// <summary>
    /// 停止炸弹（拆除）
    /// </summary>
    public void Deactivate()
    {
        if (currentState != BombState.Active)
        {
            Debug.LogWarning("炸弹未激活，无法拆除");
            return;
        }
        
        isDefused = true;
        currentState = BombState.Inactive;
        
        // 停止倒计时协程
        if (timerCoroutine != null)
        {
            StopCoroutine(timerCoroutine);
        }
        
        // 隐藏炸弹模型
        if (bombModel != null)
        {
            bombModel.SetActive(false);
        }
        
        Debug.Log("C4 炸弹已拆除");
    }
    
    /// <summary>
    /// 炸弹爆炸
    /// </summary>
    public void Explode()
    {
        if (currentState != BombState.Active)
        {
            Debug.LogWarning("炸弹状态异常，无法爆炸");
            return;
        }
        
        currentState = BombState.Exploded;
        timeRemaining = 0;
        
        // 播放爆炸音效
        PlaySound(explodeSound);
        
        // 显示爆炸效果
        if (explosionEffect != null)
        {
            GameObject effectInstance = Instantiate(explosionEffect, transform.position, transform.rotation);
            Destroy(effectInstance, 2f); // 2 秒后销毁效果
        }
        
        // 隐藏炸弹模型
        if (bombModel != null)
        {
            bombModel.SetActive(false);
        }
        
        // 对范围内玩家造成伤害
        DealDamage();
        
        Debug.Log("C4 炸弹爆炸！");
        
        // 触发爆炸事件
        OnBombExploded?.Invoke();
        
        // 通知爆点
        if (bombSite != null)
        {
            bombSite.ExplodeBomb();
        }
    }
    
    /// <summary>
    /// 对范围内玩家造成伤害
    /// </summary>
    private void DealDamage()
    {
        Collider[] colliders = Physics.OverlapSphere(transform.position, explosionRadius);
        
        foreach (Collider collider in colliders)
        {
            PlayerHealth health = collider.GetComponent<PlayerHealth>();
            if (health != null)
            {
                health.TakeDamage(explosionDamage);
                Debug.Log($"玩家 {collider.name} 受到爆炸伤害：{explosionDamage}");
            }
        }
    }
    
    /// <summary>
    /// 播放音效
    /// </summary>
    private void PlaySound(AudioClip clip)
    {
        if (clip != null)
        {
            AudioSource.PlayClipAtPoint(clip, transform.position);
        }
    }
    
    /// <summary>
    /// 设置关联的爆点
    /// </summary>
    public void SetBombSite(BombSite site)
    {
        bombSite = site;
    }
    
    /// <summary>
    /// 设置放置炸弹的玩家
    /// </summary>
    public void SetPlanter(GameObject player)
    {
        planter = player;
    }
    
    /// <summary>
    /// 获取炸弹状态
    /// </summary>
    public string GetStatusText()
    {
        switch (currentState)
        {
            case BombState.Inactive:
                return "未激活";
            case BombState.Active:
                return $"倒计时：{timeRemaining:F1}秒";
            case BombState.Exploded:
                return "已爆炸";
            default:
                return "未知状态";
        }
    }
    
    private void OnDestroy()
    {
        if (timerCoroutine != null)
        {
            StopCoroutine(timerCoroutine);
        }
    }
}

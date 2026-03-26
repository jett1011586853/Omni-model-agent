using UnityEngine;

/// <summary>
/// 玩家健康组件 - 管理生命值、护甲和死亡
/// </summary>
public class PlayerHealth : MonoBehaviour
{
    [Header("生命值设置")]
    [Tooltip("最大生命值")]
    public float maxHealth = 100f;
    
    [Tooltip("当前生命值")]
    public float currentHealth = 100f;

    [Header("护甲设置")]
    [Tooltip("最大护甲值")]
    public float maxArmor = 100f;
    
    [Tooltip("当前护甲值")]
    public float currentArmor = 100f;
    
    [Tooltip("护甲减伤比例 (0-1)")]
    public float armorDamageReduction = 0.5f;

    [Header("重生设置")]
    [Tooltip("重生延迟时间")]
    public float respawnDelay = 3f;
    
    [Tooltip("是否启用重生")]
    public bool enableRespawn = true;

    [Header("伤害反馈")]
    [Tooltip("受伤时屏幕震动强度")]
    public float damageScreenShake = 0.1f;
    
    [Tooltip("受伤时屏幕红色叠加强度")]
    public float damageScreenFade = 0.3f;

    // 状态
    private bool isDead;
    private bool isRespawning;
    private float respawnTimer;

    // 事件
    public delegate void HealthChanged(float health, float armor);
    public event HealthChanged OnHealthChanged;

    public delegate void PlayerDied();
    public event PlayerDied OnPlayerDied;
    
    public delegate void PlayerKilled(int victimId, int killerId);
    public event PlayerKilled OnPlayerKilled;

    public delegate void PlayerRespawned();
    public event PlayerRespawned OnPlayerRespawned;

    // 玩家 ID (用于经济系统)
    [Header("玩家设置")]
    [Tooltip("玩家 ID (用于经济系统)")]
    public int playerId = 0;

    void Start()
    {
        isDead = false;
        isRespawning = false;
    }

    void Update()
    {
        HandleRespawn();
    }

    /// <summary>
    /// 处理重生
    /// </summary>
    private void HandleRespawn()
    {
        if (isRespawning)
        {
            respawnTimer -= Time.deltaTime;
            
            if (respawnTimer <= 0)
            {
                Respawn();
            }
        }
    }

    /// <summary>
    /// 受到损伤
    /// </summary>
    /// <param name="damage">伤害值</param>
    public void TakeDamage(float damage)
    {
        if (isDead) return;

        // 计算实际伤害
        float actualDamage = CalculateDamage(damage);
        
        // 优先扣除护甲
        if (currentArmor > 0)
        {
            float armorDamage = damage * armorDamageReduction;
            currentArmor = Mathf.Max(0, currentArmor - armorDamage);
            
            // 剩余伤害扣生命值
            float healthDamage = damage - armorDamage;
            currentHealth = Mathf.Max(0, currentHealth - healthDamage);
        }
        else
        {
            currentHealth = Mathf.Max(0, currentHealth - actualDamage);
        }

        // 触发健康变化事件
        OnHealthChanged?.Invoke(currentHealth, currentArmor);

        // 检查是否死亡
        if (currentHealth <= 0)
        {
            Die();
        }
    }

    /// <summary>
    /// 计算实际伤害
    /// </summary>
    /// <param name="damage">原始伤害</param>
    /// <returns>实际伤害</returns>
    private float CalculateDamage(float damage)
    {
        // 可以根据护甲值调整伤害
        if (currentArmor > 0)
        {
            return damage * (1f - armorDamageReduction);
        }
        return damage;
    }

    /// <summary>
    /// 死亡
    /// </summary>
    public void Die()
    {
        if (isDead) return;

        isDead = true;
        OnPlayerDied?.Invoke();
        
        // 触发击杀事件 (killerId = -1 表示自杀或环境伤害)
        OnPlayerKilled?.Invoke(playerId, -1);

        // 启用重生
        if (enableRespawn)
        {
            StartRespawn();
        }
    }
    
    /// <summary>
    /// 被击杀 (指定击杀者)
    /// </summary>
    /// <param name="killerId">击杀者 ID</param>
    public void DieByPlayer(int killerId)
    {
        if (isDead) return;

        isDead = true;
        OnPlayerDied?.Invoke();
        
        // 触发击杀事件
        OnPlayerKilled?.Invoke(playerId, killerId);

        // 启用重生
        if (enableRespawn)
        {
            StartRespawn();
        }
    }

    /// <summary>
    /// 开始重生
    /// </summary>
    private void StartRespawn()
    {
        isRespawning = true;
        respawnTimer = respawnDelay;
    }

    /// <summary>
    /// 重生
    /// </summary>
    private void Respawn()
    {
        isRespawning = false;
        isDead = false;
        
        // 恢复生命值和护甲
        currentHealth = maxHealth;
        currentArmor = maxArmor;
        
        OnPlayerRespawned?.Invoke();
        
        Debug.Log("Player respawned!");
    }

    /// <summary>
    /// 恢复生命值
    /// </summary>
    /// <param name="amount">恢复量</param>
    public void Heal(float amount)
    {
        currentHealth = Mathf.Min(maxHealth, currentHealth + amount);
        OnHealthChanged?.Invoke(currentHealth, currentArmor);
    }

    /// <summary>
    /// 恢复护甲
    /// </summary>
    /// <param name="amount">恢复量</param>
    public void RepairArmor(float amount)
    {
        currentArmor = Mathf.Min(maxArmor, currentArmor + amount);
        OnHealthChanged?.Invoke(currentHealth, currentArmor);
    }

    /// <summary>
    /// 设置生命值
    /// </summary>
    public void SetHealth(float health)
    {
        currentHealth = Mathf.Clamp(health, 0, maxHealth);
        OnHealthChanged?.Invoke(currentHealth, currentArmor);
    }

    /// <summary>
    /// 设置护甲值
    /// </summary>
    public void SetArmor(float armor)
    {
        currentArmor = Mathf.Clamp(armor, 0, maxArmor);
        OnHealthChanged?.Invoke(currentHealth, currentArmor);
    }

    /// <summary>
    /// 获取最大生命值
    /// </summary>
    public float GetMaxHealth()
    {
        return maxHealth;
    }

    /// <summary>
    /// 获取当前生命值
    /// </summary>
    public float GetCurrentHealth()
    {
        return currentHealth;
    }

    /// <summary>
    /// 获取最大护甲值
    /// </summary>
    public float GetMaxArmor()
    {
        return maxArmor;
    }

    /// <summary>
    /// 获取当前护甲值
    /// </summary>
    public float GetCurrentArmor()
    {
        return currentArmor;
    }

    /// <summary>
    /// 获取是否死亡
    /// </summary>
    public bool IsDead()
    {
        return isDead;
    }

    /// <summary>
    /// 获取生命值百分比
    /// </summary>
    public float GetHealthPercentage()
    {
        return currentHealth / maxHealth;
    }

    /// <summary>
    /// 获取护甲百分比
    /// </summary>
    public float GetArmorPercentage()
    {
        return currentArmor / maxArmor;
    }
}

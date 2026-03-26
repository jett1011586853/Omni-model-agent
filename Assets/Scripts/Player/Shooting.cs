using UnityEngine;

/// <summary>
/// 射击组件 - 处理射击逻辑和后坐力
/// </summary>
public class Shooting : MonoBehaviour
{
    [Header("射击设置")]
    [Tooltip("射击频率 (每秒射击次数)")]
    public float fireRate = 6f;
    
    [Tooltip("射击范围")]
    public float range = 100f;
    
    [Tooltip("射击伤害")]
    public float damage = 25f;

    [Header("后坐力设置")]
    [Tooltip("垂直后坐力")]
    public float verticalRecoil = 0.02f;
    
    [Tooltip("水平后坐力范围")]
    public float horizontalRecoilRange = 0.01f;
    
    [Tooltip("后坐力恢复速度")]
    public float recoilRecoverySpeed = 5f;

    [Header("瞄准辅助")]
    [Tooltip("瞄准辅助启用")]
    public bool aimAssistEnabled = true;
    
    [Tooltip("瞄准辅助强度")]
    public float aimAssistStrength = 0.5f;

    // 状态
    private float fireTimer;
    private Vector3 recoilOffset;
    private bool isFiring;
    private LayerMask targetLayers;

    void Start()
    {
        // 设置目标层级掩码
        targetLayers = LayerMask.GetMask("Enemy", "Player");
    }

    void Update()
    {
        HandleFiring();
        HandleRecoilRecovery();
    }

    /// <summary>
    /// 处理射击
    /// </summary>
    private void HandleFiring()
    {
        if (isFiring)
        {
            fireTimer -= Time.deltaTime;
            
            if (fireTimer <= 0)
            {
                Fire();
                fireTimer = 1f / fireRate;
            }
        }
    }

    /// <summary>
    /// 处理後坐力恢复
    /// </summary>
    private void HandleRecoilRecovery()
    {
        if (!isFiring)
        {
            // 恢复后坐力
            recoilOffset = Vector3.MoveTowards(recoilOffset, Vector3.zero, recoilRecoverySpeed * Time.deltaTime);
        }
    }

    /// <summary>
    /// 开始射击
    /// </summary>
    public void StartFiring()
    {
        isFiring = true;
        fireTimer = 0f;
    }

    /// <summary>
    /// 停止射击
    /// </summary>
    public void StopFiring()
    {
        isFiring = false;
    }

    /// <summary>
    /// 执行射击
    /// </summary>
    private void Fire()
    {
        // 应用后坐力
        ApplyRecoil();
        
        // 执行射线检测
        RaycastFire();
        
        // 触发射击事件
        OnFire();
    }

    /// <summary>
    /// 应用后坐力
    /// </summary>
    private void ApplyRecoil()
    {
        // 垂直后坐力
        float vertical = verticalRecoil;
        
        // 水平后坐力 (随机)
        float horizontal = Random.Range(-horizontalRecoilRange, horizontalRecoilRange);
        
        recoilOffset += new Vector3(horizontal, vertical, 0);
    }

    /// <summary>
    /// 射线检测射击
    /// </summary>
    private void RaycastFire()
    {
        Camera mainCamera = Camera.main;
        if (mainCamera == null) return;

        // 从屏幕中心发射射线
        Ray ray = mainCamera.ScreenPointToRay(new Vector3(Screen.width / 2, Screen.height / 2, 0));
        
        RaycastHit hit;
        if (Physics.Raycast(ray, out hit, range, targetLayers))
        {
            // 击中目标
            OnHit(hit);
        }
    }

    /// <summary>
    /// 获取当前后坐力偏移
    /// </summary>
    public Vector3 GetRecoilOffset()
    {
        return recoilOffset;
    }

    /// <summary>
    /// 重置后坐力
    /// </summary>
    public void ResetRecoil()
    {
        recoilOffset = Vector3.zero;
    }

    /// <summary>
    /// 射击事件
    /// </summary>
    private void OnFire()
    {
        // 可以在这里触发音效、粒子等
    }

    /// <summary>
    /// 击中事件
    /// </summary>
    /// <param name="hit">射线检测结果</param>
    private void OnHit(RaycastHit hit)
    {
        // 可以在这里应用伤害、触发特效等
        Debug.Log($"Hit {hit.collider.name} at {hit.point}");
    }

    /// <summary>
    /// 获取射击频率
    /// </summary>
    public float GetFireRate()
    {
        return fireRate;
    }

    /// <summary>
    /// 设置射击频率
    /// </summary>
    public void SetFireRate(float rate)
    {
        fireRate = rate;
    }

    /// <summary>
    /// 获取射击范围
    /// </summary>
    public float GetRange()
    {
        return range;
    }

    /// <summary>
    /// 设置射击范围
    /// </summary>
    public void SetRange(float r)
    {
        range = r;
    }

    /// <summary>
    /// 获取伤害值
    /// </summary>
    public float GetDamage()
    {
        return damage;
    }

    /// <summary>
    /// 设置伤害值
    /// </summary>
    public void SetDamage(float d)
    {
        damage = d;
    }
}

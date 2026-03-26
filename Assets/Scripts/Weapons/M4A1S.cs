using UnityEngine;

/// <summary>
/// M4A1-S - M4A1-S 消音卡宾枪实现
/// 特点：带消音器、弹药消耗快、适合 ECO 局
/// </summary>
public class M4A1S : WeaponBase
{
    [Header("M4A1-S 特殊属性")]
    [SerializeField] private float m4sDamage = 32f; // 比 M4A4 稍高
    [SerializeField] private float m4sFireRate = 9f; // 射速稍慢
    [SerializeField] private int m4sMagazineSize = 25; // 弹匣较小
    [SerializeField] private int m4sReserveAmmo = 75; // 弹药较少
    
    [Header("消音器设置")]
    [SerializeField] private float silenceDistance = 30f; // 消音有效距离
    [SerializeField] private float damagePenalty = 0.8f; // 远距离伤害惩罚
    
    [Header("喷射模式设置")]
    [SerializeField] private Vector3[] sprayPattern;
    
    private int currentShotCount = 0;
    
    private void Start()
    {
        base.Start();
        weaponName = "M4A1-S";
        damage = m4sDamage;
        fireRate = m4sFireRate;
        magazineSize = m4sMagazineSize;
        reserveAmmo = m4sReserveAmmo;
        currentMagazineAmmo = m4sMagazineSize;
        
        // 定义 M4A1-S 的喷射模式
        sprayPattern = new Vector3[]
        {
            new Vector3(0, 0.07f, 0),    // 第 1 发：轻微向上
            new Vector3(0.04f, 0.08f, 0), // 第 2 发：向上微右
            new Vector3(-0.04f, 0.08f, 0), // 第 3 发：向上微左
            new Vector3(0, 0.075f, 0),   // 第 4 发：轻微向上
            new Vector3(0.02f, 0.075f, 0), // 第 5 发：向上微右
        };
    }
    
    /// <summary>
    /// 重写射击方法，应用喷射模式和消音器效果
    /// </summary>
    public override void Fire()
    {
        if (isReloading) return;
        
        float timeSinceLastFire = Time.time - lastFireTime;
        if (timeSinceLastFire < 1f / fireRate) return;
        
        if (currentMagazineAmmo <= 0)
        {
            PlaySound(emptySound);
            return;
        }
        
        lastFireTime = Time.time;
        currentMagazineAmmo--;
        isFiring = true;
        
        ApplyM4SRecoil();
        PlaySound(fireSound);
        
        // 触发射线检测（带消音器效果）
        RaycastFireWithSilencer();
        
        currentShotCount = (currentShotCount + 1) % sprayPattern.Length;
        
        if (currentMagazineAmmo == 0)
        {
            isFiring = false;
        }
    }
    
    /// <summary>
    /// M4A1-S 特殊后坐力应用
    /// </summary>
    private void ApplyM4SRecoil()
    {
        Vector3 currentPattern = sprayPattern[currentShotCount];
        currentRecoilY += currentPattern.y;
        currentRecoilX += currentPattern.x;
        
        // M4A1-S 后坐力控制较好
        currentRecoilY *= 0.88f;
        currentRecoilX *= 0.88f;
    }
    
    /// <summary>
    /// 带消音器的射线射击
    /// </summary>
    protected void RaycastFireWithSilencer()
    {
        Vector3 adjustedDirection = weaponTransform.forward;
        adjustedDirection.y += currentRecoilY;
        adjustedDirection.x += currentRecoilX;
        adjustedDirection.Normalize();
        
        Ray ray = new Ray(weaponTransform.position, adjustedDirection);
        
        if (Physics.Raycast(ray, out RaycastHit hit, 100f))
        {
            float distance = hit.distance;
            float actualDamage = damage;
            
            // 超过消音距离后伤害下降
            if (distance > silenceDistance)
            {
                actualDamage *= damagePenalty;
            }
            
            Debug.Log($"M4A1-S 击中：{hit.collider.name}，距离：{distance:F1}m，伤害：{actualDamage:F1}");
            
            PlayerHealth targetHealth = hit.collider.GetComponent<PlayerHealth>();
            if (targetHealth != null)
            {
                targetHealth.TakeDamage((int)actualDamage);
            }
            
            CreateHitEffect(hit.point);
        }
    }
    
    /// <summary>
    /// 重写重新装填
    /// </summary>
    public override void Reload()
    {
        if (isReloading || currentMagazineAmmo == magazineSize || reserveAmmo <= 0)
        {
            return;
        }
        
        isReloading = true;
        PlaySound(reloadSound);
        
        StartCoroutine(ReloadCoroutineWithDelay(2.5f));
    }
    
    /// <summary>
    /// 带延迟的重新装填协程
    /// </summary>
    protected System.Collections.IEnumerator ReloadCoroutineWithDelay(float delay)
    {
        yield return new WaitForSeconds(delay);
        
        int ammoNeeded = magazineSize - currentMagazineAmmo;
        int ammoToLoad = Mathf.Min(ammoNeeded, reserveAmmo);
        
        currentMagazineAmmo += ammoToLoad;
        reserveAmmo -= ammoToLoad;
        
        isReloading = false;
        Debug.Log($"M4A1-S 重新装填完成：{currentMagazineAmmo}/{magazineSize}");
    }
}

using UnityEngine;

/// <summary>
/// M4A4 - M4A4 卡宾枪实现
/// 特点：较平稳的喷射模式、高射速、需要热管理
/// </summary>
public class M4A4 : WeaponBase
{
    [Header("M4A4 特殊属性")]
    [SerializeField] private float m4Damage = 30f; // 比 AK-47 稍低
    [SerializeField] private float m4FireRate = 10f; // 射速更快
    [SerializeField] private int m4MagazineSize = 30;
    [SerializeField] private int m4ReserveAmmo = 90;
    
    [Header("喷射模式设置")]
    [SerializeField] private Vector3[] sprayPattern; // 较平稳的喷射模式
    
    private int currentShotCount = 0;
    
    private void Start()
    {
        base.Start();
        weaponName = "M4A4";
        damage = m4Damage;
        fireRate = m4FireRate;
        magazineSize = m4MagazineSize;
        reserveAmmo = m4ReserveAmmo;
        currentMagazineAmmo = m4MagazineSize;
        
        // 定义 M4A4 的平稳喷射模式
        // 模式：主要向上，波动较小
        sprayPattern = new Vector3[]
        {
            new Vector3(0, 0.08f, 0),    // 第 1 发：轻微向上
            new Vector3(0.05f, 0.09f, 0), // 第 2 发：向上微右
            new Vector3(-0.05f, 0.09f, 0), // 第 3 发：向上微左
            new Vector3(0, 0.08f, 0),    // 第 4 发：轻微向上
            new Vector3(0.03f, 0.085f, 0), // 第 5 发：向上微右
            new Vector3(-0.03f, 0.085f, 0), // 第 6 发：向上微左
        };
    }
    
    /// <summary>
    /// 重写射击方法，应用喷射模式
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
        
        ApplyM4Recoil();
        PlaySound(fireSound);
        
        // 触发射线检测
        RaycastFireWithSpray();
        
        currentShotCount = (currentShotCount + 1) % sprayPattern.Length;
        
        if (currentMagazineAmmo == 0)
        {
            isFiring = false;
        }
    }
    
    /// <summary>
    /// M4A4 特殊后坐力应用
    /// </summary>
    private void ApplyM4Recoil()
    {
        // 根据喷射模式应用后坐力
        Vector3 currentPattern = sprayPattern[currentShotCount];
        currentRecoilY += currentPattern.y;
        currentRecoilX += currentPattern.x;
        
        // M4A4 后坐力衰减更快（更平稳）
        currentRecoilY *= 0.85f;
        currentRecoilX *= 0.85f;
    }
    
    /// <summary>
    /// 带喷射模式的射线射击
    /// </summary>
    protected void RaycastFireWithSpray()
    {
        // 根据后坐力调整射击方向
        Vector3 adjustedDirection = weaponTransform.forward;
        adjustedDirection.y += currentRecoilY;
        adjustedDirection.x += currentRecoilX;
        adjustedDirection.Normalize();
        
        Ray ray = new Ray(weaponTransform.position, adjustedDirection);
        
        if (Physics.Raycast(ray, out RaycastHit hit, 100f))
        {
            Debug.Log($"M4A4 击中：{hit.collider.name}");
            
            // 如果有 PlayerHealth 组件，造成伤害
            PlayerHealth targetHealth = hit.collider.GetComponent<PlayerHealth>();
            if (targetHealth != null)
            {
                targetHealth.TakeDamage((int)damage);
            }
            
            // 添加击中效果
            CreateHitEffect(hit.point);
        }
    }
    
    /// <summary>
    /// 重写重新装填，M4A4 装填速度正常
    /// </summary>
    public override void Reload()
    {
        if (isReloading || currentMagazineAmmo == magazineSize || reserveAmmo <= 0)
        {
            return;
        }
        
        isReloading = true;
        PlaySound(reloadSound);
        
        StartCoroutine(ReloadCoroutineWithDelay(2.8f));
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
        Debug.Log($"M4A4 重新装填完成：{currentMagazineAmmo}/{magazineSize}");
    }
}

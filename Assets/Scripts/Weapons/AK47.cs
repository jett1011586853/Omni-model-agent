using UnityEngine;

/// <summary>
/// AK47 - AK-47 步枪实现
/// 特点：高伤害、明显后坐力、独特的喷射模式
/// </summary>
public class AK47 : WeaponBase
{
    [Header("AK-47 特殊属性")]
    [SerializeField] private float akDamage = 35f; // 比 M4 更高伤害
    [SerializeField] private float akFireRate = 8f; // 射速稍慢
    [SerializeField] private int akMagazineSize = 30;
    [SerializeField] private int akReserveAmmo = 90;
    
    [Header("喷射模式设置")]
    [SerializeField] private Vector3[] sprayPattern; // 喷射模式数组
    
    private int currentShotCount = 0;
    
    private void Start()
    {
        base.Start();
        weaponName = "AK-47";
        damage = akDamage;
        fireRate = akFireRate;
        magazineSize = akMagazineSize;
        reserveAmmo = akReserveAmmo;
        currentMagazineAmmo = akMagazineSize;
        
        // 定义 AK-47 的经典喷射模式
        // 模式：上 - 右 - 左 - 下 的规律
        sprayPattern = new Vector3[]
        {
            new Vector3(0, 0.1f, 0),   // 第 1 发：向上
            new Vector3(0.1f, 0.15f, 0), // 第 2 发：向上偏右
            new Vector3(-0.1f, 0.15f, 0), // 第 3 发：向上偏左
            new Vector3(0, 0.1f, 0),   // 第 4 发：向上
            new Vector3(0.05f, 0.1f, 0), // 第 5 发：向上微右
            new Vector3(-0.05f, 0.1f, 0), // 第 6 发：向上微左
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
        
        ApplyAKRecoil();
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
    /// 应用 AK-47 后坐力
    /// </summary>
    protected override void ApplyRecoil()
    {
        // 在 Fire 方法中已经处理
    }
    
    /// <summary>
    /// AK-47 特殊后坐力应用
    /// </summary>
    private void ApplyAKRecoil()
    {
        // 根据喷射模式应用后坐力
        Vector3 currentPattern = sprayPattern[currentShotCount];
        currentRecoilY += currentPattern.y;
        currentRecoilX += currentPattern.x;
        
        // 后坐力衰减
        currentRecoilY *= 0.9f;
        currentRecoilX *= 0.9f;
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
            Debug.Log($"AK-47 击中：{hit.collider.name}");
            
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
    /// 重写重新装填，AK-47 装填稍慢
    /// </summary>
    public override void Reload()
    {
        if (isReloading || currentMagazineAmmo == magazineSize || reserveAmmo <= 0)
        {
            return;
        }
        
        isReloading = true;
        PlaySound(reloadSound);
        
        // AK-47 装填时间稍长
        StartCoroutine(ReloadCoroutineWithDelay(3f));
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
        Debug.Log($"AK-47 重新装填完成：{currentMagazineAmmo}/{magazineSize}");
    }
}

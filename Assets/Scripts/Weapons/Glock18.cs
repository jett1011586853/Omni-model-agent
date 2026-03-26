using UnityEngine;

/// <summary>
/// Glock18 - 格洛克 18 手枪实现
/// 特点：T 方标配手枪、射速快、适合近距离战斗
/// </summary>
public class Glock18 : WeaponBase
{
    [Header("Glock18 特殊属性")]
    [SerializeField] private float glockDamage = 15f; // 手枪伤害较低
    [SerializeField] private float glockFireRate = 12f; // 射速非常快
    [SerializeField] private int glockMagazineSize = 20;
    [SerializeField] private int glockReserveAmmo = 60;
    
    [Header("爆头加成设置")]
    [SerializeField] private float headshotMultiplier = 2.5f; // 爆头伤害倍率
    
    [Header("喷射模式设置")]
    [SerializeField] private Vector3[] sprayPattern;
    
    private int currentShotCount = 0;
    
    private void Start()
    {
        base.Start();
        weaponName = "Glock-18";
        damage = glockDamage;
        fireRate = glockFireRate;
        magazineSize = glockMagazineSize;
        reserveAmmo = glockReserveAmmo;
        currentMagazineAmmo = glockMagazineSize;
        
        // 定义 Glock18 的喷射模式（手枪模式较不规则）
        sprayPattern = new Vector3[]
        {
            new Vector3(0, 0.05f, 0),    // 第 1 发：轻微向上
            new Vector3(0.03f, 0.06f, 0), // 第 2 发：向上微右
            new Vector3(-0.02f, 0.06f, 0), // 第 3 发：向上微左
            new Vector3(0, 0.05f, 0),    // 第 4 发：轻微向上
        };
    }
    
    /// <summary>
    /// 重写射击方法
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
        
        ApplyGlockRecoil();
        PlaySound(fireSound);
        
        // 触发射线检测
        RaycastFireWithHeadshot();
        
        currentShotCount = (currentShotCount + 1) % sprayPattern.Length;
        
        if (currentMagazineAmmo == 0)
        {
            isFiring = false;
        }
    }
    
    /// <summary>
    /// Glock18 后坐力应用
    /// </summary>
    private void ApplyGlockRecoil()
    {
        Vector3 currentPattern = sprayPattern[currentShotCount];
        currentRecoilY += currentPattern.y;
        currentRecoilX += currentPattern.x;
        
        // 手枪后坐力恢复较快
        currentRecoilY *= 0.9f;
        currentRecoilX *= 0.9f;
    }
    
    /// <summary>
    /// 带爆头检测的射线射击
    /// </summary>
    protected void RaycastFireWithHeadshot()
    {
        Vector3 adjustedDirection = weaponTransform.forward;
        adjustedDirection.y += currentRecoilY;
        adjustedDirection.x += currentRecoilX;
        adjustedDirection.Normalize();
        
        Ray ray = new Ray(weaponTransform.position, adjustedDirection);
        
        if (Physics.Raycast(ray, out RaycastHit hit, 100f))
        {
            Debug.Log($"Glock-18 击中：{hit.collider.name}");
            
            PlayerHealth targetHealth = hit.collider.GetComponent<PlayerHealth>();
            if (targetHealth != null)
            {
                // 检测是否为头部命中（通过碰撞层判断）
                bool isHeadshot = hit.collider.CompareTag("Head");
                float actualDamage = damage;
                
                if (isHeadshot)
                {
                    actualDamage *= headshotMultiplier;
                    Debug.Log("爆头！伤害加成");
                }
                
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
        
        // 手枪装填较快
        StartCoroutine(ReloadCoroutineWithDelay(2f));
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
        Debug.Log($"Glock-18 重新装填完成：{currentMagazineAmmo}/{magazineSize}");
    }
}
